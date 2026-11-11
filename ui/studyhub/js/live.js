// =====================================================
// StudyHub – Anbindung an die echte App (server/app.py)
//
// Läuft nur, wenn StudyHub mit Sitzungs-Token geöffnet wird:
//   http://127.0.0.1:<port>/ui/studyhub/index.html?t=<token>
// Ohne Token (z. B. Doppelklick auf index.html) bleibt alles bei den Beispieldaten.
// Mit Token zeigt StudyHub nie Beispieldaten: bis die App antwortet „Lädt …“, bei einem Fehler eine Meldung.
//
// Die Daten kommen fertig aus GET /api/studyhub (server/studyhub.py, siehe docs/studyhub-api.md):
// DATEN und MODUL_DETAILS werden damit ersetzt. Lernplan-Status und Notizen speichert der
// Server (PATCH /api/studyhub/lernplan). KI-Aufgaben laufen über POST /api/ai/run.
// Finanzmathematik bleibt im Demo-Modus (--demo) als Beispielmodul drin, im normalen Programm nicht.
// =====================================================

const LIVE = {
  token: new URLSearchParams(location.search).get("t") || "",
  aktiv: false, // true, sobald die API geantwortet hat
  fehler: null, // Meldung, wenn die App beim Start nicht geantwortet hat
  abgleich: false, // true, solange LIVE.synchronisieren() einen Abgleich verfolgt
  sync: null, // { configured, demo, running, letzter, fehler } aus /api/studyhub
  laedt: null, // laufende KI-Aktion, z. B. "thema-<dateiId>"
  anki: null, // { ready, decks, hinweis } von /api/anki/status, erst nach Klick geladen
  ankiLaeuft: false,
  klausurEdit: null, // Modul-ID, solange dort der Klausurtermin bearbeitet wird
  pfade: {}, // Kurz-ID → Dateipfad (Pfade nie direkt ins HTML schreiben)
};

// Statische Platzhalter der Kopfzeile (Beispieldaten) gleich ersetzen
if (LIVE.token) {
  document.getElementById("sync-text").textContent = "Verbinde mit der App …";
  document.getElementById("avatar").textContent = "";
}

// Mit Token, aber noch ohne Antwort der App: route() zeigt dann LIVE.wartenSeite() statt Beispieldaten
LIVE.wartet = () => Boolean(LIVE.token) && !LIVE.aktiv;

LIVE.wartenSeite = function () {
  if (!LIVE.fehler) {
    return `<div class="platzhalter"><div class="platzhalter-icon">${icon("sync", 28)}</div><h2>Lädt deine Kurse …</h2></div>`;
  }
  return `
    <div class="platzhalter glas">
      <div class="platzhalter-icon">${icon("logo", 28)}</div>
      <h2>Keine Verbindung zur App</h2>
      <p>${esc(LIVE.fehler)}. Läuft StudyHub noch? Sonst die App beenden (⌘Q) und neu öffnen.</p>
      <button class="pille" data-aktion="live-neu-laden">Erneut versuchen</button>
    </div>`;
};

// Beispielmodul merken, bevor DATEN mit echten Kursen überschrieben wird
const BEISPIEL_MODUL = { ...DATEN.semester[0].module.find((m) => m.id === "fima"), beispiel: true };

// Text sicher ins HTML schreiben (für Texte, die nicht schon vom Server maskiert sind)
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

async function api(pfad, { method = "GET", body } = {}) {
  const antwort = await fetch(pfad, {
    method,
    headers: { "x-app-token": LIVE.token, ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const daten = await antwort.json().catch(() => ({}));
  if (!antwort.ok) throw new Error(daten.detail || `Fehler ${antwort.status}`);
  return daten;
}

// Kleiner Markdown-Umbau für KI-Antworten
function inline(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
}
function markdown(md) {
  let html = "";
  let liste = false;
  for (const roh of String(md || "").split("\n")) {
    const zeile = roh.trim();
    const punkt = zeile.match(/^[-*•]\s+(.*)/) || zeile.match(/^\d+[.)]\s+(.*)/);
    if (punkt) {
      if (!liste) { html += "<ul>"; liste = true; }
      html += `<li>${inline(punkt[1])}</li>`;
      continue;
    }
    if (liste) { html += "</ul>"; liste = false; }
    const titel = zeile.match(/^#{1,4}\s+(.*)/);
    if (titel) html += `<h4>${inline(titel[1])}</h4>`;
    else if (zeile) html += `<p>${inline(zeile)}</p>`;
  }
  return html + (liste ? "</ul>" : "");
}

const titelAus = (name) => name.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ").trim();
const groesse = (b) => (b > 1e6 ? (b / 1e6).toFixed(1).replace(".", ",") + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB");
const LERNBAR = /\.(pdf|txt|md|pptx|docx)$/i;

// ---------- Daten laden ----------

// Server-Daten so ergänzen, dass app.js sie wie die Mock-Daten zeichnen kann.
// Dateipfade bekommen Kurz-IDs, damit sie nie roh in HTML-Attributen landen.
function aufbereiten(modulId, d) {
  d.live = true;
  // d.kurs: Kursordner, kommt vom Server
  const idVonPfad = {};
  let n = 0;
  const kurzId = (pfad) => {
    if (!idVonPfad[pfad]) {
      idVonPfad[pfad] = `${modulId}-d${n++}`;
      LIVE.pfade[idVonPfad[pfad]] = pfad;
    }
    return idVonPfad[pfad];
  };

  for (const g of d.dokumente) {
    for (const f of g.dateien) {
      f.id = kurzId(f.pfad);
      f.art = f.typ;
      f.bytes = f.groesse;
      f.groesse = groesse(f.bytes);
      f.lernbar = LERNBAR.test(f.pfad);
    }
  }
  for (const e of [...d.lernplan.kapitel.flatMap((k) => k.eintraege), ...d.lernplan.bereiche.flatMap((b) => b.aufgaben)]) {
    e.pfad = e.id;
    e.id = kurzId(e.pfad);
  }
  for (const f of d.ausgeblendet || []) f.id = kurzId(f.pfad);
  for (const t of d.themen) t.dateiId = kurzId(t.pfad);
  for (const k of d.karten.liste) {
    k.lernplan = k.pfad ? kurzId(k.pfad) : null; // eigene und Anki-Karten gehören zu keiner Datei
    if (!k.formel?.text) k.formel = null; // KI-Karten haben keine eigene Formel
  }
  // Stand beim Laden merken (für Fortschritt nach Klicks, siehe lernstand() in app.js)
  LERNPLAN_START[modulId] = zaehleStatus(alleEintraege(d.lernplan));
}

// Hinzugefügte Skills eines Kurses speichern (PATCH /api/studyhub/skills); false bei Fehler
LIVE.skillsSpeichern = async function (modulId, skills) {
  try {
    await api("/api/studyhub/skills", { method: "PATCH", body: { kurs: MODUL_DETAILS[modulId].kurs, skills } });
    return true;
  } catch (fehler) {
    zeigeToast(fehler.message);
    return false;
  }
};

LIVE.laden = async function () {
  const studyhub = await api("/api/studyhub");
  LIVE.sync = studyhub.sync;
  LIVE.pfade = {};

  for (const id of Object.keys(MODUL_DETAILS)) if (id !== "fima") delete MODUL_DETAILS[id];
  for (const [id, d] of Object.entries(studyhub.details)) {
    aufbereiten(id, d);
    MODUL_DETAILS[id] = d;
    zustand.skills[id] = studyhub.skills?.[d.kurs] || [];
  }

  const daten = studyhub.daten;
  DATEN.nutzer = { ...daten.nutzer, vorname: null }; // der Server kennt nur die Uni-ID, keinen Vornamen
  DATEN.naechsteKlausur = daten.naechsteKlausur; // null: ILIAS kennt keine Klausurtermine
  DATEN.heuteDran = daten.heuteDran;
  DATEN.semester = daten.semester.length ? daten.semester : [{ id: "meine-kurse", name: "Meine Kurse", status: "aktuell", module: [] }];
  for (const m of DATEN.semester.flatMap((s) => s.module)) m.live = true;
  // Beispielmodul nur im Demo-Modus (--demo); im normalen Programm erscheinen nur echte Kurse
  if (LIVE.sync.demo) {
    const aktuell = DATEN.semester.find((s) => s.status === "aktuell") || DATEN.semester[0];
    aktuell.module.push(BEISPIEL_MODUL);
  } else {
    delete MODUL_DETAILS.fima;
  }
  for (const s of DATEN.semester) if (s.status === "aktuell") zustand.offeneSemester.add(s.id);

  $("#avatar").textContent = DATEN.nutzer.initialen;
  if (zustand.karten && MODUL_DETAILS[zustand.karten.modul]?.live) {
    neueRunde(zustand.karten.modul, zustand.karten.filter, true);
  }
  LIVE.statusZeigen();
};

LIVE.statusZeigen = function () {
  const s = LIVE.sync;
  if (!s) return;
  document.body.classList.toggle("ist-demo", Boolean(s.demo)); // Marke „DEMO“ und Hinweisband
  document.title = s.demo ? "StudyHub · Demo" : "StudyHub";
  $("#sync-text").textContent = s.demo ? "Demo-Modus · Beispielkurse"
    : s.running ? "Synchronisiere mit ILIAS …"
      : s.configured ? `ILIAS verbunden · ${s.letzter}` : "ILIAS noch nicht verbunden";
  $("#sync-knopf").title = $("#sync-text").textContent; // in kleineren Fenstern ist die Statuszeile ausgeblendet
};

LIVE.start = async function () {
  if (!LIVE.token) return;
  LIVE.fehler = null;
  try {
    await LIVE.laden();
    LIVE.aktiv = true;
    document.body.classList.add("ist-live");
    zustand.animieren = true;
    // Noch nicht eingerichtet (erster Start): direkt zur Einrichtung „Mit Uni-Login verbinden“
    if (!LIVE.sync.demo && !LIVE.sync.configured && aktuelleRoute().seite === "start") {
      location.hash = "#/einrichtung";
      return;
    }
    route();
    if (LIVE.sync.running && !LIVE.sync.demo) LIVE.synchronisieren(true); // läuft schon: Fortschritt zeigen
  } catch (fehler) {
    LIVE.fehler = fehler.message;
    $("#sync-text").textContent = "Keine Verbindung zur App";
    route();
  }
};

// ---------- Speichern ----------

// Lernplan-Status und Notiz an den Server (Notizen gesammelt, damit nicht jeder Tastendruck einzeln geht)
const notizTimer = {};
LIVE.eintragGeaendert = function (eintrag, nurNotiz = false) {
  if (!LIVE.aktiv || !eintrag?.pfad) return;
  const senden = (body) => api("/api/studyhub/lernplan", { method: "PATCH", body: { pfad: eintrag.pfad, ...body } })
    .catch((f) => zeigeToast(`Speichern fehlgeschlagen: ${f.message}`));
  if (nurNotiz) {
    clearTimeout(notizTimer[eintrag.pfad]);
    notizTimer[eintrag.pfad] = setTimeout(() => senden({ notiz: nurText(eintrag.notiz) }), 600);
  } else {
    senden({ status: eintrag.status });
    // Ampel des passenden Themas gleich mitziehen (wie server/studyhub.py)
    for (const d of Object.values(MODUL_DETAILS)) {
      const thema = d.live && d.themen.find((t) => t.pfad === eintrag.pfad);
      if (thema) thema.stand = { erledigt: "sitzt", nochmal: "unsicher", inArbeit: "unsicher" }[eintrag.status] || "offen";
    }
  }
};

// Karten-Bewertungen speichert der Server (noch) nicht; „Nochmal“ landet über den Lernplan beim Server.
// Bewertung speichern (SM-2 auf dem Server) und den Lernstand der Karte sofort nachziehen
LIVE.karteBewertet = async function (modulId, karte, wert) {
  if (!LIVE.aktiv || !karte.id) return; // Beispielkarten haben keinen Lernstand
  try {
    const r = await api("/api/cards/review", { method: "POST", body: { id: karte.id, bewertung: wert } });
    Object.assign(karte, { neu: false, faellig: false, inTagen: r.inTagen });
    const d = MODUL_DETAILS[modulId];
    d.karten.faellig = d.karten.liste.filter((k) => k.faellig !== false).length;
  } catch (fehler) {
    zeigeToast(`Bewertung nicht gespeichert: ${fehler.message}`);
  }
};

// ---------- Aktionen ----------

// Abgleich starten und verfolgen; laeuftSchon: nur verfolgen (z. B. Hintergrund-Job beim Öffnen der App)
LIVE.synchronisieren = async function (laeuftSchon = false) {
  if (LIVE.abgleich) return;
  LIVE.abgleich = true;
  const knopf = $("#sync-knopf");
  const statusEl = $("#sync-status");
  const vorher = Object.keys(LIVE.pfade).length;
  const anzeigen = (an) => {
    knopf.disabled = an;
    knopf.classList.toggle("laedt", an);
    statusEl.classList.toggle("laedt", an);
  };
  try {
    if (!laeuftSchon) {
      const r = await api("/api/sync", { method: "POST" });
      if (!r.started) {
        zeigeToast(r.message || "Abgleich nicht gestartet");
        return;
      }
    }
    anzeigen(true);
    $("#sync-text").textContent = "Synchronisiere mit ILIAS …";
    // Fortschritt aus /api/status, z. B. „3 von 8 Kursen fertig · 1:20“; die App bricht nach 45 Minuten ab
    for (let i = 0; i < 1000; i++) {
      await pause(3000);
      const status = await api("/api/status");
      if (!status.running) break;
      $("#sync-text").textContent = `Synchronisiere … ${status.progress?.text || ""}`.trim();
      knopf.title = $("#sync-text").textContent; // in kleineren Fenstern ist die Statuszeile ausgeblendet
    }
    await LIVE.laden();
    route();
    const neu = Object.keys(LIVE.pfade).length - vorher;
    // fehler = Zahl der fehlgeschlagenen Abrufe in Folge (state.json „crawl_failures“), 0 nach Erfolg
    zeigeToast(LIVE.sync.fehler > 0 ? "ILIAS-Abgleich fehlgeschlagen: kein Netz oder Anmeldung abgelehnt (Einstellungen › ILIAS-Zugang)"
      : `Abgleich fertig · ${Math.max(0, neu)} neue Dateien`);
  } catch (fehler) {
    zeigeToast(fehler.message);
  } finally {
    LIVE.abgleich = false;
    anzeigen(false);
    LIVE.statusZeigen();
  }
};

// KI-Aufgabe für eine Datei ("thema" | "flashcards"), danach alles neu laden.
// Gibt die Nummer des Themas zurück, das zu dieser Datei gehört (die Reihenfolge kann sich ändern).
async function kiAusfuehren(modulId, dateiId, aufgabe) {
  const pfad = LIVE.pfade[dateiId];
  LIVE.laedt = `${aufgabe}-${dateiId}`;
  neuZeichnen();
  try {
    await api("/api/ai/run", { method: "POST", body: { path: pfad, task: aufgabe } });
    await LIVE.laden();
    const thema = MODUL_DETAILS[modulId].themen.find((t) => t.pfad === pfad);
    if (thema) zustand.thema[modulId] = thema.nr;
    return thema?.nr || null;
  } catch (fehler) {
    zeigeToast(`KI: ${fehler.message}`);
    return null;
  } finally {
    LIVE.laedt = null;
    neuZeichnen();
  }
}

// Alle Klicks auf data-aktion="live-…" landen hier (siehe app.js)
LIVE.klick = async function (ds) {
  const d = MODUL_DETAILS[ds.modul];
  const thema = d?.themen.find((t) => t.nr === Number(ds.nr));
  switch (ds.aktion) {
    case "live-neu-laden":
      LIVE.fehler = null;
      $("#sync-text").textContent = "Verbinde mit der App …";
      route();
      LIVE.start();
      break;

    case "live-dokument":
      zeigeToast("Wird in der Vorschau geöffnet …");
      api("/api/open", { method: "POST", body: { path: LIVE.pfade[ds.id] } }).catch((f) => zeigeToast(f.message));
      break;

    case "live-suche-oeffnen":
      sucheSchliessen();
      zeigeToast("Wird in der Vorschau geöffnet …");
      api("/api/open", { method: "POST", body: { path: ds.pfad } }).catch((f) => zeigeToast(f.message));
      break;

    case "live-finder":
      api("/api/reveal", { method: "POST", body: { path: LIVE.pfade[ds.id] } }).catch((f) => zeigeToast(f.message));
      break;

    case "live-teilen": {
      const ziel = ds.ziel === "telegram" ? "Telegram" : "reMarkable";
      zeigeToast(`Wird an ${ziel} geschickt …`);
      try {
        const r = await api("/api/share", { method: "POST", body: { path: LIVE.pfade[ds.id], task: ds.aufgabe, target: ds.ziel } });
        zeigeToast(`An ${ziel} geschickt${r.via && r.via !== ziel ? ` (${r.via})` : ""}`);
      } catch (fehler) {
        zeigeToast(fehler.message);
      }
      break;
    }

    case "live-thema-erstellen":
      if (await kiAusfuehren(ds.modul, ds.id, "thema")) zeigeToast("Lernthema fertig");
      break;

    case "live-karten": {
      const hatKarten = d.karten.liste.some((k) => k.lernplan === thema.dateiId);
      const nr = hatKarten ? thema.nr : await kiAusfuehren(ds.modul, thema.dateiId, "flashcards");
      if (!nr) return;
      neueRunde(ds.modul, String(nr), true);
      location.hash = `#/modul/${ds.modul}/karteikarten`;
      break;
    }

    case "live-einfacher": {
      const schluessel = `${ds.modul}-${thema.nr}`;
      if (zustand.einfach.has(schluessel)) {
        zustand.einfach.delete(schluessel);
        neuZeichnen();
        return;
      }
      // „Einfacher erklärt“ steckt im strukturierten Thema; fehlt es, erst erzeugen
      if (!thema.einfacher) {
        const nr = await kiAusfuehren(ds.modul, thema.dateiId, "thema");
        if (!nr) return;
        zustand.einfach.add(`${ds.modul}-${nr}`);
      } else {
        zustand.einfach.add(schluessel);
      }
      neuZeichnen();
      break;
    }

    case "live-ausblenden":
    case "live-einblenden": {
      const ausblenden = ds.aktion === "live-ausblenden";
      try {
        await api("/api/studyhub/ausblenden", { method: "PATCH", body: { pfad: LIVE.pfade[ds.id], ausgeblendet: ausblenden } });
        await LIVE.laden();
        route();
        zeigeToast(ausblenden ? `„${ds.name}“ ausgeblendet · unten unter „Ausgeblendet“ wieder einblenden`
          : `„${ds.name}“ wieder eingeblendet`);
      } catch (fehler) {
        zeigeToast(fehler.message);
      }
      break;
    }

    case "live-hochladen":
      dateiAuswahl(ds.modul); // ohne await davor: der Dateidialog braucht den Klick als Auslöser
      break;

    // --- Karten: Anki und Textdateien ---
    case "live-anki-verbinden":
      LIVE.anki = await api("/api/anki/status").catch((f) => ({ ready: false, decks: [], hinweis: f.message }));
      neuZeichnen();
      break;
    case "live-anki-import":
    case "live-anki-export": {
      const importieren = ds.aktion === "live-anki-import";
      const deck = $("#anki-deck")?.value;
      LIVE.ankiLaeuft = true;
      neuZeichnen();
      try {
        const r = importieren
          ? await api("/api/anki/import", { method: "POST", body: { kurs: d.kurs, deck } })
          : await api("/api/anki/export", { method: "POST", body: { kurs: d.kurs } });
        if (importieren) {
          await LIVE.laden();
          neueRunde(ds.modul);
        }
        zeigeToast(importieren ? `${r.neu} Karten aus „${deck}“ übernommen${r.doppelt ? `, ${r.doppelt} schon vorhanden` : ""}`
          : `${r.neu} Karten nach Anki (${r.deck})${r.vorhanden ? `, ${r.vorhanden} waren schon da` : ""}`);
      } catch (fehler) {
        zeigeToast(fehler.message);
      } finally {
        LIVE.ankiLaeuft = false;
        neuZeichnen();
      }
      break;
    }
    case "live-karten-textimport":
      kartenTextWaehlen(ds.modul);
      break;
    case "live-karten-textexport":
      api("/api/cards/export", { method: "POST", body: { kurs: d.kurs } })
        .then((r) => zeigeToast(`${r.karten} Karten in „Downloads/${r.datei}“ gespeichert`))
        .catch((f) => zeigeToast(f.message));
      break;

    // --- Klausurtermin ---
    case "live-klausur":
      LIVE.klausurEdit = ds.modul;
      neuZeichnen("klausur-datum");
      break;
    case "live-klausur-loeschen":
      klausurSpeichern(ds.modul, "");
      break;

    // --- Eigene Zusammenfassungen ---
    case "live-zf-hochladen":
      dateiAuswahl(ds.modul, "zusammenfassung");
      break;
    case "live-zf-schreiben":
      zustand.zfEditor = ds.modul;
      neuZeichnen("zf-titel");
      break;
    case "live-zf-abbrechen":
      zustand.zfEditor = null;
      neuZeichnen();
      break;
    case "live-zf-speichern": {
      const titel = $("#zf-titel").value.trim();
      const text = $("#zf-text").value;
      try {
        const r = await api("/api/summaries", { method: "POST", body: { kurs: d.kurs, titel, text } });
        zustand.zfEditor = null;
        await LIVE.laden();
        const neu = MODUL_DETAILS[ds.modul].themen.find((t) => t.pfad === r.pfad);
        if (neu) zustand.thema[ds.modul] = neu.nr;
        neuZeichnen();
        zeigeToast("Zusammenfassung gespeichert");
      } catch (fehler) {
        zeigeToast(fehler.message);
      }
      break;
    }

    case "live-vorlesen": {
      const einfach = zustand.einfach.has(`${ds.modul}-${thema.nr}`) && thema.einfacher;
      vorlesen(`${nurText(thema.titel)}. ${nurText(einfach || thema.kernidee)} ${thema.falle ? `Typische Klausurfalle: ${nurText(thema.falle)}` : ""}`);
      break;
    }

    default:
      EINSTELLUNGEN.klick?.(ds);
  }
};

// ---------- Karteikarten: Anki und Textdateien ----------

LIVE.kartenWerkzeuge = function (m, d) {
  const a = LIVE.anki;
  const anki = !a
    ? `<button class="knopf-hell" data-aktion="live-anki-verbinden" data-modul="${m.id}">${icon("sync", 16)} Mit Anki verbinden</button>`
    : !a.ready
      ? `<p class="klein">${esc(a.hinweis)}. Danach Anki geöffnet lassen.</p>
         <button class="knopf-hell" data-aktion="live-anki-verbinden" data-modul="${m.id}">${icon("sync", 16)} Erneut versuchen</button>`
      : `<select id="anki-deck" class="eingabe auswahl" aria-label="Anki-Deck">${a.decks.map((x) => `<option>${esc(x)}</option>`).join("")}</select>
         <button class="knopf-hell" data-aktion="live-anki-import" data-modul="${m.id}" ${LIVE.ankiLaeuft ? "disabled" : ""}>${icon("plus", 16)} Deck übernehmen</button>
         <button class="knopf-hell" data-aktion="live-anki-export" data-modul="${m.id}" ${LIVE.ankiLaeuft || !d.karten.gesamt ? "disabled" : ""}>${icon("pfeil", 16)} Alle Karten nach Anki</button>`;
  return `
    <section class="karten-werkzeuge glas" aria-label="Anki und Textdateien">
      <div class="werkzeug-reihe">
        <span class="mini-titel">Anki</span>
        ${anki}
      </div>
      <div class="werkzeug-reihe">
        <span class="mini-titel">Textdatei</span>
        <button class="knopf-hell" data-aktion="live-karten-textimport" data-modul="${m.id}">${icon("plus", 16)} Importieren</button>
        <button class="knopf-hell" data-aktion="live-karten-textexport" data-modul="${m.id}" ${d.karten.gesamt ? "" : "disabled"}>${icon("dokument", 16)} Für Anki exportieren</button>
        <span class="klein">Eine Karte pro Zeile, Vorder- und Rückseite durch Tabulator getrennt (Anki: „Notizen als Text“)</span>
      </div>
    </section>`;
};

function kartenTextWaehlen(modulId) {
  const d = MODUL_DETAILS[modulId];
  const eingabe = document.createElement("input");
  eingabe.type = "file";
  eingabe.accept = ".txt,.tsv,.csv";
  eingabe.addEventListener("change", async () => {
    const datei = eingabe.files[0];
    if (!datei) return;
    const form = new FormData();
    form.append("kurs", d.kurs);
    form.append("file", datei, datei.name);
    try {
      const antwort = await fetch("/api/cards/import", { method: "POST", headers: { "x-app-token": LIVE.token }, body: form });
      const r = await antwort.json().catch(() => ({}));
      if (!antwort.ok) throw new Error(r.detail || `Fehler ${antwort.status}`);
      await LIVE.laden();
      neueRunde(modulId);
      neuZeichnen();
      zeigeToast(`${r.neu} Karten übernommen${r.doppelt ? `, ${r.doppelt} schon vorhanden` : ""}`);
    } catch (fehler) {
      zeigeToast(`Import fehlgeschlagen: ${fehler.message}`);
    }
  });
  eingabe.click();
}

// ---------- Klausurtermin (ILIAS kennt keinen) ----------

LIVE.klausurBadge = function (m) {
  if (LIVE.klausurEdit === m.id) {
    return `<span class="badge badge-edit">${icon("kalender", 14)} Klausur am
      <input type="date" id="klausur-datum" data-modul="${m.id}" value="${m.klausur?.datum || ""}" data-fokus="klausur-datum">
      ${m.klausur ? `<button class="link-leise" data-aktion="live-klausur-loeschen" data-modul="${m.id}">entfernen</button>` : ""}</span>`;
  }
  const text = !m.klausur ? "Klausurtermin eintragen"
    : m.klausur.tage === 0 ? "Klausur heute" : `Klausur in ${m.klausur.tage} ${m.klausur.tage === 1 ? "Tag" : "Tagen"}`;
  return `<button class="badge badge-knopf" data-aktion="live-klausur" data-modul="${m.id}">${icon("kalender", 14)} ${text}</button>`;
};

async function klausurSpeichern(modulId, datum) {
  const d = MODUL_DETAILS[modulId];
  try {
    await api("/api/studyhub/klausur", { method: "PATCH", body: { kurs: d.kurs, datum: datum || null } });
    LIVE.klausurEdit = null;
    await LIVE.laden();
    neuZeichnen();
    zeigeToast(datum ? "Klausurtermin gespeichert" : "Klausurtermin entfernt");
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
}

document.addEventListener("change", (e) => {
  if (e.target.id === "klausur-datum" && e.target.value) klausurSpeichern(e.target.dataset.modul, e.target.value);
});

// ---------- Tab „Zusammenfassung“ mit echten KI-Ergebnissen ----------

LIVE.tabZusammenfassung = function (m, d) {
  const laedt = (aufgabe, dateiId) => LIVE.laedt === `${aufgabe}-${dateiId}`;
  const offen = d.dokumente.flatMap((g) => g.dateien).filter((f) => f.lernbar && !d.themen.some((t) => t.pfad === f.pfad));

  const themenListe = d.themen.map((x) => `
    <li>
      <button class="thema-knopf" data-aktion="thema-waehlen" data-modul="${m.id}" data-nr="${x.nr}" data-fokus="thema-${x.nr}"
        aria-current="${x.nr === (zustand.thema[m.id] || d.themen[0]?.nr)}">
        <span class="nr">${x.nr}</span>
        <span class="zeile-text"><span class="zeile-titel">${x.titel}</span></span>
        <span class="ampel-punkt ampel-${x.stand}" aria-label="${AMPEL[x.stand]}"></span>
      </button>
    </li>`).join("");

  const offenListe = offen.map((f) => `
    <li>
      <button class="thema-knopf thema-neu" data-aktion="live-thema-erstellen" data-modul="${m.id}" data-id="${f.id}"
        data-fokus="neu-${f.id}" ${LIVE.laedt ? "disabled" : ""}>
        <span class="nr">${icon(laedt("thema", f.id) ? "sync" : "plus", 14)}</span>
        <span class="zeile-text"><span class="zeile-titel">${f.name}</span>
          <span class="mini">${laedt("thema", f.id) ? "KI liest das Dokument …" : "Lernthema erstellen"}</span></span>
      </button>
    </li>`).join("");

  const nav = `
    <nav class="zf-themen glas" aria-label="Themen">
      ${themenListe ? `<h2 class="mini-titel">Themen</h2><ul>${themenListe}</ul>` : ""}
      ${offenListe ? `<h2 class="mini-titel">Noch ohne Zusammenfassung</h2><ul>${offenListe}</ul>` : ""}
      <h2 class="mini-titel">Eigene Zusammenfassung</h2>
      <div class="zf-eigene">
        <button class="knopf-hell" data-aktion="live-zf-schreiben" data-modul="${m.id}">${icon("notiz", 16)} Schreiben</button>
        <button class="knopf-hell" data-aktion="live-zf-hochladen" data-modul="${m.id}">${icon("plus", 16)} Hochladen</button>
      </div>
    </nav>`;

  if (zustand.zfEditor === m.id) {
    return `
      <div class="zf-layout">
        ${nav}
        <form class="zf-detail zf-editor glas" onsubmit="return false">
          <p class="eyebrow">Eigene Zusammenfassung · ${m.name}</p>
          <label class="mini-titel" for="zf-titel">Titel</label>
          <input id="zf-titel" class="eingabe" maxlength="120" placeholder="z. B. Kapitel 3 – Renten" data-fokus="zf-titel">
          <label class="mini-titel" for="zf-text">Text</label>
          <textarea id="zf-text" class="eingabe" rows="16" placeholder="# Überschrift&#10;- Stichpunkt&#10;**fett** für Wichtiges"></textarea>
          <p class="klein">Wird als Markdown-Datei unter „Eigene Zusammenfassungen“ im Kurs gespeichert. Daraus lassen sich danach Karten erstellen.</p>
          <div class="zf-aktionen">
            <button class="pille" data-aktion="live-zf-speichern" data-modul="${m.id}">${icon("haken", 18)} Speichern</button>
            <button class="knopf-hell" data-aktion="live-zf-abbrechen">Abbrechen</button>
          </div>
        </form>
      </div>`;
  }

  if (!d.themen.length) {
    return `
      <div class="zf-layout">
        ${nav}
        <div class="leer-karte glas">
          <h2>Noch keine Zusammenfassung</h2>
          <p>${offen.length ? "Wähle links ein Dokument: Die KI macht daraus ein Lernthema mit Kernidee, Formeln und typischer Klausurfalle." : "Nach dem ersten Abgleich mit ILIAS erscheinen hier deine Unterlagen."}</p>
        </div>
      </div>`;
  }

  const t = d.themen.find((x) => x.nr === zustand.thema[m.id]) || d.themen[0];
  const schluessel = `${m.id}-${t.nr}`;
  const einfach = zustand.einfach.has(schluessel) && t.einfacher;
  const themaLaedt = laedt("thema", t.dateiId);
  const kartenLaedt = laedt("flashcards", t.dateiId);
  const hatKarten = d.karten.liste.some((k) => k.lernplan === t.dateiId);
  const frageLaedt = laedt("frage", t.dateiId);
  const zfAufgabe = t.strukturiert ? "thema" : "summary"; // was als „Zusammenfassung“ weitergegeben wird

  const kern = themaLaedt
    ? `<div class="schimmer" aria-label="KI arbeitet"><span></span><span></span><span></span></div>`
    : einfach
      ? `<p class="zf-text"><span class="badge badge-neu">${icon("einfach", 12)} einfacher erklärt</span><br>${t.einfacher}</p>`
      : `<p class="zf-text">${t.kernidee}</p>`;

  const formeln = t.formeln.map((f) => `
    <div class="formel glas-stark">
      <span class="mini">${f.name}</span>
      <div class="formel-ausdruck ${t.strukturiert ? "" : "begriff-text"}">${f.text}</div>
    </div>`).join("");

  return `
    <div class="zf-layout">
      ${nav}
      <article class="zf-detail mit-aura">
        <div class="aura" aria-hidden="true"></div>
        <header class="zf-kopf">
          <p class="eyebrow">${t.eigene ? t.quelle : `Thema ${t.nr} · aus ${t.quelle}`}</p>
          <div class="zf-titelzeile">
            <h2>${t.titel}</h2>
            <span class="ampel ampel-${t.stand}">${AMPEL[t.stand]}</span>
          </div>
        </header>

        <div class="zf-aktionen">
          <button class="pille" data-aktion="live-karten" data-modul="${m.id}" data-nr="${t.nr}" ${kartenLaedt || themaLaedt ? "disabled" : ""}>
            ${icon(kartenLaedt ? "sync" : "karten", 18)} ${kartenLaedt ? "Karten werden erstellt …" : hatKarten ? "Karten lernen" : "Karten erstellen"}
          </button>
          ${t.eigene ? "" : `<button class="knopf-hell" data-aktion="live-einfacher" data-modul="${m.id}" data-nr="${t.nr}" data-fokus="einfacher"
            aria-pressed="${Boolean(einfach)}" ${themaLaedt ? "disabled" : ""}>${icon("einfach", 18)} ${einfach ? "Original anzeigen" : "Einfacher erklären"}</button>`}
          <button class="knopf-hell" data-aktion="live-vorlesen" data-modul="${m.id}" data-nr="${t.nr}">${icon("lautsprecher", 18)} Vorlesen</button>
        </div>

        <section class="zf-abschnitt"><h3 class="mini-titel">${t.eigene ? "Deine Notizen" : "Kernidee"}</h3>${kern}</section>
        ${formeln ? `<section class="zf-abschnitt"><h3 class="mini-titel">${t.strukturiert ? "Formeln" : "Wichtige Begriffe"}</h3>
          <div class="formel-raster">${formeln}</div></section>` : ""}
        ${t.falle ? `<section class="falle"><h3>${icon("flagge", 18)} ${t.strukturiert ? "Typische Klausurfalle" : "Prüfungsrelevant"}</h3><p>${t.falle}</p></section>` : ""}
        ${!t.strukturiert && !t.eigene && !themaLaedt ? `
          <div class="hinweis-leiste glas">
            <p>Aus der einfachen Zusammenfassung abgeleitet. Als Lernthema aufbereitet gibt es Formeln, Klausurfalle und „Einfacher erklären“.</p>
            <button class="knopf-hell" data-aktion="live-thema-erstellen" data-modul="${m.id}" data-id="${t.dateiId}">${icon("funken", 16)} Als Lernthema aufbereiten</button>
          </div>` : ""}

        <section class="zf-abschnitt">
          <h3 class="mini-titel">Frage zu diesem Dokument</h3>
          <form class="frage-form" data-form="live-frage" data-modul="${m.id}" data-id="${t.dateiId}">
            <input class="eingabe" name="frage" maxlength="500" autocomplete="off" data-fokus="frage-${t.dateiId}"
              placeholder="z. B. „Was ist der Unterschied zwischen … und …?“" ${frageLaedt ? "disabled" : ""}>
            <button class="knopf-hell" ${frageLaedt || themaLaedt ? "disabled" : ""}>${icon(frageLaedt ? "sync" : "funken", 16)} ${frageLaedt ? "KI liest …" : "Fragen"}</button>
          </form>
          ${t.fragen.map((q, i) => `
            <details class="frage-antwort" ${i === 0 ? "open" : ""}>
              <summary>${q.frage}</summary>
              <p class="zf-text">${q.antwort}</p>
            </details>`).join("")}
        </section>

        <p class="quelle">${icon("dokument", 14)} Quelle: ${t.quelle} ·
          <button class="link-leise" data-aktion="live-dokument" data-id="${t.dateiId}">Original öffnen</button> ·
          <button class="link-leise" data-aktion="live-finder" data-id="${t.dateiId}">Im Finder zeigen</button></p>
        ${t.eigene ? "" : `
          <p class="quelle">${icon("pfeil", 14)} Weitergeben:
            <button class="link-leise" data-aktion="live-teilen" data-id="${t.dateiId}" data-aufgabe="${zfAufgabe}" data-ziel="telegram">Zusammenfassung an Telegram</button>
            ${hatKarten ? `· <button class="link-leise" data-aktion="live-teilen" data-id="${t.dateiId}" data-aufgabe="flashcards" data-ziel="telegram">Karten an Telegram</button>` : ""}
            · <button class="link-leise" data-aktion="live-teilen" data-id="${t.dateiId}" data-aufgabe="${zfAufgabe}" data-ziel="remarkable">Zusammenfassung ans reMarkable</button>
            ${/\.pdf$/i.test(t.pfad) ? `· <button class="link-leise" data-aktion="live-teilen" data-id="${t.dateiId}" data-aufgabe="original" data-ziel="remarkable">PDF ans reMarkable</button>` : ""}
          </p>`}
      </article>
    </div>`;
};

// Claude Desktop mit neuem Chat öffnen; auf einer Modulseite kennt der Auftrag den Kurs
LIVE.claudeOeffnen = async function (modulId) {
  const modul = modulId ? findeModul(modulId) : null;
  try {
    const antwort = await api("/api/claude/open", { method: "POST", body: { kurs: modul?.live ? modul.kurs : null } });
    zeigeToast(antwort.mcp ? "Claude geöffnet · Auftrag steht im neuen Chat, mit ↩ senden"
      : "Claude geöffnet · erst unter Einstellungen › KI › Claude Desktop einrichten");
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
};

// Frage zu einem Dokument (KI-Aufgabe „qa“); die Antwort erscheint im Lernthema unter der Frage
LIVE.frageStellen = async function (modulId, dateiId, frage) {
  if (!frage.trim() || LIVE.laedt) return;
  const pfad = LIVE.pfade[dateiId];
  LIVE.laedt = `frage-${dateiId}`;
  neuZeichnen();
  try {
    await api("/api/ai/run", { method: "POST", body: { path: pfad, task: "qa", question: frage.trim() } });
    await LIVE.laden();
    const thema = MODUL_DETAILS[modulId].themen.find((t) => t.pfad === pfad);
    if (thema) zustand.thema[modulId] = thema.nr;
  } catch (fehler) {
    zeigeToast(`KI: ${fehler.message}`);
  } finally {
    LIVE.laedt = null;
    neuZeichnen();
  }
};

// ---------- Suche oben (GET /api/search): Dateinamen und Text der Unterlagen ----------

let suchTimer = null;
let suchLauf = 0;

function sucheSchliessen() {
  const liste = $("#such-ergebnisse");
  if (liste) liste.hidden = true;
}

async function suchen(text) {
  const liste = $("#such-ergebnisse");
  if (text.trim().length < 2) return sucheSchliessen();
  const zeigen = (html) => { liste.innerHTML = html; liste.hidden = false; };
  if (!LIVE.aktiv) return zeigen('<p class="klein such-hinweis">Die Suche gibt es in der laufenden App.</p>');
  const lauf = ++suchLauf;
  try {
    const r = await api(`/api/search?q=${encodeURIComponent(text.trim())}`);
    if (lauf !== suchLauf) return; // inzwischen weitergetippt
    const treffer = r.treffer.map((h) => `
      <button class="such-treffer" role="option" data-aktion="live-suche-oeffnen" data-pfad="${esc(h.pfad)}">
        <span class="zeile-titel">${h.name}${h.seite ? ` · S. ${h.seite}` : ""}</span>
        <span class="mini">${h.kurs}</span>
        ${h.ausschnitt ? `<span class="klein such-ausschnitt">${h.ausschnitt}</span>` : ""}
      </button>`).join("");
    const hinweis = r.ausstehend
      ? `<p class="mini such-hinweis">${anzahl(r.ausstehend, "Datei wird", "Dateien werden")} noch für die Suche vorbereitet.</p>` : "";
    zeigen((treffer || '<p class="klein such-hinweis">Nichts gefunden.</p>') + hinweis);
  } catch (fehler) {
    zeigen(`<p class="klein such-hinweis">${esc(fehler.message)}</p>`);
  }
}

document.addEventListener("input", (e) => {
  if (e.target.id !== "suche") return;
  clearTimeout(suchTimer);
  suchTimer = setTimeout(() => suchen(e.target.value), 250);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") sucheSchliessen(); });
document.addEventListener("click", (e) => { if (!e.target.closest(".suche-rahmen")) sucheSchliessen(); });

document.addEventListener("submit", (e) => {
  const frage = e.target.closest('[data-form="live-frage"]');
  if (frage) {
    e.preventDefault();
    LIVE.frageStellen(frage.dataset.modul, frage.dataset.id, frage.elements.frage.value);
    return;
  }
});

// ---------- Eigene Dateien hochladen (POST /api/upload, siehe server/uploads.py) ----------

const UPLOAD_TYPEN = ".pdf,.txt,.md,.csv,.tex,.rtf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,"
  + ".pages,.key,.numbers,.png,.jpg,.jpeg,.gif,.heic,.zip";

// dateien: File-Objekte (Browser, Ziehen und Ablegen) oder Pfade aus dem nativen Dialog der App
LIVE.hochladen = async function (modulId, dateien, art = "material") {
  const d = MODUL_DETAILS[modulId];
  if (!d?.live || !dateien.length) return;
  const name = (x) => (typeof x === "string" ? x.split("/").pop() : x.name);
  zeigeToast(dateien.length === 1 ? `${name(dateien[0])} wird hinzugefügt …` : `${dateien.length} Dateien werden hinzugefügt …`);
  try {
    let r;
    if (typeof dateien[0] === "string") {
      r = await api("/api/upload/paths", { method: "POST", body: { course: d.kurs, paths: dateien, art } });
    } else {
      const form = new FormData();
      form.append("course", d.kurs);
      form.append("art", art);
      for (const datei of dateien) form.append("files", datei, datei.name);
      const antwort = await fetch("/api/upload", { method: "POST", headers: { "x-app-token": LIVE.token }, body: form });
      r = await antwort.json().catch(() => ({}));
      if (!antwort.ok) throw new Error(r.detail || `Fehler ${antwort.status}`);
    }
    await LIVE.laden();
    route();
    const abgelehnt = r.errors.length ? ` · ${r.errors.length} abgelehnt (${r.errors[0]})` : "";
    const ordner = art === "zusammenfassung" ? "Eigene Zusammenfassungen" : "Eigene Dateien";
    zeigeToast(`${r.saved.length} ${r.saved.length === 1 ? "Datei" : "Dateien"} unter „${ordner}“ hinzugefügt${abgelehnt}`);
  } catch (fehler) {
    zeigeToast(`Hinzufügen fehlgeschlagen: ${fehler.message}`);
  }
};

function dateiAuswahl(modulId, art = "material") {
  // App-Fenster: nativer macOS-Dialog über pywebview (main.py, Bridge.pick_files)
  if (window.pywebview?.api?.pick_files) {
    window.pywebview.api.pick_files()
      .then((pfade) => LIVE.hochladen(modulId, pfade || [], art))
      .catch((f) => zeigeToast(`Dateiauswahl fehlgeschlagen: ${f.message || f}`));
    return;
  }
  // Browser: Dateifeld; im Dokument verankert, sonst verliert WebKit es teils vor dem „change“
  const eingabe = document.createElement("input");
  eingabe.type = "file";
  eingabe.multiple = true;
  eingabe.accept = UPLOAD_TYPEN;
  eingabe.hidden = true;
  document.body.append(eingabe);
  eingabe.addEventListener("change", () => {
    LIVE.hochladen(modulId, [...eingabe.files], art);
    eingabe.remove();
  });
  eingabe.click();
}

// Ziehen und Ablegen: Auf einer Modulseite landen Dateien in diesem Kurs. Sonst nur abfangen,
// denn WebKit würde eine abgelegte Datei sonst anstelle der App im Fenster öffnen.
const zieltDatei = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
document.addEventListener("dragover", (e) => {
  if (!zieltDatei(e)) return;
  e.preventDefault();
  const r = aktuelleRoute();
  document.body.classList.toggle("ablegen", Boolean(LIVE.aktiv && r.modul && MODUL_DETAILS[r.modul]?.live));
});
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) document.body.classList.remove("ablegen"); });
document.addEventListener("drop", (e) => {
  if (!zieltDatei(e)) return;
  e.preventDefault();
  document.body.classList.remove("ablegen");
  const r = aktuelleRoute();
  if (LIVE.aktiv && r.modul && MODUL_DETAILS[r.modul]?.live) LIVE.hochladen(r.modul, [...e.dataTransfer.files]);
  else zeigeToast("Zum Hinzufügen erst ein Modul öffnen");
});

// ---------- Automatisch neu laden ----------
// Ergebnisse, die außerhalb von StudyHub entstehen (z. B. Lernthemen aus Claude Desktop über den
// MCP-Server), erscheinen ohne Neustart: beim
// Zurückwechseln ins Fenster und alle 30 Sekunden. Gezeichnet wird nur, wenn sich etwas geändert hat,
// und nie während einer Lernrunde, eines Gesprächs, einer KI-Aktion oder in Formularen.

const NEULADEN_ABSTAND = 4000; // ms, Mindestabstand zwischen zwei Abfragen
let zuletztGeladen = Date.now();

const datenStand = () => JSON.stringify([
  DATEN.semester.flatMap((s) => s.module.map((m) => [m.id, m.fortschritt, m.info, m.zeile, m.neu])),
  Object.entries(MODUL_DETAILS).map(([id, d]) => [id, d.themen, d.karten?.liste?.length,
    d.dokumente?.reduce((n, g) => n + g.dateien.length, 0)]),
]);

function ruhig() {
  if (!LIVE.aktiv || LIVE.laedt || document.hidden || $("#sync-knopf")?.disabled) return false;
  const r = aktuelleRoute();
  if (r.seite && r.seite !== "start") return false; // Kurse, Einstellungen, Einrichtung: Eingaben nicht verwerfen
  if (r.tab === "karteikarten") return false; // Lernrunde nicht stören
  const feld = document.activeElement;
  return !(feld?.matches("input, textarea, [contenteditable]") && (feld.value || feld.textContent));
}

async function stillNeuLaden() {
  if (!ruhig() || Date.now() - zuletztGeladen < NEULADEN_ABSTAND) return;
  zuletztGeladen = Date.now();
  const vorher = datenStand();
  try {
    await LIVE.laden();
  } catch {
    return; // Server kurz nicht erreichbar: beim nächsten Mal wieder versuchen
  }
  if (datenStand() !== vorher && ruhig()) {
    neuZeichnen();
    zeigeToast("Neue Ergebnisse geladen");
  }
}

window.addEventListener("focus", stillNeuLaden);
document.addEventListener("visibilitychange", () => { if (!document.hidden) stillNeuLaden(); });
setInterval(stillNeuLaden, 30000);
