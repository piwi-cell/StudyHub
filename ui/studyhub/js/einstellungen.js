// =====================================================
// StudyHub – Seiten „Kurse“ und „Einstellungen“
//
// Kurse und Einstellungen der App im StudyHub-Design.
// Sie sprechen dieselben Endpunkte an wie ui/app.js:
//   /api/courses (Kurse an/aus, umbenennen), /api/settings, /api/account, /api/ai/providers,
//   /api/telegram/connect|test|disconnect
// Ohne laufende App (kein Token) zeigen sie nur einen Hinweis.
// Zugangsdaten und API-Keys gehen nur an den lokalen Server (der legt sie im Schlüsselbund ab)
// und werden nie angezeigt.
// =====================================================

const EINSTELLUNGEN = {
  settings: null, // Antwort von /api/settings
  providers: null, // Antwort von /api/ai/providers
  kurse: null, // Antwort von /api/courses
  laedt: false,
  busy: "", // gerade laufende Aktion, z. B. "account"
  umbenennen: null, // Kurs-Titel, der gerade umbenannt wird
};

const KI_NAMEN = { claude: "Claude", openai: "ChatGPT", gemini: "Gemini", gemma: "Gemma" };

// „&amp;“ → „&“ usw. (Kurstitel stehen maskiert in HTML-Attributen)
function entschluesseln(text) {
  const el = document.createElement("textarea");
  el.innerHTML = text;
  return el.value;
}

async function einstellungenLaden() {
  if (EINSTELLUNGEN.laedt) return;
  EINSTELLUNGEN.laedt = true;
  try {
    const [settings, providers, kurse, nutzung] = await Promise.all([api("/api/settings"), api("/api/ai/providers"),
      api("/api/courses"), api("/api/ai/usage").catch(() => null)]);
    Object.assign(EINSTELLUNGEN, { settings, providers, kurse, nutzung, fehler: null });
  } catch (fehler) {
    EINSTELLUNGEN.fehler = fehler.message; // nicht endlos neu versuchen
  }
  EINSTELLUNGEN.laedt = false;
  neuZeichnen();
}

// Gemeinsamer Rahmen: ohne App ein Hinweis, beim ersten Öffnen kurz „Lade …“
function rahmen(titel, unterzeile, inhalt) {
  if (!LIVE.token) {
    return `
      <header class="modul-kopf"><div><h1>${titel}</h1></div></header>
      <div class="platzhalter glas">
        <div class="platzhalter-icon">${icon("einstellungen", 28)}</div>
        <h2>Nur in der App</h2>
        <p>Diese Seite braucht die laufende App. Öffne dazu StudyHub.app.</p>
      </div>`;
  }
  if (EINSTELLUNGEN.fehler) {
    return `<header class="modul-kopf"><div><h1>${titel}</h1></div></header>
      <div class="platzhalter glas"><h2>Konnte nicht geladen werden</h2><p>${esc(EINSTELLUNGEN.fehler)}</p>
      <button class="knopf-hell" data-aktion="live-e-neu">Nochmal versuchen</button></div>`;
  }
  if (!EINSTELLUNGEN.settings) {
    einstellungenLaden();
    return `<header class="modul-kopf"><div><h1>${titel}</h1></div></header>
      <div class="schimmer"><span></span><span></span><span></span></div>`;
  }
  return `
    <header class="modul-kopf mit-aura">
      <div class="aura aura-klein" aria-hidden="true"></div>
      <div><p class="eyebrow">${EINSTELLUNGEN.settings.demo ? "Demo-Modus" : "StudyHub"}</p><h1>${titel}</h1>
      <p class="klein">${unterzeile}</p></div>
    </header>
    ${inhalt()}`;
}

const karte = (titel, iconName, inhalt, unter = "") => `
  <section class="einst-karte glas">
    <div class="einst-kopf"><h2>${icon(iconName, 20)} ${titel}</h2>${unter ? `<p class="klein">${unter}</p>` : ""}</div>
    ${inhalt}
  </section>`;

const zeile = (titel, unter, rechts) => `
  <div class="einst-zeile">
    <div class="einst-text"><span class="einst-titel">${titel}</span>${unter ? `<span class="klein">${unter}</span>` : ""}</div>
    <div class="einst-rechts">${rechts}</div>
  </div>`;

const schalter = (name, an, beschriftung, gesperrt = false) => `
  <label class="schalter ${gesperrt ? "gesperrt" : ""}">
    <input type="checkbox" data-einst="${name}" ${an ? "checked" : ""} ${gesperrt ? "disabled" : ""}>
    <span class="schalter-bahn" aria-hidden="true"></span><span class="sr-only">${beschriftung}</span>
  </label>`;

const auswahl = (name, aktuell, optionen) => `
  <div class="segment" role="group">${Object.entries(optionen).map(([wert, text]) => `
    <button class="segment-knopf" data-aktion="live-e-setzen" data-name="${name}" data-wert="${wert}" data-fokus="e-${name}-${wert}"
      aria-pressed="${String(aktuell) === wert}">${text}</button>`).join("")}</div>`;

const geheim = (name, gespeichert, platzhalter) => `
  <form class="einst-form" data-form="einst-geheim" data-name="${name}">
    <input class="tutor-feld" type="password" name="wert" autocomplete="off" placeholder="${gespeichert ? "Gespeichert ✓ – zum Ändern neu eingeben" : platzhalter}">
    <button class="knopf-hell">Speichern</button>
  </form>`;

// Geschätzte Kosten in US-Dollar, z. B. „0,84 $“ oder „unter 0,01 $“
const dollar = (betrag) => betrag > 0 && betrag < 0.01 ? "unter 0,01 $"
  : `${betrag.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`;

const bereit = (ja, text = "bereit") => `<span class="status ${ja ? "status-erledigt" : "status-offen"}">${ja ? text : "nicht eingerichtet"}</span>`;

// ---------- Seite „Kurse“ ----------

EINSTELLUNGEN.seiteKurse = function () {
  return rahmen("Kurse", "Welche ILIAS-Kurse StudyHub abgleicht und wie sie heißen.", () => {
    const { kurse } = EINSTELLUNGEN;
    const liste = kurse.courses.map((k) => {
      const umbenennen = EINSTELLUNGEN.umbenennen === k.title;
      return `
        <li class="einst-zeile">
          <div class="einst-text">
            <span class="einst-titel">${esc(k.name)}${k.group ? ' <span class="mini">Übungsgruppe</span>' : ""}</span>
            <span class="klein">${esc(k.title)}${k.files != null ? ` · ${anzahl(k.files, "Datei", "Dateien")}` : ""}</span>
            ${umbenennen ? `
              <form class="einst-form" data-form="einst-umbenennen" data-titel="${esc(k.title)}">
                <input class="tutor-feld" name="wert" value="${esc(k.name)}" aria-label="Neuer Name">
                <button class="knopf-hell">Umbenennen</button>
              </form>` : ""}
          </div>
          <div class="einst-rechts">
            <button class="icon-knopf klein-knopf" data-aktion="live-e-umbenennen" data-titel="${esc(k.title)}" aria-label="${esc(k.name)} umbenennen">${icon("notiz", 16)}</button>
            ${schalter(`kurs:${esc(k.title)}`, k.sync, `${esc(k.name)} abgleichen`)}
          </div>
        </li>`;
    }).join("");

    return `
      ${karte("Deine Kurse", "glossar", kurse.courses.length
        ? `<ul class="einst-liste">${liste}</ul>`
        : `<p>Noch keine Kurse. Melde dich unter Einstellungen › ILIAS-Zugang an, dann erscheinen hier deine Kurse.</p>`,
      `${kurse.courses.filter((k) => k.sync).length} von ${kurse.courses.length} werden abgeglichen`)}
      ${karte("Neue Kurse", "plus", zeile("Neue Kurse automatisch übernehmen", "z. B. zu Semesterbeginn", schalter("include_new", kurse.include_new, "Neue Kurse automatisch übernehmen")))}`;
  });
};

// ---------- Seite „Einstellungen“ ----------

EINSTELLUNGEN.seiteEinstellungen = function () {
  return rahmen("Einstellungen", "ILIAS-Zugang, Abgleich, KI und Sprachtutor.", () => {
    const s = EINSTELLUNGEN.settings;
    const p = EINSTELLUNGEN.providers;
    const busy = (art) => EINSTELLUNGEN.busy === art;

    const zugang = karte("ILIAS-Zugang", "logo", `
      ${zeile(s.uni_id ? `Angemeldet als <b>${esc(s.uni_id)}</b>` : "Noch nicht angemeldet", s.has_password ? "Passwort im Schlüsselbund gespeichert" : "", bereit(s.has_password, "verbunden"))}
      ${s.demo ? `<p class="klein">Im Demo-Modus wird ILIAS nicht abgefragt.</p>` : `
        <form class="einst-form einst-form-zugang" data-form="einst-zugang">
          <input class="tutor-feld" name="uni_id" autocomplete="username" placeholder="Uni-ID" value="${esc(s.uni_id || "")}" aria-label="Uni-ID">
          <input class="tutor-feld" name="passwort" type="password" autocomplete="current-password" placeholder="Passwort" aria-label="Passwort">
          <button class="pille" ${busy("account") ? "disabled" : ""}>${busy("account") ? "Prüfe bei ILIAS …" : "Anmelden"}</button>
        </form>`}
      ${s.demo ? "" : `<a class="link-leise" href="#/einrichtung">Einrichtung Schritt für Schritt (Anmelden, Kurse, erster Abgleich)</a>`}`,
    "Deine Uni-ID und dein Passwort bleiben auf diesem Mac (Schlüsselbund).");

    const abgleich = karte("Abgleich", "sync", `
      <form class="einst-form" data-form="einst-ordner">
        <input class="tutor-feld" name="wert" value="${esc(s.target_dir || "")}" placeholder="Zielordner, z. B. ~/Documents/ILIAS" aria-label="Zielordner">
        <button class="knopf-hell">Speichern</button>
      </form>
      <div class="einst-chips">${s.folder_suggestions.map((f) => `
        <button class="chip chip-klein" data-aktion="live-e-ordner" data-pfad="${esc(f.path)}" title="${esc(f.hint)}">${esc(f.label)}</button>`).join("")}</div>
      ${zeile("Wie oft", "", auswahl("interval", s.interval, { 30: "alle 30 Min.", 60: "stündlich" }))}
      ${zeile("Automatisch im Hintergrund", s.demo ? "im Demo-Modus nicht verfügbar" : "auch wenn die App zu ist", schalter("schedule_active", s.schedule_active, "Automatisch abgleichen", s.demo))}`,
    "Wohin die Dateien aus ILIAS kopiert werden.");

    const modelle = (anbieter) => Object.fromEntries(Object.entries(p[anbieter].models || {}).map(([id, name]) => [id, name.split(" (")[0]]));
    const ki = karte("KI", "funken", `
      ${zeile("Anbieter", "für Zusammenfassungen und Karteikarten", auswahl("ai_provider", s.ai_provider, KI_NAMEN))}
      <div class="einst-unter">
        ${zeile("Claude", p.claude.ready ? "" : "API-Key von console.anthropic.com", bereit(p.claude.ready))}
        ${auswahl("claude_model", s.claude_model, modelle("claude"))}
        ${geheim("api_key", s.has_api_key, "Anthropic-API-Key")}
      </div>
      <div class="einst-unter">
        ${zeile("ChatGPT", p.openai.ready ? "" : "API-Key von platform.openai.com", bereit(p.openai.ready))}
        ${auswahl("openai_model", s.openai_model, modelle("openai"))}
        ${geheim("openai_key", s.has_openai_key, "OpenAI-API-Key")}
      </div>
      <div class="einst-unter">
        ${zeile("Gemini", p.gemini.ready ? "" : "API-Key von aistudio.google.com", bereit(p.gemini.ready))}
        ${auswahl("gemini_model", s.gemini_model, modelle("gemini"))}
        ${geheim("google_key", s.has_google_key, "Google-AI-API-Key")}
      </div>
      <div class="einst-unter">
        ${zeile("Gemma (lokal)", p.gemma.ollama ? `Modell ${esc(p.gemma.model)}` : "Ollama-App von ollama.com/download installieren und starten", bereit(p.gemma.local))}
      </div>
      <div class="einst-unter">
        ${zeile("Gemma (Gemini API)", p.gemma.local ? "wird genutzt, wenn Ollama nicht läuft" : "mit demselben Google-AI-API-Key wie Gemini, im kostenlosen Kontingent", bereit(p.gemma.api))}
        ${auswahl("gemma_api_model", s.gemma_api_model, modelle("gemma"))}
      </div>
      <div class="einst-unter">${claudeDesktopZeile(s.claude_desktop)}</div>
      ${kostenZeile()}`,
    "Kosten entstehen pro Nutzung beim Anbieter. Gemma läuft kostenlos auf dem Mac oder im kostenlosen Kontingent von Google AI Studio.");

    const tutorKarte = karte("Sprachtutor", "stimme", `
      ${zeile("Wer bewertet deine Antworten", "", auswahl("tutor_brain", s.tutor_brain, KI_NAMEN))}
      ${zeile("Stimme (ElevenLabs)", s.has_elevenlabs_key ? "Vorlesen und Spracherkennung aktiv" : "ohne Key spricht die Browser-Stimme", bereit(s.has_elevenlabs_key))}
      ${geheim("elevenlabs_key", s.has_elevenlabs_key, "ElevenLabs-API-Key")}
      <form class="einst-form" data-form="einst-text" data-name="voice_id">
        <input class="tutor-feld" name="wert" value="${esc(s.voice_id || "")}" placeholder="Stimmen-ID" aria-label="Stimmen-ID">
        <button class="knopf-hell">Speichern</button>
      </form>
      ${zeile("Freies Gespräch (ElevenLabs Agent)", s.agent_id ? "Agent-ID gespeichert" : "Agent im ElevenLabs-Dashboard anlegen, ID hier eintragen (docs/tutor/SETUP.md)", bereit(Boolean(s.agent_id && s.has_elevenlabs_key)))}
      <form class="einst-form" data-form="einst-text" data-name="agent_id">
        <input class="tutor-feld" name="wert" value="${esc(s.agent_id || "")}" placeholder="Agent-ID, z. B. agent_…" aria-label="ElevenLabs Agent-ID">
        <button class="knopf-hell">Speichern</button>
      </form>
      ${zeile("Fragen automatisch vorbereiten", "im Hintergrund mit Gemma lokal (kostenlos), nach jedem Abgleich", schalter("tutor_auto", s.tutor_auto !== false, "Fragen automatisch vorbereiten"))}`,
    "Das Mikrofon funktioniert nur im Browser, nicht im App-Fenster.");

    const weitergabe = karte("Weitergabe", "pfeil", `
      ${zeile("Telegram", s.telegram ? "Zusammenfassungen und Karten aufs Handy" : "Bot bei @BotFather anlegen, Token hier einfügen",
        s.telegram ? `<button class="knopf-hell" data-aktion="live-e-telegram-test">Test</button> <button class="knopf-hell" data-aktion="live-e-telegram-aus">Trennen</button>` : bereit(false))}
      ${s.telegram ? "" : `
        <form class="einst-form" data-form="einst-telegram">
          <input class="tutor-feld" name="wert" type="password" autocomplete="off" placeholder="Bot-Token, z. B. 123456789:ABC…" aria-label="Telegram-Bot-Token">
          <button class="knopf-hell" ${busy("telegram") ? "disabled" : ""}>${busy("telegram") ? "Schreib deinem Bot in Telegram …" : "Verbinden"}</button>
        </form>`}
      ${zeile("reMarkable", s.remarkable.usb ? "per USB verbunden" : s.remarkable.app ? "über die reMarkable-App" : "Tablet per USB anschließen oder reMarkable-App installieren", bereit(s.remarkable.usb || s.remarkable.app, "bereit"))}
      ${s.goodnotes_available ? zeile("GoodNotes", "neue PDFs automatisch importieren", schalter("goodnotes", s.goodnotes, "GoodNotes-Import")) : ""}`);

    const info = karte("Über die App", "uebersicht", `
      ${zeile("Version", esc(s.version), "")}
      ${zeile("Programmordner", esc(s.code_dir), "")}
      ${zeile("Datenordner", esc(s.data_dir), "")}`);

    return `<div class="einst-raster">${zugang}${abgleich}${ki}${tutorKarte}${weitergabe}${info}</div>`;
  });
};

// Claude Desktop arbeitet über den MCP-Server mit den Kursunterlagen: mit dem Claude-Abo, ohne API-Key (docs/mcp.md)
function claudeDesktopZeile(c) {
  if (!c.installed) {
    return zeile("Claude Desktop", "mit deinem Claude-Abo statt API-Key: Claude Desktop von claude.com/download installieren", bereit(false));
  }
  if (c.current) return zeile("Claude Desktop", "eingerichtet: Claude liest deine Kursunterlagen über „studyhub“", bereit(true));
  const unter = c.mcp ? "Eintrag gehört zu einem anderen Programmordner, z. B. einer älteren Installation"
    : "mit deinem Claude-Abo statt API-Key arbeiten";
  return zeile("Claude Desktop", unter, `<button class="knopf-hell" data-aktion="live-e-claude-mcp">${c.mcp ? "Aktualisieren" : "Einrichten"}</button>`);
}

// Geschätzte Kosten des Monats aus GET /api/ai/usage (Listenpreise, gespeicherte Ergebnisse)
function kostenZeile() {
  const n = EINSTELLUNGEN.nutzung;
  if (!n) return "";
  const ohne = n.ohne_preis ? `, ${n.ohne_preis} ohne Preis (z. B. über Claude Desktop)` : "";
  return zeile("Kosten diesen Monat", `${n.ergebnisse} Ergebnisse${ohne}. Schätzung nach Listenpreisen; Sprachtutor nicht mitgezählt`,
    `<span class="einst-titel">ca. ${dollar(n.kosten_usd)}</span>`);
}

// ---------- Aktionen ----------

async function speichern(body, meldung = "Gespeichert") {
  try {
    EINSTELLUNGEN.settings = await api("/api/settings", { method: "PATCH", body });
    EINSTELLUNGEN.providers = await api("/api/ai/providers");
    if ("elevenlabs_key" in body) LIVE.voiceReady = EINSTELLUNGEN.settings.has_elevenlabs_key;
    zeigeToast(meldung);
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
  neuZeichnen();
}

async function kurseNeuLaden() {
  EINSTELLUNGEN.kurse = await api("/api/courses");
  await LIVE.laden(); // Register links aktualisieren
  neuZeichnen();
}

EINSTELLUNGEN.klick = async function (ds) {
  switch (ds.aktion) {
    case "live-e-neu":
      EINSTELLUNGEN.fehler = null;
      einstellungenLaden();
      neuZeichnen();
      break;
    case "live-e-setzen": {
      const zahl = ds.name === "interval";
      await speichern({ [ds.name]: zahl ? Number(ds.wert) : ds.wert });
      break;
    }
    case "live-e-ordner":
      await speichern({ target_dir: ds.pfad }, "Zielordner gespeichert");
      break;
    case "live-e-umbenennen":
      EINSTELLUNGEN.umbenennen = EINSTELLUNGEN.umbenennen === ds.titel ? null : ds.titel;
      neuZeichnen();
      document.querySelector('[data-form="einst-umbenennen"] input')?.select();
      break;
    case "live-e-claude-mcp":
      try {
        await api("/api/claude/mcp", { method: "POST" });
        zeigeToast("In Claude Desktop eingetragen · Claude Desktop mit ⌘Q beenden und neu öffnen");
      } catch (fehler) {
        zeigeToast(fehler.message);
      }
      EINSTELLUNGEN.settings = await api("/api/settings");
      neuZeichnen();
      break;
    case "live-e-telegram-test":
      api("/api/telegram/test", { method: "POST" }).then(() => zeigeToast("Testnachricht gesendet")).catch((f) => zeigeToast(f.message));
      break;
    case "live-e-telegram-aus":
      await api("/api/telegram/disconnect", { method: "POST" }).catch((f) => zeigeToast(f.message));
      EINSTELLUNGEN.settings = await api("/api/settings");
      neuZeichnen();
      break;
  }
};

// Schalter (Checkboxen)
document.addEventListener("change", async (e) => {
  const feld = e.target.closest("[data-einst]");
  if (!feld) return;
  const name = feld.dataset.einst;
  try {
    if (name.startsWith("kurs:")) {
      await api("/api/courses", { method: "PATCH", body: { title: entschluesseln(name.slice(5)), sync: feld.checked } });
      await kurseNeuLaden();
    } else if (name === "include_new") {
      await api("/api/courses/include-new", { method: "POST", body: { include_new: feld.checked } });
      EINSTELLUNGEN.kurse.include_new = feld.checked;
    } else {
      await speichern({ [name]: feld.checked });
    }
  } catch (fehler) {
    feld.checked = !feld.checked;
    zeigeToast(fehler.message);
  }
});

// Formulare
document.addEventListener("submit", async (e) => {
  const form = e.target.closest('[data-form^="einst-"]');
  if (!form) return;
  e.preventDefault();
  const wert = form.elements.wert?.value ?? "";
  switch (form.dataset.form) {
    case "einst-geheim":
      if (!wert.trim()) return;
      await speichern({ [form.dataset.name]: wert.trim() }, "Key im Schlüsselbund gespeichert");
      break;
    case "einst-text":
      await speichern({ [form.dataset.name]: wert });
      break;
    case "einst-ordner":
      await speichern({ target_dir: wert }, "Zielordner gespeichert");
      break;
    case "einst-umbenennen":
      try {
        await api("/api/courses", { method: "PATCH", body: { title: entschluesseln(form.dataset.titel), name: wert } });
        EINSTELLUNGEN.umbenennen = null;
        await kurseNeuLaden();
        zeigeToast("Kurs umbenannt");
      } catch (fehler) {
        zeigeToast(fehler.message);
      }
      break;
    case "einst-zugang": {
      EINSTELLUNGEN.busy = "account";
      neuZeichnen();
      try {
        const r = await api("/api/account", { method: "POST", body: { uni_id: form.elements.uni_id.value, password: form.elements.passwort.value } });
        zeigeToast(`Angemeldet · ${r.courses} Kurse gefunden`);
        EINSTELLUNGEN.settings = await api("/api/settings");
        if (form.dataset.weiter) EINRICHTUNG.schritt = Number(form.dataset.weiter); // in der Einrichtung: weiter zu „Kurse“
        await kurseNeuLaden();
      } catch (fehler) {
        zeigeToast(fehler.message);
      }
      EINSTELLUNGEN.busy = "";
      neuZeichnen();
      break;
    }
    case "einst-telegram":
      if (!wert.trim()) return;
      EINSTELLUNGEN.busy = "telegram";
      neuZeichnen();
      try {
        const r = await api("/api/telegram/connect", { method: "POST", body: { token: wert.trim() } });
        zeigeToast(`Verbunden mit @${r.bot}`);
        EINSTELLUNGEN.settings = await api("/api/settings");
      } catch (fehler) {
        zeigeToast(fehler.message);
      }
      EINSTELLUNGEN.busy = "";
      neuZeichnen();
      break;
  }
});
