// Study-Tutor: fragt Kursmaterial ab, Antwort per Tastatur oder Push-to-Talk, Feedback auch gesprochen.
// Gesprächsmodus: ein ElevenLabs Agent führt das Gespräch, die Client-Tools rufen unsere lokale API.
// Wird vor app.js geladen; nutzt dessen Helfer (api, $, $$, esc, toast, ICON, state) erst beim Aufruf.
"use strict";

const tutorState = {
  course: "",
  question: null,
  result: null,        // Bewertung der aktuellen Antwort
  followUps: [],
  speakOn: true,
  busy: "",
  recorder: null,
  audio: null,
  status: null,
  mode: "quiz",        // "quiz" (Frage für Frage) | "chat" (freies Gespräch)
  chat: [],            // Verlauf im Gesprächsmodus: { role: "tutor" | "user", text, verdict?, source? }
  chatQuestion: null,  // ID der offenen Frage im Gesprächsmodus
  chatOpened: false,   // Eröffnung schon versucht (verhindert Endlosschleife bei Fehlern)
  agent: null,         // laufendes Gespräch mit dem ElevenLabs Agent
  agentMode: "",       // "connecting" | "speaking" | "listening"
};

const ELEVENLABS_SDK = "/ui/vendor/elevenlabs-client-1.27.0/elevenlabs-client.js";

const canRecord = () => !!(navigator.mediaDevices && window.MediaRecorder);
const inNativeWindow = () => new URLSearchParams(location.search).get("v") === "1";
const VERDICT = {
  correct: { icon: "✓", label: "Richtig", cls: "ok" },
  partial: { icon: "💡", label: "Teilweise richtig", cls: "partial" },
  wrong: { icon: "✗", label: "Noch nicht", cls: "wrong" },
};

async function renderTutor() {
  const view = $("#view-tutor");
  try {
    tutorState.status = await api(`/api/tutor/status${tutorState.course ? `?course=${encodeURIComponent(tutorState.course)}` : ""}`);
  } catch (e) { toast(e.message, true); return; }
  const s = tutorState.status;
  if (s.auto?.running) setTimeout(() => { if (state.view === "tutor" && !tutorState.question) renderTutor(); }, 10000);
  if (!s.questions && !tutorState.course) return renderTutorSetup(view);
  if (!tutorState.question && tutorState.mode === "quiz") await tutorNext(false);
  const brainName = { gemma: "Gemma (lokal)", claude: "Claude", openai: "ChatGPT" }[s.brain];
  view.innerHTML = `<div class="page tutor-page">
    <div class="tutor-head">
      <div><h2>Study-Tutor</h2><p>${s.questions} Fragen aus ${s.files} Dateien · bewertet von ${esc(brainName)}${s.brain_ready ? "" : " (nicht bereit)"}${s.auto?.running ? ` · bereite vor: ${s.auto.done}/${s.auto.pending}` : ""}</p></div>
      <span style="flex:1"></span>
      <select id="tutor-course" class="field"><option value="">Alle Kurse</option>${s.courses.map((c) => `<option ${c === tutorState.course ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
      <button class="btn" id="tutor-more" title="Weitere Dateien vorbereiten">${ICON.sparkles.replace("<svg", '<svg class="icon"')} Material</button>
    </div>
    <div class="tutor-score">
      <span class="chip green">${s.correct} richtig</span><span class="chip">${s.partial} teilweise</span>
      <span class="chip red">${s.wrong} falsch</span>
      <div class="segmented" id="tutor-mode">${[["quiz", "Abfrage"], ["chat", "Gespräch"]].map(([k, l]) => `<button data-v="${k}" class="${tutorState.mode === k ? "active" : ""}">${l}</button>`).join("")}</div>
      <span style="flex:1"></span>
      ${s.voice_ready ? `<label class="tutor-toggle"><input type="checkbox" id="tutor-speak" ${tutorState.speakOn ? "checked" : ""}> Vorlesen</label>` : `<span class="row-sub">Sprache: ElevenLabs-Key in den Einstellungen</span>`}
    </div>
    ${s.brain === "gemma" ? `<div class="banner warn"><div class="banner-main"><b>Kleines lokales Modell</b>Gemma bewertet Antworten unzuverlässig. Für verlässliches Feedback in den Einstellungen Claude oder ChatGPT als Tutor wählen.</div></div>` : ""}
    <div id="tutor-session"></div>
  </div>`;
  $("#tutor-course").addEventListener("change", (e) => { tutorState.course = e.target.value; tutorState.question = null; tutorState.result = null; tutorState.chat = []; tutorState.chatQuestion = null; tutorState.chatOpened = false; renderTutor(); });
  $$("#tutor-mode button").forEach((b) => b.addEventListener("click", () => { stopAudio(); tutorState.mode = b.dataset.v; renderTutor(); }));
  $("#tutor-more").addEventListener("click", () => renderTutorSetup(view));
  $("#tutor-speak")?.addEventListener("change", (e) => { tutorState.speakOn = e.target.checked; if (!e.target.checked) stopAudio(); });
  renderTutorSession();
}

function renderTutorSession() {
  const box = $("#tutor-session");
  if (!box) return;
  if (tutorState.mode === "chat" && !tutorState.agentMode) return renderTutorChat(box);
  const q = tutorState.question;
  if (!q) { box.innerHTML = `<div class="empty"><div><h3>Keine Fragen in diesem Kurs</h3><p>Über „Material“ Dateien vorbereiten.</p></div></div>`; return; }
  const r = tutorState.result;
  const agentOn = !!tutorState.agentMode;
  const voiceIn = canRecord() && tutorState.status.voice_ready && !agentOn;
  const agentBtn = !canRecord() || !tutorState.status.agent_ready ? ""
    : agentOn ? `<button class="btn danger" id="tutor-agent-stop">Gespräch beenden</button>`
      : `<button class="btn" id="tutor-agent" ${tutorState.busy ? "disabled" : ""} title="Freies Gespräch mit dem ElevenLabs Agent">🗣 Gespräch starten</button>`;
  const mic = voiceIn
    ? `<button class="btn primary tutor-mic" id="tutor-mic" ${tutorState.busy ? "disabled" : ""}>🎙 Halten zum Sprechen</button>`
    : inNativeWindow() && tutorState.status.voice_ready
      ? `<button class="btn" id="tutor-browser" title="Das App-Fenster darf nicht aufs Mikrofon zugreifen">🎙 Mit Sprache im Browser öffnen</button>`
      : "";
  const agentLabel = { connecting: "Verbinde …", speaking: "Tutor spricht", listening: "Tutor hört zu" }[tutorState.agentMode];
  box.innerHTML = `
    ${agentOn ? `<div class="tutor-agent ${tutorState.agentMode}"><span class="tutor-orb"></span>${agentLabel}</div>` : ""}
    <div class="tutor-card">
      <div class="tutor-q selectable">${esc(q.question)}</div>
      <div class="tutor-source">${q.last ? `Zuletzt: ${VERDICT[q.last].label} · ` : ""}${esc(q.source)}</div>
    </div>
    ${r ? `
      <div class="tutor-result ${VERDICT[r.verdict].cls}">
        <div class="tutor-verdict"><span>${VERDICT[r.verdict].icon}</span>${VERDICT[r.verdict].label}</div>
        <div class="selectable markdown">${markdown(r.feedback)}</div>
        <details><summary>Musterlösung · ${esc(r.source)}</summary><div class="selectable">${esc(r.solution)}</div></details>
      </div>
      ${tutorState.followUps.map((f) => `<div class="tutor-follow"><b>${esc(f.q)}</b><div class="selectable markdown">${markdown(f.a)}</div><small>${f.sources.map(esc).join(" · ")}</small></div>`).join("")}` : ""}
    ${tutorState.busy ? `<div class="loading"><div class="spinner"></div>${esc(tutorState.busy)}</div>` : ""}
    <form class="ask-bar" id="tutor-form">
      <input class="field" id="tutor-input" autocomplete="off" placeholder="${r ? "Rückfrage stellen, z. B. „Warum ist das so?“" : "Deine Antwort …"}" ${tutorState.busy ? "disabled" : ""}>
      <button class="btn primary" ${tutorState.busy ? "disabled" : ""}>${r ? "Fragen" : "Antworten"}</button>
    </form>
    <div class="tutor-actions">${mic}${agentBtn}<span style="flex:1"></span>
      ${r ? `<button class="btn primary" id="tutor-next">Nächste Frage →</button>` : `<button class="btn" id="tutor-skip">Überspringen</button>`}
    </div>
    ${voiceIn ? `<div class="row-sub tutor-hint">Tipp: Leertaste gedrückt halten zum Sprechen (außerhalb des Textfelds).</div>` : ""}`;
  $("#tutor-form").addEventListener("submit", (e) => { e.preventDefault(); tutorSubmit($("#tutor-input").value); });
  $("#tutor-next")?.addEventListener("click", () => tutorNext());
  $("#tutor-skip")?.addEventListener("click", () => tutorNext());
  $("#tutor-agent")?.addEventListener("click", startAgent);
  $("#tutor-agent-stop")?.addEventListener("click", stopAgent);
  $("#tutor-browser")?.addEventListener("click", () => api("/api/tutor/open-browser", { method: "POST" }).then(() => toast("Tutor im Browser geöffnet")));
  const micBtn = $("#tutor-mic");
  if (micBtn) {
    micBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); startRecording(); });
    ["pointerup", "pointerleave"].forEach((ev) => micBtn.addEventListener(ev, stopRecording));
  }
  if (!tutorState.busy && !agentOn) $("#tutor-input").focus();
}

async function tutorNext(render = true) {
  stopAudio();
  const params = new URLSearchParams();
  if (tutorState.course) params.set("course", tutorState.course);
  if (tutorState.question) params.set("exclude", tutorState.question.id);
  try {
    tutorState.question = await api(`/api/tutor/next?${params}`);
  } catch { tutorState.question = null; }
  tutorState.result = null;
  tutorState.followUps = [];
  if (render) { renderTutor(); }
  if (tutorState.question) say(tutorState.question.question);
}

async function tutorSubmit(text) {
  if (tutorState.mode === "chat") return chatSend(text);
  text = text.trim();
  if (!text || tutorState.busy) return;
  const q = tutorState.question;
  const isFollowUp = !!tutorState.result;
  tutorState.busy = isFollowUp ? "Suche im Material …" : "Bewerte deine Antwort …";
  renderTutorSession();
  try {
    if (isFollowUp) {
      const r = await api("/api/tutor/ask", { method: "POST", body: { question_id: q.id, text } });
      tutorState.followUps.push({ q: text, a: r.answer, sources: r.sources });
      say(r.answer);
    } else {
      tutorState.result = await api("/api/tutor/answer", { method: "POST", body: { question_id: q.id, text } });
      say(tutorState.result.feedback);
      api("/api/tutor/status").then((s) => { tutorState.status = { ...tutorState.status, ...s }; });
    }
  } catch (e) { toast(e.message, true); }
  tutorState.busy = "";
  renderTutorSession();
}

// --- Freies Gespräch ------------------------------------------------------------

function renderTutorChat(box) {
  const voiceIn = canRecord() && tutorState.status.voice_ready;
  const mic = voiceIn
    ? `<button class="btn primary tutor-mic" id="tutor-mic" ${tutorState.busy ? "disabled" : ""}>🎙 Halten zum Sprechen</button>`
    : inNativeWindow() && tutorState.status.voice_ready
      ? `<button class="btn" id="tutor-browser" title="Das App-Fenster darf nicht aufs Mikrofon zugreifen">🎙 Mit Sprache im Browser öffnen</button>`
      : "";
  box.innerHTML = `
    <div class="tutor-chat selectable" id="tutor-chat">
      ${tutorState.chat.map((t) => t.role === "user"
        ? `<div class="chat-bubble user">${esc(t.text)}</div>`
        : `<div class="chat-bubble tutor">${t.verdict ? `<div class="tutor-verdict ${VERDICT[t.verdict].cls}"><span>${VERDICT[t.verdict].icon}</span>${VERDICT[t.verdict].label}</div>` : ""}
             <div class="markdown">${markdown(t.text)}</div>${t.source ? `<small>${esc(t.source)}</small>` : ""}</div>`).join("")}
      ${tutorState.busy ? `<div class="loading"><div class="spinner"></div>${esc(tutorState.busy)}</div>` : ""}
    </div>
    <form class="ask-bar" id="tutor-form">
      <input class="field" id="tutor-input" autocomplete="off" placeholder="Antworten, nachfragen oder z. B. „Lass uns Statistik machen“" ${tutorState.busy ? "disabled" : ""}>
      <button class="btn primary" ${tutorState.busy ? "disabled" : ""}>Senden</button>
    </form>
    <div class="tutor-actions">${mic}<span style="flex:1"></span>
      <button class="btn" id="tutor-chat-new" ${tutorState.busy ? "disabled" : ""}>Neues Gespräch</button></div>
    ${voiceIn ? `<div class="row-sub tutor-hint">Sprich frei: antworten, „Warum ist das so?“, „Erklär mir …“ oder „Lass uns ein anderes Thema machen“.</div>` : ""}`;
  $("#tutor-form").addEventListener("submit", (e) => { e.preventDefault(); chatSend($("#tutor-input").value); });
  $("#tutor-chat-new").addEventListener("click", () => { stopAudio(); tutorState.chat = []; tutorState.chatQuestion = null; tutorState.chatOpened = true; chatSend("", true); });
  $("#tutor-browser")?.addEventListener("click", () => api("/api/tutor/open-browser", { method: "POST" }).then(() => toast("Tutor im Browser geöffnet")));
  const micBtn = $("#tutor-mic");
  if (micBtn) {
    micBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); startRecording(); });
    ["pointerup", "pointerleave"].forEach((ev) => micBtn.addEventListener(ev, stopRecording));
  }
  const list = $("#tutor-chat");
  list.scrollTop = list.scrollHeight;
  if (!tutorState.busy) $("#tutor-input").focus();
  if (!tutorState.chatOpened && !tutorState.busy) { tutorState.chatOpened = true; chatSend("", true); }  // Tutor eröffnet
}

async function chatSend(text, opening = false) {
  text = text.trim();
  if ((!text && !opening) || tutorState.busy) return;
  const history = tutorState.chat.map(({ role, text: t }) => ({ role, text: t }));
  if (text) tutorState.chat.push({ role: "user", text });
  tutorState.busy = "Tutor denkt nach …";
  renderTutorSession();
  try {
    const r = await api("/api/tutor/chat", {
      method: "POST", body: { text, history, course: tutorState.course, question_id: tutorState.chatQuestion },
    });
    tutorState.chat.push({ role: "tutor", text: r.say, verdict: r.verdict, source: r.source });
    tutorState.chatQuestion = r.question_id;
    if (r.course && r.course !== tutorState.course) { tutorState.course = r.course; toast(`Kurs: ${r.course}`); }
    if (r.verdict) api("/api/tutor/status").then((s) => { tutorState.status = { ...tutorState.status, ...s }; });
    say(r.say);
  } catch (e) {
    toast(e.message, true);
    if (text) tutorState.chat.pop();
  }
  tutorState.busy = "";
  if (tutorState.mode === "chat") renderTutorSession();
}

// --- Sprache ------------------------------------------------------------------

function stopAudio() {
  if (tutorState.audio) { tutorState.audio.pause(); tutorState.audio = null; }
}

async function say(text) {
  if (!tutorState.speakOn || !tutorState.status?.voice_ready || !text) return;
  stopAudio();
  text = text.replace(/[*#`_]/g, "");  // Markdown nicht mitsprechen
  try {
    const res = await fetch("/api/tutor/speak", {
      method: "POST", headers: { "x-app-token": TOKEN, "content-type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Vorlesen fehlgeschlagen");
    const audio = new Audio(URL.createObjectURL(await res.blob()));
    tutorState.audio = audio;
    await audio.play();
  } catch (e) { toast(e.message, true); }
}

async function startRecording() {
  if (tutorState.recorder || tutorState.busy) return;
  stopAudio();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      tutorState.busy = "Verstehe dich …";
      renderTutorSession();
      try {
        const res = await fetch("/api/tutor/transcribe", { method: "POST", headers: { "x-app-token": TOKEN, "content-type": blob.type }, body: blob });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Spracherkennung fehlgeschlagen");
        tutorState.busy = "";
        if (data.text) await tutorSubmit(data.text); else { toast("Nichts verstanden, bitte noch einmal", true); renderTutorSession(); }
      } catch (e) { tutorState.busy = ""; toast(e.message, true); renderTutorSession(); }
    };
    recorder.start();
    tutorState.recorder = recorder;
    $("#tutor-mic")?.classList.add("recording");
    if ($("#tutor-mic")) $("#tutor-mic").textContent = "● Aufnahme … loslassen zum Senden";
  } catch (e) { toast(`Mikrofon: ${e.message}`, true); }
}

function stopRecording() {
  const recorder = tutorState.recorder;
  tutorState.recorder = null;
  if (recorder && recorder.state === "recording") recorder.stop();
}

// Leertaste halten = sprechen (nur in der Tutor-Ansicht, nicht im Textfeld)
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.repeat || state.view !== "tutor" || !$("#tutor-mic")) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  e.preventDefault();
  startRecording();
});
document.addEventListener("keyup", (e) => { if (e.code === "Space" && state.view === "tutor") stopRecording(); });

// --- Gesprächsmodus (ElevenLabs Agent) ------------------------------------------

function loadElevenLabsSdk() {
  if (window.ElevenLabsClient) return Promise.resolve(window.ElevenLabsClient);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = ELEVENLABS_SDK;
    script.onload = () => resolve(window.ElevenLabsClient);
    script.onerror = () => reject(new Error("ElevenLabs-SDK nicht ladbar"));
    document.head.appendChild(script);
  });
}

// Client-Tools: der Agent ruft sie im Browser auf, sie sprechen nur mit unserer API auf 127.0.0.1.
// Im ElevenLabs-Dashboard müssen sie mit genau diesen Namen angelegt sein (docs/tutor/SETUP.md).
const agentTools = {
  async get_next_question() {
    const params = new URLSearchParams({ solution: "true" });
    if (tutorState.course) params.set("course", tutorState.course);
    if (tutorState.question) params.set("exclude", tutorState.question.id);
    try {
      const q = await api(`/api/tutor/next?${params}`);
      tutorState.question = { ...q, solution: undefined };
      tutorState.result = null;
      tutorState.followUps = [];
      renderTutorSession();
      return JSON.stringify({ question: q.question, solution: q.solution, source: q.source });
    } catch (e) { return `Fehler: ${e.message}`; }
  },
  async record_result({ answer, verdict, feedback } = {}) {
    // Nur die gerade gestellte Frage darf bewertet werden; die ID kommt aus dem Browser, nicht vom Agent.
    if (!tutorState.question) return "Fehler: keine Frage gestellt, erst get_next_question aufrufen";
    try {
      tutorState.result = await api("/api/tutor/record", {
        method: "POST", body: { question_id: tutorState.question.id, answer: String(answer || ""), verdict, feedback: String(feedback || "") },
      });
      api("/api/tutor/status").then((s) => { tutorState.status = { ...tutorState.status, ...s }; });
      renderTutorSession();
      return "gespeichert";
    } catch (e) { return `Fehler: ${e.message}`; }
  },
};

async function startAgent() {
  if (tutorState.agent || tutorState.agentMode) return;
  stopAudio();
  tutorState.agentMode = "connecting";
  renderTutorSession();
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => s.getTracks().forEach((t) => t.stop()));
    const [sdk, session] = await Promise.all([
      loadElevenLabsSdk(),
      api("/api/tutor/agent-session", { method: "POST", body: { course: tutorState.course } }),
    ]);
    tutorState.agent = await sdk.Conversation.startSession({
      signedUrl: session.signed_url,
      overrides: { agent: { prompt: { prompt: session.prompt }, firstMessage: session.first_message, language: "de" } },
      dynamicVariables: session.dynamic_variables,
      clientTools: agentTools,
      onModeChange: ({ mode }) => { tutorState.agentMode = mode; renderTutorSession(); },
      onDisconnect: () => { tutorState.agent = null; tutorState.agentMode = ""; renderTutorSession(); },
      onError: (message) => toast(`Gespräch: ${message}`, true),
    });
    if (tutorState.agentMode === "connecting") { tutorState.agentMode = "listening"; renderTutorSession(); }
  } catch (e) {
    tutorState.agent = null;
    tutorState.agentMode = "";
    toast(e.message.startsWith("Permission") || e.name === "NotAllowedError" ? "Mikrofon nicht erlaubt" : e.message, true);
    renderTutorSession();
  }
}

async function stopAgent() {
  const agent = tutorState.agent;
  tutorState.agent = null;
  tutorState.agentMode = "";
  renderTutorSession();
  if (agent) await agent.endSession().catch(() => {});
}

// --- Material vorbereiten -----------------------------------------------------

function autoBanner(a) {
  if (!a?.enabled) return "";
  if (a.running) return `<div class="banner"><div class="banner-main"><b>Fragen werden automatisch vorbereitet</b>${a.done} von ${a.pending} Dateien fertig${a.current ? `, gerade: ${esc(a.current)}` : ""}. Du kannst schon loslegen, sobald die ersten Fragen da sind.</div></div>`;
  if (!a.gemma_ready) return `<div class="banner warn"><div class="banner-main"><b>Automatische Fragen brauchen Gemma</b>Ollama installieren und ein Gemma-Modell laden (Einstellungen › KI). Bis dahin hier von Hand vorbereiten.</div></div>`;
  if (a.error) return `<div class="banner warn"><div class="banner-main"><b>Automatische Vorbereitung angehalten</b>${esc(a.error)}. Nächster Versuch in ein paar Minuten.</div></div>`;
  return "";
}

async function renderTutorSetup(view) {
  let files;
  try { files = (await api("/api/files")).files.filter((f) => ["pdf", "txt", "md", "pptx", "docx"].includes(f.ext)); }
  catch (e) { toast(e.message, true); return; }
  const courses = [...new Set(files.map((f) => f.course))];
  const s = tutorState.status || {};
  view.innerHTML = `<div class="page tutor-page">
    <div class="hero"><div><h2>Study-Tutor</h2><p>Der Tutor stellt dir Fragen zu deinen Unterlagen, bewertet deine Antworten und nennt die Quelle, auf Wunsch per Sprache.</p></div></div>
    ${autoBanner(s.auto)}
    ${files.length ? `
    <div class="section-title">Material vorbereiten</div>
    <div class="group">
      <div class="row"><div class="row-main"><div class="row-title">Kurs</div><div class="row-sub">Pro Datei entstehen ${6} Fragen mit Musterlösung. Schon vorbereitete Dateien werden übersprungen.</div></div>
        <select class="field" id="prep-course" style="min-width:200px">${courses.map((c) => `<option>${esc(c)}</option>`).join("")}</select></div>
      <div class="row"><div class="row-main" id="prep-status">${files.length} Dateien verfügbar</div><button class="btn primary" id="prep-go">Fragen erzeugen</button></div>
    </div>
    ${s.questions ? `<button class="btn" id="prep-back">Zurück zum Tutor</button>` : ""}`
    : `<div class="empty"><div>${ICON.doc}<h3>Noch keine Dateien</h3><p>Nach dem ersten Abgleich kann der Tutor Fragen zu deinen Unterlagen stellen.</p></div></div>`}
  </div>`;
  $("#prep-back")?.addEventListener("click", () => renderTutor());
  $("#prep-go")?.addEventListener("click", async (e) => {
    const course = $("#prep-course").value;
    const todo = files.filter((f) => f.course === course);
    e.currentTarget.disabled = true;
    let made = 0, failed = 0;
    for (const [i, f] of todo.entries()) {
      $("#prep-status").innerHTML = `<div class="loading" style="padding:0"><div class="spinner"></div>${i + 1}/${todo.length}: ${esc(f.name)}</div>`;
      try { const r = await api("/api/tutor/prepare", { method: "POST", body: { path: f.path } }); made += r.skipped ? 0 : r.questions; }
      catch (err) { failed++; toast(`${f.name}: ${err.message}`, true); }
    }
    toast(`${made} neue Fragen${failed ? `, ${failed} Dateien übersprungen` : ""}`, failed > 0 && !made);
    tutorState.course = course;
    tutorState.question = null;
    renderTutor();
  });
}
