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
  voiceReady: false, // ElevenLabs eingerichtet?
  laedt: null, // laufende KI-Aktion, z. B. "thema-<dateiId>"
  anki: null, // { ready, decks, hinweis } von /api/anki/status, erst nach Klick geladen
  ankiLaeuft: false,
  klausurEdit: null, // Modul-ID, solange dort der Klausurtermin bearbeitet wird
  pfade: {}, // Kurz-ID → Dateipfad (Pfade nie direkt ins HTML schreiben)
  tutor: {
    kurs: null, status: null, frage: null, verlauf: [], phase: "laden", busy: "", ton: true, lauf: 0, recorder: null, audio: null,
    agent: null, // laufendes Gespräch mit dem ElevenLabs Agent
    agentModus: "", // "connecting" | "speaking" | "listening"
    modus: "abfrage", // "abfrage" (Frage für Frage) | "gespraech" (freies Lerngespräch über /api/tutor/chat)
    chatFrage: null, // offene Frage im Lerngespräch (ID)
    chatKurs: null, // Kurs im Lerngespräch; kann sich per Sprache ändern („Lass uns Statistik machen“)
  },
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

// Kleiner Markdown-Umbau für Antworten des Tutors
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
  d.kurs = d.tutor.kurs;
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

LIVE.laden = async function () {
  const [studyhub, tutor] = await Promise.all([
    api("/api/studyhub"),
    api("/api/tutor/status").catch(() => null),
  ]);
  LIVE.sync = studyhub.sync;
  LIVE.voiceReady = Boolean(tutor?.voice_ready);
  LIVE.pfade = {};

  for (const id of Object.keys(MODUL_DETAILS)) if (id !== "fima") delete MODUL_DETAILS[id];
  for (const [id, d] of Object.entries(studyhub.details)) {
    aufbereiten(id, d);
    MODUL_DETAILS[id] = d;
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

    // --- Sprachtutor ---
    case "live-tutor-vorbereiten": tutorVorbereiten(ds.modul); break;
    case "live-tutor-start":
    case "live-tutor-weiter": tutorNaechsteFrage(); break;
    case "live-tutor-ton":
      LIVE.tutor.ton = !LIVE.tutor.ton;
      if (!LIVE.tutor.ton) LIVE.tutorStopp(false);
      neuZeichnen();
      break;
    case "live-tutor-chat": chatStarten(); break;
    case "live-tutor-chat-ende": chatBeenden(); break;
    case "live-tutor-agent": agentStarten(); break;
    case "live-tutor-agent-stopp": agentBeenden(); break;
    case "live-im-browser":
      // Im App-Fenster gibt es kein Mikrofon: StudyHub an derselben Stelle im Standardbrowser öffnen
      api("/api/studyhub/open-browser", { method: "POST", body: { hash: location.hash } })
        .then(() => zeigeToast("Im Browser geöffnet – dort das Mikrofon erlauben"))
        .catch((f) => zeigeToast(f.message));
      break;

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
          <a class="knopf-hell" href="#/modul/${m.id}/sprachtutor">${icon("stimme", 18)} Abfragen lassen</a>
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

        <p class="quelle">${icon("dokument", 14)} Quelle: ${t.quelle} ·
          <button class="link-leise" data-aktion="live-dokument" data-id="${t.dateiId}">Original öffnen</button></p>
      </article>
    </div>`;
};

// ---------- Tab „Sprachtutor“ mit echter API und ElevenLabs ----------

const kannAufnehmen = () => Boolean(navigator.mediaDevices && window.MediaRecorder);
const URTEIL = { correct: "✓ Richtig", partial: "💡 Teilweise richtig", wrong: "✗ Noch nicht" };

LIVE.tabSprachtutor = function (m, d) {
  const t = LIVE.tutor;
  if (t.kurs !== d.kurs) {
    LIVE.tutorStopp();
    Object.assign(t, { kurs: d.kurs, modul: m.id, status: null, frage: null, verlauf: [], phase: "laden", busy: "",
      modus: "abfrage", chatFrage: null, chatKurs: null });
    tutorStatusLaden();
  }
  const s = t.status;
  const mikro = LIVE.voiceReady && kannAufnehmen();
  const agentAn = Boolean(t.agentModus);
  const agentMoeglich = Boolean(s?.agent_ready) && s.questions > 0;
  const auto = s?.auto;

  // Gesprächsmodus (ElevenLabs Agent) hat eigene Zustände; sonst gilt die Frage-Antwort-Phase
  const statusText = agentAn
    ? { connecting: "Verbinde mit dem Tutor …", speaking: "Tutor spricht …", listening: "Tutor hört zu – einfach antworten" }[t.agentModus]
    : {
      laden: "Lade Tutor …",
      vorbereiten: t.busy || (auto?.running
        ? `Fragen werden automatisch vorbereitet: ${auto.done} von ${auto.pending} Dateien`
        : auto?.enabled && auto.error ? `Automatische Vorbereitung angehalten: ${auto.error}`
          : "Noch keine Fragen – erst Material vorbereiten"),
      start: "Bereit, wenn du es bist",
      spricht: "Tutor spricht …",
      deinZug: mikro ? "Mikrofon gedrückt halten und antworten" : "Antwort unten eintippen",
      hoert: "Ich höre zu … loslassen zum Senden",
      denkt: t.busy || "Einen Moment …",
      bewertet: "Weiter zur nächsten Frage?",
    }[t.phase];

  // Knöpfe: Gespräch mit dem Agent (freies Sprechen) oder Abfrage Frage für Frage (Text oder Push-to-Talk)
  let knopf;
  if (agentAn) {
    knopf = `<button class="pille" data-aktion="live-tutor-agent-stopp">Gespräch beenden</button>`;
  } else {
    const agentKnopf = !agentMoeglich ? ""
      : kannAufnehmen()
        ? `<button class="pille" data-aktion="live-tutor-agent">${icon("stimme", 18)} Gespräch mit dem Tutor</button>`
        : `<button class="pille" data-aktion="live-im-browser">${icon("stimme", 18)} Gespräch im Browser öffnen</button>`;
    knopf = {
      vorbereiten: t.busy ? "" : `<button class="${agentKnopf ? "knopf-hell" : "pille"}" data-aktion="live-tutor-vorbereiten" data-modul="${m.id}">${icon("funken", 18)} Material vorbereiten</button>`,
      start: `<button class="pille" data-aktion="live-tutor-chat">${icon("stimme", 18)} Lerngespräch</button>${agentKnopf ? agentKnopf.replace('class="pille"', 'class="knopf-hell"') : ""}<button class="knopf-hell" data-aktion="live-tutor-start">${icon("karten", 18)} Frage für Frage</button>`,
      bewertet: `<button class="pille" data-aktion="live-tutor-weiter">Nächste Frage ${icon("pfeil", 18)}</button>${agentKnopf}`,
    }[t.phase] || "";
    if (t.modus === "gespraech" && ["deinZug", "spricht", "denkt", "hoert"].includes(t.phase)) {
      knopf = `<button class="knopf-hell" data-aktion="live-tutor-chat-ende">Gespräch beenden</button>`;
    }
  }

  const hinweise = [
    s && !s.brain_ready && !s.agent_ready ? "Die KI für den Tutor ist noch nicht eingerichtet (Einstellungen › Sprachtutor)." : "",
    s && s.brain === "gemma" && !agentAn ? "Gemma (lokal) bewertet unzuverlässig – für die Demo besser Claude oder ChatGPT wählen." : "",
    !LIVE.voiceReady ? "Stimme: ElevenLabs-Key in den Einstellungen hinterlegen, bis dahin spricht der Browser." : "",
    LIVE.voiceReady && !s?.agent_ready ? "Für das freie Gespräch eine ElevenLabs Agent-ID in den Einstellungen eintragen." : "",
    LIVE.voiceReady && !kannAufnehmen() ? "Im App-Fenster gibt es kein Mikrofon – sprechen geht im Browser, hier kannst du tippen." : "",
  ].filter(Boolean).map((h) => `<p class="klein tutor-hinweis">${h}</p>`).join("");

  const blasen = t.verlauf.map((b, i) => `
    <li class="blase blase-${b.von} ${i === t.verlauf.length - 1 ? "blase-neu" : ""} ${b.urteil ? `urteil-${b.urteil}` : ""}">
      <span class="mini">${b.von === "tutor" ? (b.urteil ? URTEIL[b.urteil] : "Tutor") : "Du"}</span>
      ${b.html}
    </li>`).join("");

  const orbPhase = agentAn ? { connecting: "denkt", speaking: "spricht", listening: "hoert" }[t.agentModus]
    : t.phase === "bewertet" ? "fertig" : t.phase;

  const eingabe = !agentAn && ["deinZug", "bewertet"].includes(t.phase) ? `
    <form class="tutor-eingabe" data-form="live-tutor">
      <label class="sr-only" for="tutor-text">${t.phase === "bewertet" ? "Rückfrage" : "Deine Antwort"}</label>
      <input id="tutor-text" class="tutor-feld" autocomplete="off" placeholder="${t.modus === "gespraech" ? "Antworten, nachfragen oder Thema wechseln …" : t.phase === "bewertet" ? "Rückfrage, z. B. „Warum ist das so?“" : "Oder Antwort tippen …"}">
      <button class="knopf-hell">${t.modus === "gespraech" ? "Senden" : t.phase === "bewertet" ? "Fragen" : "Antworten"}</button>
    </form>` : "";

  return `
    <div class="tutor">
      <section class="tutor-buehne glas mit-aura">
        <div class="aura" aria-hidden="true"></div>
        <div class="tutor-oben">
          <span class="hinweis-chip">${icon("stimme", 16)} ${m.name}</span>
          <button class="icon-knopf" data-aktion="live-tutor-ton" aria-pressed="${!t.ton}" aria-label="${t.ton ? "Ton ausschalten" : "Ton einschalten"}">${icon(t.ton ? "lautsprecher" : "stumm", 18)}</button>
        </div>
        <button class="orb orb-${orbPhase}" data-mikro="live" ${!agentAn && t.phase === "deinZug" && mikro ? "" : "disabled"}
          aria-label="Gedrückt halten zum Sprechen">
          <span class="orb-welle"></span><span class="orb-welle"></span>
          <span class="orb-kern">${icon("stimme", 36)}</span>
        </button>
        <p class="tutor-status" role="status">${esc(statusText)}</p>
        <div class="tutor-knoepfe">${knopf}</div>
        ${eingabe}
        ${s ? `<div class="runde-stats tutor-stats"><span><i class="ampel-punkt ampel-sitzt"></i><b>${s.correct}</b> richtig</span>
          <span><i class="ampel-punkt ampel-unsicher"></i><b>${s.partial}</b> teilweise</span>
          <span><i class="ampel-punkt ampel-nochmal"></i><b>${s.wrong}</b> falsch</span></div>` : ""}
        ${hinweise}
      </section>

      <section class="tutor-verlauf" aria-label="Gesprächsverlauf">
        <h2 class="mini-titel">Gespräch${s ? ` · ${s.questions} Fragen aus ${s.files} Dateien` : ""}</h2>
        ${blasen ? `<ol class="blasen">${blasen}</ol>` : `<p class="klein">Der Tutor stellt dir Fragen zu deinen Unterlagen, bewertet deine Antwort und nennt die Quelle.</p>`}
      </section>
    </div>`;
};

let autoTimer = null;
async function tutorStatusLaden() {
  const t = LIVE.tutor;
  clearTimeout(autoTimer);
  try {
    t.status = await api(`/api/tutor/status?course=${encodeURIComponent(t.kurs)}`);
    LIVE.voiceReady = Boolean(t.status.voice_ready);
    if (t.phase === "laden" || (t.phase === "vorbereiten" && !t.busy)) t.phase = t.status.questions ? "start" : "vorbereiten";
    // Während die App im Hintergrund Fragen vorbereitet: alle 4 Sekunden nachsehen (nur in diesem Tab)
    if (t.status.auto?.running && aktuelleRoute().tab === "sprachtutor") autoTimer = setTimeout(tutorStatusLaden, 4000);
  } catch (fehler) {
    zeigeToast(`Tutor: ${fehler.message}`);
  }
  neuZeichnen();
}

// ---------- Gesprächsmodus mit dem ElevenLabs Agent ----------
// Der Agent führt das Gespräch frei und bewertet selbst. Er holt Fragen und speichert Ergebnisse
// über zwei Client-Tools, die im Browser laufen und nur mit unserer lokalen API sprechen.
// Gleiche Logik wie ui/tutor.js (siehe docs/tutor/INTEGRATION.md).

const ELEVENLABS_SDK = "/ui/vendor/elevenlabs-client-1.27.0/elevenlabs-client.js";

function elevenLabsLaden() {
  if (window.ElevenLabsClient) return Promise.resolve(window.ElevenLabsClient);
  return new Promise((fertig, fehler) => {
    const script = document.createElement("script");
    script.src = ELEVENLABS_SDK;
    script.onload = () => fertig(window.ElevenLabsClient);
    script.onerror = () => fehler(new Error("ElevenLabs-SDK nicht ladbar"));
    document.head.appendChild(script);
  });
}

const agentWerkzeuge = {
  async get_next_question() {
    const t = LIVE.tutor;
    const params = new URLSearchParams({ solution: "true", course: t.kurs });
    if (t.frage) params.set("exclude", t.frage.id);
    try {
      const frage = await api(`/api/tutor/next?${params}`);
      t.frage = { ...frage, solution: undefined }; // Musterlösung nur an den Agent, nicht in die Oberfläche
      return JSON.stringify({ question: frage.question, solution: frage.solution, source: frage.source });
    } catch (fehler) {
      return `Fehler: ${fehler.message}`;
    }
  },
  async record_result({ answer, verdict, feedback } = {}) {
    // Nur die gerade gestellte Frage darf bewertet werden; die ID kommt aus dem Browser, nicht vom Agent
    const t = LIVE.tutor;
    if (!t.frage) return "Fehler: keine Frage gestellt, erst get_next_question aufrufen";
    try {
      await api("/api/tutor/record", {
        method: "POST",
        body: { question_id: t.frage.id, answer: String(answer || ""), verdict, feedback: String(feedback || "") },
      });
      if (URTEIL[verdict]) t.verlauf.push({ von: "tutor", urteil: verdict, html: `<p>${esc(feedback || "")}</p><span class="mini">${esc(t.frage.source || "")}</span>` });
      api(`/api/tutor/status?course=${encodeURIComponent(t.kurs)}`).then((s) => { t.status = s; neuZeichnen(); }).catch(() => {});
      return "gespeichert";
    } catch (fehler) {
      return `Fehler: ${fehler.message}`;
    }
  },
};

async function agentStarten() {
  const t = LIVE.tutor;
  if (t.agent || t.agentModus) return;
  LIVE.tutorStopp(false);
  t.agentModus = "connecting";
  neuZeichnen();
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => s.getTracks().forEach((spur) => spur.stop()));
    const [sdk, sitzung] = await Promise.all([
      elevenLabsLaden(),
      api("/api/tutor/agent-session", { method: "POST", body: { course: t.kurs } }),
    ]);
    t.agent = await sdk.Conversation.startSession({
      signedUrl: sitzung.signed_url,
      overrides: { agent: { prompt: { prompt: sitzung.prompt }, firstMessage: sitzung.first_message, language: "de" } },
      dynamicVariables: sitzung.dynamic_variables,
      clientTools: agentWerkzeuge,
      onModeChange: ({ mode }) => { t.agentModus = mode; neuZeichnen(); },
      // Mitschrift: was der Tutor sagt und was du sagst
      onMessage: ({ source, message }) => {
        if (!message) return;
        t.verlauf.push({ von: source === "user" ? "du" : "tutor", html: `<p>${esc(message)}</p>` });
        neuZeichnen();
      },
      onDisconnect: () => { t.agent = null; t.agentModus = ""; neuZeichnen(); },
      onError: (meldung) => zeigeToast(`Gespräch: ${meldung}`),
    });
    if (t.agentModus === "connecting") { t.agentModus = "listening"; neuZeichnen(); }
  } catch (fehler) {
    t.agent = null;
    t.agentModus = "";
    zeigeToast(fehler.name === "NotAllowedError" ? "Mikrofon nicht erlaubt" : fehler.message);
    neuZeichnen();
  }
}

async function agentBeenden() {
  const t = LIVE.tutor;
  const agent = t.agent;
  t.agent = null;
  t.agentModus = "";
  neuZeichnen();
  if (agent) await agent.endSession().catch(() => {});
}

async function tutorVorbereiten(modulId) {
  const t = LIVE.tutor;
  const d = MODUL_DETAILS[modulId];
  const dateien = d.dokumente.flatMap((g) => g.dateien).filter((f) => f.lernbar);
  let neu = 0;
  for (const [i, f] of dateien.entries()) {
    t.busy = `Bereite vor: ${i + 1} von ${dateien.length} · ${titelAus(LIVE.pfade[f.id].split("/").pop())}`;
    neuZeichnen();
    try {
      const r = await api("/api/tutor/prepare", { method: "POST", body: { path: f.pfad } });
      neu += r.skipped ? 0 : r.questions || 0;
    } catch (fehler) {
      zeigeToast(`${titelAus(f.pfad.split("/").pop())}: ${fehler.message}`);
    }
  }
  t.busy = "";
  zeigeToast(`${neu} neue Fragen vorbereitet`);
  t.phase = "laden";
  await tutorStatusLaden();
}

async function tutorNaechsteFrage() {
  const t = LIVE.tutor;
  LIVE.tutorStopp(false);
  const lauf = t.lauf;
  const params = new URLSearchParams({ course: t.kurs });
  if (t.frage) params.set("exclude", t.frage.id);
  try {
    t.frage = await api(`/api/tutor/next?${params}`);
  } catch (fehler) {
    zeigeToast(fehler.message);
    return;
  }
  t.verlauf.push({ von: "tutor", html: `<p>${esc(t.frage.question)}</p><span class="mini">${esc(t.frage.source)}</span>` });
  t.phase = "spricht";
  neuZeichnen();
  await LIVE.sprechen(t.frage.question);
  if (lauf !== t.lauf) return;
  t.phase = "deinZug";
  neuZeichnen();
  document.querySelector("#tutor-text")?.focus({ preventScroll: true });
}

async function liveTutorAntworten(text) {
  const t = LIVE.tutor;
  if (t.modus === "gespraech") return chatSenden(text);
  text = text.trim();
  if (!text || !t.frage) return;
  const lauf = t.lauf;
  const rueckfrage = t.phase === "bewertet";
  t.verlauf.push({ von: "du", html: `<p>${esc(text)}</p>` });
  t.phase = "denkt";
  t.busy = rueckfrage ? "Suche im Material …" : "Bewerte deine Antwort …";
  neuZeichnen();
  try {
    if (rueckfrage) {
      const r = await api("/api/tutor/ask", { method: "POST", body: { question_id: t.frage.id, text } });
      t.verlauf.push({ von: "tutor", html: `${markdown(r.answer)}<span class="mini">${(r.sources || []).map(esc).join(" · ")}</span>` });
      t.phase = "spricht";
      neuZeichnen();
      await LIVE.sprechen(r.answer);
    } else {
      const r = await api("/api/tutor/answer", { method: "POST", body: { question_id: t.frage.id, text } });
      t.verlauf.push({
        von: "tutor",
        urteil: r.verdict,
        html: `${markdown(r.feedback)}<details><summary>Musterlösung · ${esc(r.source)}</summary><p>${esc(r.solution)}</p></details>`,
      });
      t.phase = "spricht";
      neuZeichnen();
      api(`/api/tutor/status?course=${encodeURIComponent(t.kurs)}`).then((s) => { t.status = s; neuZeichnen(); }).catch(() => {});
      await LIVE.sprechen(r.feedback);
    }
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
  if (lauf !== t.lauf) return;
  t.busy = "";
  t.phase = "bewertet";
  neuZeichnen();
}

// --- Lerngespräch: der Tutor fragt frei aus dem Material, gibt Hinweise, erklärt und wechselt das Thema ---

function chatStarten() {
  const t = LIVE.tutor;
  LIVE.tutorStopp();
  Object.assign(t, { modus: "gespraech", verlauf: [], chatFrage: null, chatKurs: t.kurs, frage: null });
  chatSenden("", true);
}

function chatBeenden() {
  const t = LIVE.tutor;
  LIVE.tutorStopp();
  Object.assign(t, { modus: "abfrage", chatFrage: null, busy: "", phase: t.status?.questions ? "start" : "vorbereiten" });
  neuZeichnen();
}

async function chatSenden(text, eroeffnung = false) {
  const t = LIVE.tutor;
  text = text.trim();
  if (!text && !eroeffnung) return;
  const lauf = t.lauf;
  // Verlauf für den Server als reiner Text (die Blasen enthalten HTML)
  const history = t.verlauf.map((b) => ({ role: b.von === "tutor" ? "tutor" : "user", text: b.text || "" }));
  if (text) t.verlauf.push({ von: "du", text, html: `<p>${esc(text)}</p>` });
  t.phase = "denkt";
  t.busy = "Tutor denkt nach …";
  neuZeichnen();
  try {
    const r = await api("/api/tutor/chat", {
      method: "POST", body: { text, history, course: t.chatKurs || t.kurs, question_id: t.chatFrage },
    });
    if (lauf !== t.lauf) return;
    t.chatFrage = r.question_id;
    if (r.course && r.course !== t.chatKurs) { t.chatKurs = r.course; zeigeToast(`Thema: ${r.course}`); }
    t.verlauf.push({
      von: "tutor", text: r.say, urteil: r.verdict || undefined,
      html: `${markdown(r.say)}${r.source ? `<span class="mini">${esc(r.source)}</span>` : ""}`,
    });
    if (r.verdict) api(`/api/tutor/status?course=${encodeURIComponent(t.kurs)}`).then((s) => { t.status = s; neuZeichnen(); }).catch(() => {});
    t.busy = "";
    t.phase = "spricht";
    neuZeichnen();
    await LIVE.sprechen(r.say);
  } catch (fehler) {
    zeigeToast(fehler.message);
    if (text) t.verlauf.pop();
  }
  if (lauf !== t.lauf) return;
  t.busy = "";
  t.phase = "deinZug";
  neuZeichnen();
  document.querySelector("#tutor-text")?.focus({ preventScroll: true });
}

// Vorlesen über ElevenLabs (/api/tutor/speak). Fällt auf die Browser-Stimme zurück.
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

LIVE.sprechen = async function (text) {
  const t = LIVE.tutor;
  if (!t.ton || !text) return;
  const sauber = String(text).replace(/[*#`_]/g, "");
  if (!LIVE.voiceReady) return sprichBrowser(sauber);
  try {
    const antwort = await fetch("/api/tutor/speak", {
      method: "POST",
      headers: { "x-app-token": LIVE.token, "content-type": "application/json" },
      body: JSON.stringify({ text: sauber }),
    });
    if (!antwort.ok) throw new Error((await antwort.json().catch(() => ({}))).detail || "Vorlesen fehlgeschlagen");
    const audio = new Audio(URL.createObjectURL(await antwort.blob()));
    t.audio = audio;
    await new Promise((fertig) => {
      audio.onended = fertig;
      audio.onerror = fertig;
      audio.onpause = fertig;
      audio.play().catch(fertig);
    });
  } catch (fehler) {
    zeigeToast(fehler.message);
    return sprichBrowser(sauber);
  }
};

LIVE.tutorStopp = function (abbrechen = true) {
  const t = LIVE.tutor;
  if (abbrechen) {
    t.lauf++;
    if (t.agent) agentBeenden(); // Gespräch mit dem Agent beim Verlassen des Tabs beenden
  }
  if (t.audio) { t.audio.pause(); t.audio = null; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  if (t.recorder?.state === "recording") t.recorder.stop();
};

// Push-to-Talk: Mikrofon-Knopf gedrückt halten
async function aufnahmeStart() {
  const t = LIVE.tutor;
  if (t.recorder || t.phase !== "deinZug") return;
  LIVE.tutorStopp(false);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const teile = [];
    recorder.ondataavailable = (e) => teile.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((spur) => spur.stop());
      t.recorder = null;
      const blob = new Blob(teile, { type: recorder.mimeType || "audio/webm" });
      t.phase = "denkt";
      t.busy = "Verstehe dich …";
      neuZeichnen();
      try {
        const antwort = await fetch("/api/tutor/transcribe", { method: "POST", headers: { "x-app-token": LIVE.token, "content-type": blob.type }, body: blob });
        const daten = await antwort.json();
        if (!antwort.ok) throw new Error(daten.detail || "Spracherkennung fehlgeschlagen");
        if (!daten.text) throw new Error("Nichts verstanden, bitte noch einmal");
        t.phase = "deinZug";
        await liveTutorAntworten(daten.text);
      } catch (fehler) {
        zeigeToast(fehler.message);
        t.phase = "deinZug";
        t.busy = "";
        neuZeichnen();
      }
    };
    recorder.start();
    t.recorder = recorder;
    t.phase = "hoert";
    neuZeichnen();
  } catch (fehler) {
    zeigeToast(`Mikrofon: ${fehler.message}`);
  }
}

function aufnahmeStopp() {
  const r = LIVE.tutor.recorder;
  if (r?.state === "recording") r.stop();
}

document.addEventListener("pointerdown", (e) => {
  if (e.target.closest('[data-mikro="live"]:not([disabled])')) { e.preventDefault(); aufnahmeStart(); }
});
document.addEventListener("pointerup", aufnahmeStopp);

document.addEventListener("submit", (e) => {
  const form = e.target.closest('[data-form="live-tutor"]');
  if (!form) return;
  e.preventDefault();
  liveTutorAntworten(form.querySelector("input").value);
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
// MCP-Server, Tutor-Fragen aus der Hintergrund-Vorbereitung), erscheinen ohne Neustart: beim
// Zurückwechseln ins Fenster und alle 30 Sekunden. Gezeichnet wird nur, wenn sich etwas geändert hat,
// und nie während einer Lernrunde, eines Gesprächs, einer KI-Aktion oder in Formularen.

const NEULADEN_ABSTAND = 4000; // ms, Mindestabstand zwischen zwei Abfragen
let zuletztGeladen = Date.now();

const datenStand = () => JSON.stringify([
  DATEN.semester.flatMap((s) => s.module.map((m) => [m.id, m.fortschritt, m.info, m.zeile, m.neu])),
  Object.entries(MODUL_DETAILS).map(([id, d]) => [id, d.themen, d.karten?.liste?.length, d.tutor?.fragen,
    d.dokumente?.reduce((n, g) => n + g.dateien.length, 0)]),
]);

function ruhig() {
  if (!LIVE.aktiv || LIVE.laedt || document.hidden || $("#sync-knopf")?.disabled) return false;
  const r = aktuelleRoute();
  if (r.seite && r.seite !== "start") return false; // Kurse, Einstellungen, Einrichtung: Eingaben nicht verwerfen
  if (["karteikarten", "sprachtutor"].includes(r.tab)) return false; // Lernrunde bzw. Gespräch nicht stören
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
