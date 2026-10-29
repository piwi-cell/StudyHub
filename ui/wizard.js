// Einrichtungs-Assistent beim ersten Start: Willkommen → Zugang → Kurse → Zielordner → KI → Fertig.
// Nutzt die Helfer aus app.js (api, $, $$, esc, toast, show, refreshStatus, state).
"use strict";

const WIZARD_STEPS = ["welcome", "account", "courses", "folder", "ai", "done"];
const wizard = { step: 0, settings: null, providers: null, busy: false };

const WIZARD_ICON = {
  welcome: '<svg viewBox="0 0 24 24"><path d="M12 3 2 8l10 5 8-4v6h2V8L12 3Zm-6 9.2V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-3.8l-6 3-6-3Z"/></svg>',
  account: '<svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 1 5 5v3h1a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h1V7a5 5 0 0 1 5-5Zm0 2a3 3 0 0 0-3 3v3h6V7a3 3 0 0 0-3-3Z"/></svg>',
  courses: '<svg viewBox="0 0 24 24"><path d="M4 4h4v16H4V4Zm6 0h4v16h-4V4Zm6.2.6 3.8-1 3.9 15.5-3.9 1L16.2 4.6Z" transform="scale(.92) translate(1 1)"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M2 6a2 2 0 0 1 2-2h5l2 2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6Z"/></svg>',
  ai: '<svg viewBox="0 0 24 24"><path d="M10 2 12 8l6 2-6 2-2 6-2-6-6-2 6-2 2-6Zm8 11 1 3 3 1-3 1-1 3-1-3-3-1 3-1 1-3Z"/></svg>',
  done: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20Zm4.3 6.3L10.5 14l-2.8-2.8-1.4 1.4 4.2 4.2 7.2-7.1-1.4-1.4Z"/></svg>',
};

function wizardDismissed() {
  try { return localStorage.getItem("wizard-later") === "1"; } catch { return false; }
}

function setWizardDismissed() {
  try { localStorage.setItem("wizard-later", "1"); } catch { /* privater Modus: dann eben beim nächsten Start wieder */ }
}

async function openWizard() {
  wizard.step = 0;
  try {
    [wizard.settings, wizard.providers] = await Promise.all([api("/api/settings"), api("/api/ai/providers")]);
  } catch (e) { toast(e.message, true); return; }
  $("#wizard").hidden = false;
  renderWizard();
}

function closeWizard() {
  $("#wizard").hidden = true;
  show(state.view);
}

function wizardGo(delta) {
  wizard.step = Math.max(0, Math.min(WIZARD_STEPS.length - 1, wizard.step + delta));
  renderWizard();
}

function wizardFrame({ title, text, body = "", next = "Weiter", nextDisabled = false, back = true, skip = "",
  onSkip = () => wizardGo(1) }) {
  const key = WIZARD_STEPS[wizard.step];
  const dots = WIZARD_STEPS.map((_, i) => `<span class="${i === wizard.step ? "active" : i < wizard.step ? "done" : ""}"></span>`).join("");
  $("#wizard-card").innerHTML = `
    <div class="wizard-icon wizard-icon-${key}">${WIZARD_ICON[key]}</div>
    <h2>${title}</h2>
    <p class="wizard-text">${text}</p>
    <div class="wizard-body">${body}</div>
    <div class="wizard-foot">
      <button class="btn" id="wz-back" ${back ? "" : "hidden"}>Zurück</button>
      <div class="wizard-dots">${dots}</div>
      <div class="wizard-actions">
        ${skip ? `<button class="btn" id="wz-skip">${skip}</button>` : ""}
        <button class="btn primary" id="wz-next" ${nextDisabled ? "disabled" : ""}>${next}</button>
      </div>
    </div>`;
  $("#wz-back").addEventListener("click", () => wizardGo(-1));
  $("#wz-skip")?.addEventListener("click", onSkip);
}

async function renderWizard() {
  const s = wizard.settings;
  const step = WIZARD_STEPS[wizard.step];

  if (step === "welcome") {
    wizardFrame({
      title: "Willkommen bei StudyHub",
      text: "Deine ILIAS-Kurse landen automatisch sortiert auf dem Mac. Aus jeder Vorlesung macht die App auf Wunsch Zusammenfassungen, Lernkarten und Antworten auf deine Fragen.",
      body: `<ul class="wizard-list">
        <li>${ICON.folder}<span><b>Automatisch geladen</b> alle 30 Minuten, auch nach dem Neustart</span></li>
        <li>${ICON.sparkles}<span><b>KI-Lernhilfen</b> mit Claude, ChatGPT oder lokal mit Gemma</span></li>
        <li>${ICON.send}<span><b>Unterwegs</b> per Telegram und auf dem reMarkable</span></li>
      </ul>`,
      next: "Los geht’s", back: false, skip: "Später",
      onSkip: () => { setWizardDismissed(); closeWizard(); },
    });
    $("#wz-next").addEventListener("click", () => wizardGo(1));
    return;
  }

  if (step === "account") {
    if (s.demo) {
      wizardFrame({ title: "ILIAS-Zugang", text: "Im Demo-Modus wird ILIAS nicht abgefragt. Die Beispielkurse sind schon da.",
        body: `<div class="wizard-note">Mit echten Daten meldest du dich hier mit Uni-ID und Passwort an. Das Passwort landet nur im macOS-Schlüsselbund.</div>` });
      $("#wz-next").addEventListener("click", () => wizardGo(1));
      return;
    }
    wizardFrame({
      title: "Mit ILIAS verbinden",
      text: "Melde dich mit deiner Uni-ID an. Das Passwort landet nur im macOS-Schlüsselbund und geht ausschließlich an idp.uni-mannheim.de.",
      body: `<div class="wizard-form">
        <input class="field" id="wz-uni" placeholder="Uni-ID, z. B. mmuster" value="${esc(s.uni_id)}" autocomplete="username">
        <input class="field" id="wz-pw" type="password" placeholder="${s.has_password ? "Passwort (gespeichert, zum Ändern neu eingeben)" : "Passwort"}" autocomplete="current-password">
        <div class="wizard-status" id="wz-status"></div></div>`,
      next: "Anmelden", skip: s.has_password ? "Überspringen" : "",
    });
    const submit = async () => {
      const status = $("#wz-status");
      if (!$("#wz-uni").value.trim() || !$("#wz-pw").value) { status.innerHTML = `<span class="error">Bitte Uni-ID und Passwort eingeben.</span>`; return; }
      $("#wz-next").disabled = true;
      status.innerHTML = `<div class="spinner"></div> Anmeldung bei ILIAS wird geprüft (ca. 20 Sekunden) …`;
      try {
        const r = await api("/api/account", { method: "POST", body: { uni_id: $("#wz-uni").value, password: $("#wz-pw").value } });
        wizard.settings.uni_id = $("#wz-uni").value.trim();
        wizard.settings.has_password = true;
        toast(`Angemeldet · ${r.courses} Kurse und Gruppen gefunden`);
        wizardGo(1);
      } catch (e) {
        status.innerHTML = `<span class="error">${esc(e.message)}</span>`;
        $("#wz-next").disabled = false;
      }
    };
    $("#wz-next").addEventListener("click", submit);
    $("#wz-pw").addEventListener("keydown", (e) => e.key === "Enter" && submit());
    (s.uni_id ? $("#wz-pw") : $("#wz-uni")).focus();
    return;
  }

  if (step === "courses") {
    wizardFrame({ title: "Deine Kurse", text: "Diese Kurse und Gruppen hat ILIAS gemeldet. Wähle, welche geladen werden. Ordnernamen kannst du später unter „Kurse“ ändern.",
      body: `<div class="loading"><div class="spinner"></div>Lade Kurse …</div>` });
    $("#wz-next").addEventListener("click", () => wizardGo(1));
    let data;
    try { data = await api("/api/courses"); } catch (e) { toast(e.message, true); return; }
    $(".wizard-body").innerHTML = data.courses.length
      ? `<div class="group wizard-scroll">${data.courses.map((c, n) => `
          <div class="row"><div class="row-main"><div class="row-title">${c.group ? "↳ " : ""}${esc(c.name)}</div><div class="row-sub">${esc(c.title)}</div></div>
          <label class="switch"><input type="checkbox" data-wz-course="${n}" ${c.sync ? "checked" : ""}><span></span></label></div>`).join("")}</div>`
      : `<div class="wizard-note">Noch keine Kurse gefunden. Sie erscheinen nach der Anmeldung.</div>`;
    $$("[data-wz-course]").forEach((el) => el.addEventListener("change", async () => {
      try { await api("/api/courses", { method: "PATCH", body: { title: data.courses[+el.dataset.wzCourse].title, sync: el.checked } }); }
      catch (e) { el.checked = !el.checked; toast(e.message, true); }
    }));
    return;
  }

  if (step === "folder") {
    const options = [...s.folder_suggestions];
    if (s.target_dir && !options.some((o) => o.path === s.target_dir)) options.unshift({ label: "Aktueller Ordner", path: s.target_dir, hint: s.target_dir });
    wizardFrame({
      title: "Wohin mit den Dateien?",
      text: "Darin entsteht je Kurs ein Unterordner. Was du dort löschst oder bearbeitest, wird nie überschrieben.",
      body: `<div class="wizard-choices">${options.map((o, i) => `
          <button class="wizard-choice ${o.path === s.target_dir ? "selected" : ""}" data-wz-folder="${i}">
            ${ICON.folder}<span><b>${esc(o.label)}</b><small>${esc(o.hint)}</small></span></button>`).join("")}
          <button class="wizard-choice" id="wz-pick">${ICON.folder}<span><b>Anderen Ordner wählen …</b><small>im Finder auswählen</small></span></button></div>`,
      nextDisabled: !s.target_dir,
    });
    const choose = async (path) => {
      try {
        await api("/api/settings", { method: "PATCH", body: { target_dir: path } });
        wizard.settings.target_dir = path;
        renderWizard();
      } catch (e) { toast(e.message, true); }
    };
    $$("[data-wz-folder]").forEach((el) => el.addEventListener("click", () => choose(options[+el.dataset.wzFolder].path)));
    $("#wz-pick").addEventListener("click", async () => {
      const folder = window.pywebview?.api ? await window.pywebview.api.pick_folder() : prompt("Pfad zum Zielordner", "~/Documents/ILIAS");
      if (folder) choose(folder);
    });
    $("#wz-next").addEventListener("click", () => wizardGo(1));
    return;
  }

  if (step === "ai") {
    const p = wizard.providers;
    const ready = { claude: p.claude.ready, openai: p.openai.ready, gemini: p.gemini.ready, gemma: p.gemma.ready };
    const keys = {  // Anbieter mit API-Key: Platzhalter, Hinweis, Feld in PATCH /api/settings
      claude: ["Anthropic-API-Key (sk-ant-…)", "console.anthropic.com › API Keys", "api_key"],
      openai: ["OpenAI-API-Key (sk-…)", "platform.openai.com › API Keys (ein ChatGPT-Plus-Abo reicht nicht)", "openai_key"],
      gemini: ["Google-AI-API-Key (AIza…)", "aistudio.google.com › API-Keys", "google_key"],
    };
    const pick = s.ai_provider;
    const card = (key, name, text, status) => `
      <button class="wizard-choice ${pick === key ? "selected" : ""}" data-wz-ai="${key}">
        ${ICON.sparkles}<span><b>${name}</b><small>${text}</small></span><em class="${ready[key] ? "ok" : ""}">${status}</em></button>`;
    wizardFrame({
      title: "KI-Lernhilfen",
      text: "Welche KI soll Zusammenfassungen und Lernkarten erstellen? Du kannst das jederzeit pro Datei ändern.",
      body: `<div class="wizard-choices">
          ${card("claude", "Claude", "beste Qualität, liest auch gescannte Folien", ready.claude ? "bereit" : "API-Key nötig")}
          ${card("openai", "ChatGPT", "OpenAI, liest auch gescannte Folien", ready.openai ? "bereit" : "API-Key nötig")}
          ${card("gemini", "Gemini", "Google, liest auch gescannte Folien", ready.gemini ? "bereit" : "API-Key nötig")}
          ${card("gemma", "Gemma (lokal)", "kostenlos und offline, nur Text", ready.gemma ? "bereit" : p.gemma.ollama ? "Modell fehlt" : "Ollama nötig")}
        </div>
        <div class="wizard-form" id="wz-key-row" ${keys[pick] && !ready[pick] ? "" : "hidden"}>
          <input class="field" id="wz-key" type="password" placeholder="${keys[pick]?.[0] || ""}">
          <div class="wizard-status">${keys[pick]?.[1] || ""}</div>
        </div>
        <div class="wizard-status">Nur wenn du eine KI-Funktion nutzt, geht Text aus deinen Kursunterlagen (bei gescannten
          Folien die PDF) an den gewählten Anbieter; mit Gemma über Ollama bleibt alles auf diesem Mac. Dein Uni-Passwort
          geht nie an einen KI-Anbieter. Kosten rechnet der Anbieter über deinen API-Key ab.</div>`,
      next: "Weiter", skip: "Ohne KI",
    });
    $$("[data-wz-ai]").forEach((el) => el.addEventListener("click", async () => {
      try {
        await api("/api/settings", { method: "PATCH", body: { ai_provider: el.dataset.wzAi } });
        wizard.settings.ai_provider = el.dataset.wzAi;
        state.provider = el.dataset.wzAi;
        renderWizard();
      } catch (e) { toast(e.message, true); }
    }));
    $("#wz-next").addEventListener("click", async () => {
      const key = $("#wz-key")?.value.trim();
      if (key) {
        try {
          await api("/api/settings", { method: "PATCH", body: { [keys[pick][2]]: key } });
          wizard.providers = await api("/api/ai/providers");
          state.providers = null;
        } catch (e) { toast(e.message, true); return; }
      }
      wizardGo(1);
    });
    return;
  }

  // Fertig: Zeitplan einschalten und ersten Abgleich starten
  wizardFrame({
    title: "Alles bereit",
    text: s.demo ? "Im Demo-Modus sind Beispieldateien schon geladen. Probier eine Zusammenfassung oder Lernkarten aus."
      : "Der erste Abgleich lädt alle Dateien deiner Kurse, das dauert je nach Umfang einige Minuten.",
    body: s.demo ? "" : `<div class="group"><div class="row"><div class="row-main"><div class="row-title">Automatisch abgleichen</div>
        <div class="row-sub">alle 30 Minuten zwischen 6 und 23 Uhr, auch nach dem Neustart</div></div>
        <label class="switch"><input type="checkbox" id="wz-schedule" checked><span></span></label></div></div>`,
    next: s.demo ? "Zur App" : "Ersten Abgleich starten",
  });
  $("#wz-next").addEventListener("click", async () => {
    if (!s.demo) {
      try {
        if ($("#wz-schedule").checked) await api("/api/settings", { method: "PATCH", body: { schedule_active: true } });
        await api("/api/sync", { method: "POST" });
        toast("Erster Abgleich läuft");
      } catch (e) { toast(e.message, true); }
    }
    // Fertig eingerichtet: weiter in die neue Oberfläche StudyHub
    location.href = `/ui/studyhub/index.html?t=${encodeURIComponent(TOKEN)}`;
  });
}

// Beim Start: Assistent zeigen, wenn noch nicht eingerichtet (oder mit ?wizard=1 für die Demo)
(async () => {
  const forced = new URLSearchParams(location.search).get("wizard") === "1";
  try {
    const status = await api("/api/status");
    if (forced || (!status.configured && !status.demo && !wizardDismissed())) openWizard();
  } catch { /* Server noch nicht erreichbar: dann ohne Assistent */ }
})();
