// =====================================================
// Chat mit Claude (Panel rechts, auf jeder Seite erreichbar).
// Der Kontext folgt der Ansicht: im Tab „Zusammenfassung“ das geöffnete Lernthema (ein Dokument),
// sonst auf einer Modulseite der ganze Kurs. Der Verlauf liegt pro Kurs bzw. Dokument auf dem Server
// (GET/POST/DELETE /api/chat). Antworten der KI kommen nur über markdown() bzw. esc() ins HTML.
// =====================================================

const CHAT = {
  offen: false,
  kontext: null, // { schluessel, kurs, pfad, label } oder { grund } ohne Kurs
  gezeichnet: null, // Schlüssel des zuletzt gezeichneten Kontexts
  daten: {}, // Schlüssel → { verlauf, anmelden, fehler } (vom Server geladen)
  wartet: {}, // Schlüssel → Frage, solange Claude antwortet
  entwurf: {}, // Schlüssel → noch nicht abgeschickter Text
  loeschen: null, // Schlüssel, für den „Wirklich löschen?“ gerade gezeigt wird
};

// Welcher Kurs bzw. welches Dokument ist gerade zu sehen?
CHAT.kontextErmitteln = function () {
  if (!LIVE.aktiv) return { grund: "Den Chat gibt es in der laufenden App." };
  const r = aktuelleRoute();
  const d = r.modul && MODUL_DETAILS[r.modul];
  if (!d) return { grund: "Öffne einen Kurs oder ein Lernthema, dann kennt Claude den Kontext." };
  if (!d.live) return { grund: "Für das Beispielmodul gibt es keinen Chat." };
  let pfad = null;
  if (r.tab === "zusammenfassung" && d.themen.length) {
    pfad = (d.themen.find((t) => t.nr === zustand.thema[r.modul]) || d.themen[0]).pfad || null;
  }
  return { schluessel: pfad || d.kurs, kurs: d.kurs, pfad, label: pfad ? `${d.kurs} · ${pfad.split("/").pop()}` : d.kurs };
};

// Nach jedem Zeichnen der Seite (route() in app.js): bei neuem Kontext das Panel neu zeichnen
CHAT.aktualisieren = function () {
  const k = CHAT.kontextErmitteln();
  const schluessel = k.schluessel || `-${k.grund}`;
  if (schluessel === CHAT.gezeichnet) return;
  CHAT.entwurfMerken();
  CHAT.kontext = k;
  CHAT.loeschen = null;
  if (CHAT.offen) {
    CHAT.zeichnen();
    CHAT.laden(k);
  }
};

CHAT.entwurfMerken = function () {
  const feld = document.querySelector("#chat textarea");
  if (feld && CHAT.kontext?.schluessel) CHAT.entwurf[CHAT.kontext.schluessel] = feld.value;
};

CHAT.laden = async function (k) {
  if (!k?.schluessel || CHAT.daten[k.schluessel]?.verlauf) return;
  const abfrage = new URLSearchParams(k.pfad ? { kurs: k.kurs, pfad: k.pfad } : { kurs: k.kurs });
  try {
    const antwort = await api(`/api/chat?${abfrage}`);
    CHAT.daten[k.schluessel] = { verlauf: antwort.verlauf, anmelden: antwort.anmelden };
  } catch (fehler) {
    CHAT.daten[k.schluessel] = { fehler: fehler.message };
  }
  if (CHAT.kontext?.schluessel === k.schluessel) CHAT.zeichnen();
};

CHAT.beitrag = function (b) {
  if (b.rolle === "nutzer") return `<div class="chat-beitrag chat-nutzer">${esc(b.text)}</div>`;
  const quellen = (b.quellen || []).map((q) => `<li>${esc(q)}</li>`).join("");
  return `<div class="chat-beitrag chat-claude">
      <div class="zf-md">${markdown(b.text)}</div>
      ${quellen ? `<ul class="chat-quellen" aria-label="Quellen">${quellen}</ul>` : ""}
      ${b.hinweis ? `<p class="klein">${esc(b.hinweis)}</p>` : ""}
    </div>`;
};

CHAT.zeichnen = function () {
  const panel = $("#chat");
  const k = CHAT.kontext || CHAT.kontextErmitteln();
  CHAT.kontext = k;
  CHAT.gezeichnet = k.schluessel || `-${k.grund}`;
  const d = CHAT.daten[k.schluessel] || {};
  const wartet = CHAT.wartet[k.schluessel];
  const verlauf = d.verlauf || [];

  let mitte;
  if (!k.schluessel) mitte = `<p class="chat-leer">${esc(k.grund)}</p>`;
  else if (d.fehler && !verlauf.length) mitte = `<p class="chat-leer">${esc(d.fehler)}</p>`;
  else if (!d.verlauf) mitte = '<p class="chat-leer">Lädt …</p>';
  else {
    mitte = verlauf.map(CHAT.beitrag).join("");
    if (!verlauf.length && !wartet) {
      mitte = `<p class="chat-leer">Frag etwas ${k.pfad ? "zu diesem Dokument" : "zu diesem Kurs"}. Claude antwortet nur aus
        ${k.pfad ? "dem Dokument" : "den Kursunterlagen"} und nennt die Quelle (Datei, Seite).</p>`;
    }
    if (wartet) {
      mitte += `<div class="chat-beitrag chat-nutzer">${esc(wartet)}</div>
        <div class="chat-beitrag chat-claude chat-wartet" role="status">${icon("sync", 14)} Claude liest ${k.pfad ? "das Dokument" : "die Kursunterlagen"} …</div>`;
    }
    if (d.fehler) mitte += `<p class="chat-fehler" role="alert">${esc(d.fehler)}</p>`;
    if (d.anmelden) mitte += `<p class="chat-fehler">${esc(d.anmelden)} <a href="#/einstellungen">Zu den Einstellungen</a></p>`;
  }

  const sperre = !k.schluessel || !d.verlauf || Boolean(wartet);
  panel.innerHTML = `
    <header class="chat-kopf">
      <div class="chat-titel">
        <h2>Chat mit Claude</h2>
        <p class="klein chat-kontext" title="${esc(k.label || "")}">${k.label ? `Kontext: ${esc(k.label)}` : "Kein Kontext"}</p>
      </div>
      ${verlauf.length ? `<button class="chat-text-knopf" data-aktion="chat-loeschen">${CHAT.loeschen === k.schluessel ? "Wirklich löschen?" : "Verlauf löschen"}</button>` : ""}
      <button class="icon-knopf klein-knopf" data-aktion="chat-umschalten" aria-label="Chat schließen">${icon("schliessen", 16)}</button>
    </header>
    <div class="chat-verlauf" id="chat-verlauf" aria-live="polite">${mitte}</div>
    <form class="chat-form" data-form="chat">
      <textarea class="eingabe" name="text" rows="2" maxlength="4000" aria-label="Frage an Claude"
        placeholder="${k.schluessel ? "Frage stellen …" : "Erst einen Kurs öffnen"}" ${sperre ? "disabled" : ""}>${esc(CHAT.entwurf[k.schluessel] || "")}</textarea>
      <button class="pille" ${sperre ? "disabled" : ""} aria-label="Senden">${icon("senden", 16)}</button>
    </form>`;
  const liste = $("#chat-verlauf");
  liste.scrollTop = liste.scrollHeight;
};

CHAT.umschalten = function (offen = !CHAT.offen) {
  CHAT.offen = offen;
  document.body.classList.toggle("chat-offen", offen);
  $("#chat").hidden = !offen;
  $("#chat-knopf").setAttribute("aria-expanded", String(offen));
  if (!offen) return CHAT.entwurfMerken();
  CHAT.kontext = CHAT.kontextErmitteln();
  CHAT.zeichnen();
  CHAT.laden(CHAT.kontext);
  document.querySelector("#chat textarea:not([disabled])")?.focus();
};

CHAT.senden = async function (text) {
  const k = CHAT.kontext;
  const frage = text.trim();
  if (!k?.schluessel || !frage || CHAT.wartet[k.schluessel]) return;
  const d = CHAT.daten[k.schluessel];
  CHAT.wartet[k.schluessel] = frage;
  CHAT.entwurf[k.schluessel] = "";
  d.fehler = null;
  CHAT.zeichnen();
  try {
    const a = await api("/api/chat", { method: "POST", body: { kurs: k.kurs, pfad: k.pfad, text: frage } });
    d.verlauf.push({ rolle: "nutzer", text: frage }, { rolle: "claude", text: a.antwort, quellen: a.quellen, hinweis: a.hinweis });
    d.anmelden = "";
  } catch (fehler) {
    d.fehler = fehler.message;
    CHAT.entwurf[k.schluessel] = frage; // Frage nicht verlieren
  } finally {
    delete CHAT.wartet[k.schluessel];
    // Inzwischen woanders: die Antwort steht im Verlauf, sobald der Kontext wieder gilt
    if (CHAT.offen && CHAT.kontext?.schluessel === k.schluessel) {
      CHAT.zeichnen();
      document.querySelector("#chat textarea")?.focus();
    }
  }
};

CHAT.verlaufLoeschen = async function () {
  const k = CHAT.kontext;
  if (!k?.schluessel) return;
  if (CHAT.loeschen !== k.schluessel) { // erster Klick fragt nach
    CHAT.loeschen = k.schluessel;
    CHAT.entwurfMerken();
    return CHAT.zeichnen();
  }
  CHAT.loeschen = null;
  const abfrage = new URLSearchParams(k.pfad ? { kurs: k.kurs, pfad: k.pfad } : { kurs: k.kurs });
  try {
    await api(`/api/chat?${abfrage}`, { method: "DELETE" });
    CHAT.daten[k.schluessel].verlauf = [];
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
  CHAT.entwurfMerken();
  CHAT.zeichnen();
};

document.addEventListener("click", (e) => {
  const aktion = e.target.closest("[data-aktion]")?.dataset.aktion;
  if (aktion === "chat-umschalten") CHAT.umschalten();
  else if (aktion === "chat-loeschen") CHAT.verlaufLoeschen();
});

document.addEventListener("submit", (e) => {
  const form = e.target.closest('[data-form="chat"]');
  if (!form) return;
  e.preventDefault();
  CHAT.senden(form.elements.text.value);
});

document.addEventListener("keydown", (e) => {
  const feld = e.target.closest?.("#chat textarea");
  if (feld && e.key === "Enter" && !e.shiftKey && !e.isComposing) { // Enter sendet, Umschalt+Enter macht eine neue Zeile
    e.preventDefault();
    CHAT.senden(feld.value);
  } else if (e.key === "Escape" && CHAT.offen && e.target.closest?.("#chat")) {
    CHAT.umschalten(false);
    $("#chat-knopf").focus();
  }
});
