// =====================================================
// StudyHub – Einrichtung „Mit Uni-Login verbinden“ (#/einrichtung)
//
// Ersetzt den Einrichtungs-Assistenten der klassischen Oberfläche im StudyHub-Design:
//   1. Mit Uni-ID und Passwort bei ILIAS anmelden   (POST /api/account)
//   2. Kurse auswählen                              (PATCH /api/courses, wie auf der Seite „Kurse“)
//   3. KI wählen (optional), mit Hinweis, was dabei den Mac verlässt (PATCH /api/settings)
//   4. Zielordner wählen und ersten Abgleich starten (PATCH /api/settings, POST /api/sync)
// Während des Abgleichs füllt sich die Liste mit den neuen Dateien (GET /api/status).
// Das Passwort geht nur an den lokalen Server; der legt es im Schlüsselbund ab.
// =====================================================

const EINRICHTUNG = {
  schritt: 1,
  busy: "", // "anmelden" | "abgleich"
  abgleich: null, // { start, dateien, neue: [...], fertig }
};

const SCHRITTE = ["Anmelden", "Kurse", "KI", "Erster Abgleich"];

function schrittLeiste() {
  return `
    <ol class="schritte" aria-label="Einrichtung">
      ${SCHRITTE.map((name, i) => {
        const nr = i + 1;
        const stand = nr < EINRICHTUNG.schritt ? "fertig" : nr === EINRICHTUNG.schritt ? "aktiv" : "";
        return `<li class="schritt ${stand}" ${stand === "aktiv" ? 'aria-current="step"' : ""}>
          <span class="schritt-nr">${stand === "fertig" ? icon("haken", 14) : nr}</span>${name}</li>`;
      }).join("")}
    </ol>`;
}

EINSTELLUNGEN.seiteEinrichtung = function () {
  return rahmen("Mit Uni-Login verbinden", "In vier Schritten holt StudyHub deine Kurse aus ILIAS.", () => {
    const s = EINSTELLUNGEN.settings;
    if (s.demo) {
      return `
        <div class="platzhalter glas">
          <div class="platzhalter-icon">${icon("logo", 28)}</div>
          <h2>Im Demo-Modus nicht möglich</h2>
          <p>Die Demo arbeitet mit Beispielkursen und fragt ILIAS nie ab. Starte StudyHub.app ohne „--demo“, um dich mit deiner Uni-ID anzumelden.</p>
        </div>`;
    }
    const inhalt = { 1: schrittAnmelden, 2: schrittKurse, 3: schrittKi, 4: schrittAbgleich }[EINRICHTUNG.schritt](s);
    return `<div class="einrichtung mit-aura"><div class="aura" aria-hidden="true"></div>${schrittLeiste()}${inhalt}</div>`;
  });
};

function schrittAnmelden(s) {
  const angemeldet = s.uni_id && s.has_password;
  const busy = EINRICHTUNG.busy === "anmelden";
  return `
    <section class="einrichtung-karte glas">
      <h2>${icon("logo", 22)} Mit Uni-Login verbinden</h2>
      <p>Melde dich mit deiner Uni-ID an, wie bei ILIAS. StudyHub prüft den Zugang und sucht deine Kurse.</p>
      ${angemeldet ? `
        <div class="hinweis-leiste glas-stark">
          <p>Du bist schon angemeldet als <b>${esc(s.uni_id)}</b>. Das Passwort liegt im Schlüsselbund.</p>
          <button class="pille" data-aktion="live-e-schritt" data-wert="2">Weiter ${icon("pfeil", 18)}</button>
        </div>
        <p class="klein">Mit einer anderen Uni-ID anmelden:</p>` : ""}
      <form class="einrichtung-form" data-form="einst-zugang" data-weiter="2">
        <label>Uni-ID<input class="tutor-feld" name="uni_id" autocomplete="username" value="${esc(s.uni_id || "")}" placeholder="z. B. mmuster" required></label>
        <label>Passwort<input class="tutor-feld" name="passwort" type="password" autocomplete="current-password" placeholder="dein Uni-Passwort" required></label>
        <button class="${angemeldet ? "knopf-hell" : "pille"}" ${busy ? "disabled" : ""}>${busy ? `${icon("sync", 18)} Prüfe bei ILIAS …` : "Anmelden"}</button>
      </form>
      <p class="klein">${icon("schloss", 14)} Dein Passwort bleibt auf diesem Mac (Schlüsselbund) und wird nur an ILIAS geschickt.</p>
    </section>`;
}

function schrittKurse() {
  const { kurse } = EINSTELLUNGEN;
  const liste = kurse.courses.filter((k) => !k.group).map((k) => `
    <li class="einst-zeile">
      <div class="einst-text"><span class="einst-titel">${esc(k.name)}</span><span class="klein">${esc(k.title)}</span></div>
      <div class="einst-rechts">${schalter(`kurs:${esc(k.title)}`, k.sync, `${esc(k.name)} abgleichen`)}</div>
    </li>`).join("");
  const gewaehlt = kurse.courses.filter((k) => k.sync && !k.group).length;
  return `
    <section class="einrichtung-karte glas">
      <h2>${icon("glossar", 22)} Welche Kurse sollen rein?</h2>
      <p>${kurse.courses.length ? `${gewaehlt} von ${kurse.courses.filter((k) => !k.group).length} Kursen ausgewählt. Später jederzeit unter „Kurse“ änderbar.` : "Es wurden noch keine Kurse gefunden."}</p>
      ${liste ? `<ul class="einst-liste einrichtung-liste">${liste}</ul>` : ""}
      <div class="einrichtung-knoepfe">
        <button class="knopf-hell" data-aktion="live-e-schritt" data-wert="1">Zurück</button>
        <button class="pille" data-aktion="live-e-schritt" data-wert="3" ${gewaehlt ? "" : "disabled"}>Weiter ${icon("pfeil", 18)}</button>
      </div>
    </section>`;
}

// Hinweis je Anbieter und das Feld für seinen API-Key (Name in PATCH /api/settings, gespeichert?, Platzhalter)
function kiAnbieter(s, p) {
  return {
    claude: { bereit: p.claude.ready, hinweis: "beste Qualität, liest auch gescannte Folien",
      key: ["api_key", s.has_api_key, "Anthropic-API-Key von console.anthropic.com"] },
    openai: { bereit: p.openai.ready, hinweis: "liest auch gescannte Folien; ein ChatGPT-Plus-Abo reicht nicht",
      key: ["openai_key", s.has_openai_key, "OpenAI-API-Key von platform.openai.com"] },
    gemini: { bereit: p.gemini.ready, hinweis: "liest auch gescannte Folien",
      key: ["google_key", s.has_google_key, "Google-AI-API-Key von aistudio.google.com"] },
    gemma: { bereit: p.gemma.ready, hinweis: p.gemma.local ? "läuft kostenlos auf diesem Mac"
      : "kostenlos: Ollama-App von ollama.com/download installieren, oder Google-AI-API-Key (dann über Google)",
    key: p.gemma.ollama ? null : ["google_key", s.has_google_key, "Google-AI-API-Key von aistudio.google.com"] },
  };
}

function schrittKi(s) {
  const wahl = s.ai_provider;
  const a = kiAnbieter(s, EINSTELLUNGEN.providers)[wahl];
  return `
    <section class="einrichtung-karte glas">
      <h2>${icon("funken", 22)} KI für Zusammenfassungen und Karteikarten</h2>
      <p>Optional: Abgleich, Dokumente und Lernplan funktionieren auch ohne KI. Ändern geht jederzeit unter Einstellungen › KI.</p>
      ${zeile("Anbieter", "", auswahl("ai_provider", wahl, KI_NAMEN))}
      ${zeile(KI_NAMEN[wahl], a.hinweis, bereit(a.bereit))}
      ${a.key && !a.bereit ? geheim(...a.key) : ""}
      <div class="hinweis-leiste glas-stark">
        <p>${icon("schloss", 14)} <b>Was dabei den Mac verlässt:</b> Nur wenn du eine KI-Funktion nutzt, schickt StudyHub
        Text aus deinen Kursunterlagen an den gewählten Anbieter, bei gescannten Folien die PDF selbst. Mit Gemma über
        Ollama bleibt alles auf diesem Mac; automatische Tutor-Fragen entstehen nur so. Dein Uni-Passwort geht nie an
        einen KI-Anbieter. Was der Anbieter mit den Inhalten macht, regeln seine Nutzungsbedingungen; die Kosten rechnet
        er über deinen API-Key ab.</p>
      </div>
      <div class="einrichtung-knoepfe">
        <button class="knopf-hell" data-aktion="live-e-schritt" data-wert="2">Zurück</button>
        <button class="pille" data-aktion="live-e-schritt" data-wert="4">${a.bereit ? "Weiter" : "Ohne KI weiter"} ${icon("pfeil", 18)}</button>
      </div>
    </section>`;
}

function schrittAbgleich(s) {
  const a = EINRICHTUNG.abgleich;
  if (a) {
    const neu = a.neue.map((n) => `<li class="zeile einrichtung-datei"><span class="datei-icon">${icon("dokument", 16)}</span><span class="zeile-titel">${esc(n)}</span></li>`).join("");
    return `
      <section class="einrichtung-karte glas">
        <h2>${icon(a.fertig ? "haken" : "sync", 22)} ${a.fertig ? "Fertig!" : "Hole deine Dateien aus ILIAS …"}</h2>
        <p>${a.fertig ? `${anzahl(a.dateien, "Datei ist", "Dateien sind")} da und nach Kursen sortiert.` : `${anzahl(a.dateien, "Datei", "Dateien")} bisher. Das kann beim ersten Mal ein paar Minuten dauern.`}</p>
        <div class="balken ${a.fertig ? "" : "balken-endlos"}"><span style="width:${a.fertig ? 100 : 35}%"></span></div>
        ${neu ? `<ul class="liste-zeilen einrichtung-dateien">${neu}</ul>` : ""}
        ${a.fertig ? `<div class="einrichtung-knoepfe"><a class="pille" href="#/">Zu StudyHub ${icon("pfeil", 18)}</a></div>` : ""}
      </section>`;
  }
  return `
    <section class="einrichtung-karte glas">
      <h2>${icon("dokument", 22)} Wohin mit den Dateien?</h2>
      <p>StudyHub kopiert die Unterlagen zusätzlich in einen Ordner, z. B. für GoodNotes oder zum Ausdrucken.</p>
      <form class="einrichtung-form" data-form="einrichtung-start">
        <label>Zielordner<input class="tutor-feld" name="wert" value="${esc(s.target_dir || s.folder_suggestions[0]?.path || "")}" required></label>
        <div class="einst-chips">${s.folder_suggestions.map((f) => `
          <button type="button" class="chip chip-klein" data-aktion="live-e-vorschlag" data-pfad="${esc(f.path)}" title="${esc(f.hint)}">${esc(f.label)}</button>`).join("")}</div>
        <div class="einrichtung-knoepfe">
          <button type="button" class="knopf-hell" data-aktion="live-e-schritt" data-wert="3">Zurück</button>
          <button class="pille">${icon("sync", 18)} Ersten Abgleich starten</button>
        </div>
      </form>
    </section>`;
}

// Erster Abgleich: starten und die Liste mit den neuen Dateien füllen, bis er fertig ist
async function ersterAbgleich(zielordner) {
  try {
    if (zielordner !== EINSTELLUNGEN.settings.target_dir) {
      EINSTELLUNGEN.settings = await api("/api/settings", { method: "PATCH", body: { target_dir: zielordner } });
    }
    const vorher = await api("/api/status");
    const r = await api("/api/sync", { method: "POST" });
    if (!r.started && !vorher.running) {
      zeigeToast(r.message || "Abgleich nicht gestartet");
      return;
    }
    EINRICHTUNG.abgleich = { dateien: vorher.files, neue: [], fertig: false };
    neuZeichnen();
    for (let i = 0; i < 600; i++) {
      await pause(2000);
      const s = await api("/api/status");
      const a = EINRICHTUNG.abgleich;
      a.dateien = s.files;
      for (const f of s.recent) if (!a.neue.includes(f.name)) a.neue.unshift(f.name);
      a.neue = a.neue.slice(0, 8);
      if (aktuelleRoute().seite === "einrichtung") neuZeichnen();
      if (!s.running) break;
    }
    EINRICHTUNG.abgleich.fertig = true;
    await LIVE.laden();
    neuZeichnen();
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
}

// Klicks und Formulare der Einrichtung (die Anmeldung selbst steckt in einstellungen.js: "einst-zugang")
const einrichtungKlick = EINSTELLUNGEN.klick;
EINSTELLUNGEN.klick = async function (ds) {
  if (ds.aktion === "live-e-schritt") {
    EINRICHTUNG.schritt = Number(ds.wert);
    neuZeichnen();
    window.scrollTo({ top: 0 });
  } else if (ds.aktion === "live-e-vorschlag") {
    const feld = document.querySelector('[data-form="einrichtung-start"] input[name="wert"]');
    if (feld) feld.value = ds.pfad.replace(/&amp;/g, "&");
  } else {
    await einrichtungKlick(ds);
  }
};

document.addEventListener("submit", (e) => {
  const form = e.target.closest('[data-form="einrichtung-start"]');
  if (!form) return;
  e.preventDefault();
  ersterAbgleich(form.elements.wert.value.trim());
});
