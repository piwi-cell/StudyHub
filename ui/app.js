// ILIAS-Sync – Oberfläche. Spricht nur mit der lokalen API (server/app.py).
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const state = {
  view: "overview",
  status: null,
  files: [],
  selected: null,
  tab: "preview",
  providers: null,
  provider: null,
  busy: {},
  search: "",
};

const ICON = {
  doc: '<svg viewBox="0 0 24 24"><path d="M6 3h8l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm7 1.5V9h4.5L13 4.5Z"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="M12 2.5 14.2 8l5.8.4-4.5 3.7 1.5 5.7L12 14.6l-5 3.2 1.5-5.7L4 8.4 9.8 8 12 2.5Z"/></svg>',
  books: '<svg viewBox="0 0 24 24"><path d="M4 4h4v16H4V4Zm6 0h4v16h-4V4Zm6.2.6 3.8-1 3.9 15.5-3.9 1L16.2 4.6Z" transform="scale(.92) translate(1 1)"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20Zm-1 5v6l5 3 1-1.7-4-2.3V7h-2Z"/></svg>',
  sparkles: '<svg viewBox="0 0 24 24"><path d="M10 2 12 8l6 2-6 2-2 6-2-6-6-2 6-2 2-6Zm8 11 1 3 3 1-3 1-1 3-1-3-3-1 3-1 1-3Z"/></svg>',
  cards: '<svg viewBox="0 0 24 24"><path d="M3 6h14v13H3V6Zm4-3h14v13h-2V5H7V3Z"/></svg>',
  ask: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 1-4.4 19L2 22l1.1-5.4A10 10 0 0 1 12 2Zm.1 4.5c-2 0-3.6 1.3-3.8 3.2h2c.2-.8.9-1.3 1.8-1.3 1 0 1.8.6 1.8 1.5 0 .7-.4 1.1-1.3 1.6-1.1.6-1.6 1.3-1.6 2.6v.5h2v-.4c0-.7.3-1 1.2-1.5 1.1-.6 1.8-1.5 1.8-2.8 0-2-1.7-3.4-3.9-3.4ZM11 16v2h2v-2h-2Z"/></svg>',
  send: '<svg viewBox="0 0 24 24"><path d="m2 21 21-9L2 3v7l15 2-15 2v7Z"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M2 6a2 2 0 0 1 2-2h5l2 2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6Z"/></svg>',
  tablet: '<svg viewBox="0 0 24 24"><path d="M6 2h12a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Zm0 2v15h12V4H6Zm5 16v1h2v-1h-2Z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 4v16l13-8L7 4Z"/></svg>',
};

// --- API ----------------------------------------------------------------------

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "x-app-token": TOKEN, ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Fehler ${res.status}`);
  return data;
}

function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (error ? " error" : "");
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), error ? 5000 : 2800);
}

// --- Formatierung -------------------------------------------------------------

const fmtSize = (b) => (b > 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB");
function fmtDate(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const days = Math.floor((now - d) / 864e5);
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `Heute, ${time}`;
  if (days < 2 && now.getDate() - d.getDate() === 1) return `Gestern, ${time}`;
  return d.toLocaleDateString("de-DE", { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}
function fileKind(ext) {
  if (ext === "pdf") return "pdf";
  if (["doc", "docx", "txt", "md", "tex"].includes(ext)) return "doc";
  if (["ppt", "pptx", "key"].includes(ext)) return "ppt";
  if (["zip", "rar", "7z"].includes(ext)) return "zip";
  return "other";
}
const fileIcon = (ext) => `<div class="file-icon ${fileKind(ext)}">${esc((ext || "?").slice(0, 4))}</div>`;
function aiChips(ai) {
  const chips = [];
  if (ai.summary) chips.push('<span class="chip">Zusammenfassung</span>');
  if (ai.flashcards) chips.push('<span class="chip purple">Karten</span>');
  if (ai.qa) chips.push(`<span class="chip green">${ai.qa} ${ai.qa === 1 ? "Frage" : "Fragen"}</span>`);
  return chips.length ? `<div class="chips">${chips.join("")}</div>` : "";
}

// Kleiner Markdown-Renderer: Überschriften, Listen, fett, kursiv, Code, Absätze
function markdown(src) {
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of String(src).split("\n")) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { close(); out.push(`<h${Math.min(3, m[1].length + 1)}>${inline(m[2])}</h${Math.min(3, m[1].length + 1)}>`); }
    else if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if (!line.trim()) close();
    else { close(); out.push(`<p>${inline(line)}</p>`); }
  }
  close();
  return out.join("");
}

function metaLine(r) {
  if (!r) return "";
  const parts = [r.provider === "gemma" ? `${r.model} (lokal)` : r.model, r.input_mode];
  if (r.cost_usd > 0) parts.push(r.cost_usd < 0.01 ? "unter 0,01 $" : `ca. ${r.cost_usd.toFixed(2).replace(".", ",")} $`);
  if (r.tokens_in != null) parts.push(`${(r.tokens_in + r.cache_read + r.cache_write).toLocaleString("de-DE")} Tokens rein${r.cache_read ? ` (${r.cache_read.toLocaleString("de-DE")} aus Cache)` : ""}, ${r.tokens_out.toLocaleString("de-DE")} raus`);
  parts.push(r.cached ? "gespeichertes Ergebnis" : `${r.seconds} s`);
  if (r.note) parts.push(r.note);
  return `<div class="ai-meta">${parts.map(esc).join(" · ")}</div>`;
}

// --- Navigation ---------------------------------------------------------------

const TITLES = { overview: "Übersicht", files: "Dateien", learn: "Lernen", tutor: "Tutor", courses: "Kurse", settings: "Einstellungen" };

function show(view) {
  state.view = view;
  $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $("#view-title").textContent = TITLES[view];
  $("#search-wrap").hidden = view !== "files";
  ({ overview: renderOverview, files: loadFiles, learn: renderLearn, tutor: renderTutor, courses: renderCourses, settings: renderSettings })[view]();
}

$$(".nav-item").forEach((a) => a.addEventListener("click", () => show(a.dataset.view)));
$("#search").addEventListener("input", (e) => { state.search = e.target.value.toLowerCase(); renderFileList(); });

// --- Status & Abgleich --------------------------------------------------------

async function refreshStatus() {
  try {
    state.status = await api("/api/status");
  } catch (e) {
    $("#sync-text").textContent = "Keine Verbindung zur App";
    return;
  }
  const s = state.status;
  const dot = $("#sync-state .dot");
  dot.className = "dot " + (s.running ? "busy" : s.crawl_failures ? "warn" : s.configured || s.demo ? "ok" : "");
  $("#sync-text").textContent = s.running ? `Abgleich läuft${s.progress ? ` · ${s.progress.text}` : " …"}` : s.demo ? "Demo-Modus" : s.configured ? `Zuletzt: ${s.last_sync}` : "Noch nicht eingerichtet";
  $("#badge-files").textContent = s.files || "";
  $("#badge-learn").textContent = s.ai_results || "";
  $("#brand-sub").textContent = s.uni_id ? `${s.uni_id} · Uni Mannheim` : "Uni Mannheim";
  const btn = $("#btn-sync");
  btn.disabled = s.running || s.demo;
  btn.querySelector(".icon").classList.toggle("spin", s.running);
  btn.querySelector("span").textContent = s.running ? "Läuft …" : "Abgleichen";
  if (refreshStatus.wasRunning && !s.running) {
    toast("Abgleich abgeschlossen");
    if (state.view === "overview") renderOverview();
    if (state.view === "files") loadFiles();
  }
  refreshStatus.wasRunning = s.running;
}

$("#btn-sync").addEventListener("click", async () => {
  try {
    const r = await api("/api/sync", { method: "POST" });
    toast(r.started ? "Abgleich mit ILIAS gestartet" : r.message, !r.started);
    refreshStatus();
  } catch (e) { toast(e.message, true); }
});

// --- Übersicht ----------------------------------------------------------------

async function renderOverview() {
  const [, tutorStatus] = await Promise.all([refreshStatus(), api("/api/tutor/status").catch(() => null)]);
  const s = state.status;
  if (!s) return;
  const hour = new Date().getHours();
  const greet = hour < 11 ? "Guten Morgen" : hour < 18 ? "Hallo" : "Guten Abend";
  const banner = !s.configured && !s.demo
    ? `<div class="banner"><div class="banner-main"><b>ILIAS-Sync einrichten</b>Uni-ID, Passwort und Zielordner hinterlegen, dann laufen deine Kursdateien automatisch ein.</div><button class="btn primary" onclick="show('settings')">Einrichten</button></div>`
    : s.crawl_failures ? `<div class="banner warn"><div class="banner-main"><b>ILIAS gerade nicht erreichbar</b>${s.crawl_failures} fehlgeschlagene Abrufe in Folge. Details im Protokoll.</div></div>` : "";
  const stat = (icon, color, value, label) => `<div class="stat"><div class="stat-icon" style="background:${color}">${icon}</div><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`;
  $("#view-overview").innerHTML = `
    <div class="page">
      <div class="hero"><div><h2>${greet}${s.uni_id ? "" : ""}</h2>
        <p>${s.files ? `${s.files} Dateien aus ${s.courses_synced} Kursen, ${s.ai_results} KI-Lernhilfen` : "Noch keine Dateien geladen"}</p></div></div>
      ${banner}
      <div class="stats">
        ${stat(ICON.doc, "#ff3b30", s.files, "Dateien")}
        ${stat(ICON.books, "#007aff", `${s.courses_synced}<span style="font-size:14px;color:var(--text-3)"> / ${s.courses_total}</span>`, "Kurse synchronisiert")}
        ${stat(ICON.sparkles, "#af52de", s.ai_results, "KI-Lernhilfen")}
        ${stat(ICON.clock, s.schedule_active ? "#34c759" : "#8e8e93", s.schedule_active ? (s.interval === 30 ? "30 Min." : "1 Std.") : "Aus", "Automatischer Abgleich")}
      </div>
      ${tutorCard(tutorStatus)}
      <div class="section-title">Zuletzt hinzugefügt <a onclick="show('files')">Alle anzeigen</a></div>
      <div class="group">
        ${s.recent.length ? s.recent.map((f) => `
          <div class="row clickable" onclick="openFile('${esc(f.path).replace(/'/g, "\\'")}')">
            ${fileIcon(f.ext)}
            <div class="row-main"><div class="row-title">${esc(f.name)}</div><div class="row-sub">${esc(f.course)}${f.folder ? " › " + esc(f.folder) : ""}</div></div>
            ${aiChips(f.ai)}
            <div class="row-value">${fmtDate(f.mtime)}</div>
          </div>`).join("") : `<div class="row"><div class="row-main row-sub">Nach dem ersten Abgleich erscheinen hier die neuesten Dateien.</div></div>`}
      </div>
      <div class="section-title">Protokoll</div>
      <div class="group"><div class="log selectable">${esc(s.log.join("\n")) || "Noch keine Einträge."}</div></div>
    </div>`;
}

function tutorCard(t) {
  if (!t) return "";
  const a = t.auto || {};
  const sub = t.questions
    ? `${t.questions} Fragen zu deinem Lernstoff bereit${a.running ? ` · bereite weitere Dateien vor (${a.done}/${a.pending})` : ""}`
    : a.running ? `Fragen werden vorbereitet (${a.done}/${a.pending}) …`
      : a.enabled && !a.gemma_ready ? "Für automatische Fragen Gemma einrichten (Einstellungen › KI)"
        : "Noch keine Fragen: nach dem ersten Abgleich entstehen sie automatisch";
  return `<div class="section-title">Study-Tutor</div>
      <div class="group"><div class="row">
        <div class="row-main"><div class="row-title">Lass dich abfragen</div><div class="row-sub">${esc(sub)}</div></div>
        <button class="btn primary" onclick="show('tutor')" ${t.questions ? "" : "disabled"}>Tutor starten</button>
      </div></div>`;
}

// --- Dateien ------------------------------------------------------------------

async function loadFiles() {
  try {
    const [files, providers] = await Promise.all([api("/api/files"), state.providers ? null : api("/api/ai/providers")]);
    state.files = files.files;
    if (providers) { state.providers = providers; state.provider = providers.default_provider; }
  } catch (e) { toast(e.message, true); }
  renderFileList();
  renderDetail();
}

function renderFileList() {
  const list = $("#file-list");
  const q = state.search;
  const files = state.files.filter((f) => !q || (f.name + " " + f.course + " " + f.folder).toLowerCase().includes(q));
  if (!state.files.length) {
    list.innerHTML = `<div class="empty"><div>${ICON.folder}<h3>Keine Dateien</h3><p>Nach dem ersten Abgleich erscheinen hier deine Kursdateien.</p></div></div>`;
    return;
  }
  let html = "", course = null;
  for (const f of files) {
    if (f.course !== course) {
      course = f.course;
      const n = files.filter((x) => x.course === course).length;
      html += `<div class="list-course"><span>${esc(course)}</span><span>${n}</span></div>`;
    }
    html += `<div class="list-item ${state.selected === f.path ? "active" : ""}" data-path="${esc(f.path)}">
      ${fileIcon(f.ext)}
      <div class="row-main"><div class="row-title">${esc(f.name)}</div>
      <div class="row-sub">${f.folder ? esc(f.folder) + " · " : ""}${fmtSize(f.size)}</div></div>
      ${f.ai.summary || f.ai.flashcards ? `<span class="chip purple">KI</span>` : ""}
    </div>`;
  }
  list.innerHTML = html || `<div class="empty"><p>Keine Treffer für „${esc(q)}“</p></div>`;
  $$(".list-item", list).forEach((el) => el.addEventListener("click", () => selectFile(el.dataset.path)));
}

function openFile(path) {
  state.selected = path;
  state.tab = "preview";
  show("files");
}

function selectFile(path) {
  state.selected = path;
  if (!["preview", "summary", "flashcards", "qa"].includes(state.tab)) state.tab = "preview";
  renderFileList();
  renderDetail();
}

function providerSelect() {
  const p = state.providers;
  if (!p) return "";
  const claude = p.claude.ready ? "" : " (kein API-Key)";
  const gemma = p.gemma.ready ? "" : p.gemma.ollama ? " (Modell fehlt)" : " (Ollama aus)";
  const model = (p.claude.models[p.claude_model] || "").split(" (")[0];
  const openai = p.openai.ready ? "" : " (kein API-Key)";
  const gpt = (p.openai.models[p.openai_model] || "").split(" (")[0];
  const gemini = p.gemini.ready ? "" : " (kein API-Key)";
  const gem = (p.gemini.models[p.gemini_model] || "").split(" (")[0];
  return `<label class="provider-pick">mit
    <select id="provider">
      <option value="claude" ${state.provider === "claude" ? "selected" : ""}>${esc(model || "Claude")}${claude}</option>
      <option value="openai" ${state.provider === "openai" ? "selected" : ""}>${esc(gpt || "ChatGPT")}${openai}</option>
      <option value="gemini" ${state.provider === "gemini" ? "selected" : ""}>${esc(gem || "Gemini")}${gemini}</option>
      <option value="gemma" ${state.provider === "gemma" ? "selected" : ""}>Gemma · lokal${gemma}</option>
    </select></label>`;
}

async function renderDetail() {
  const pane = $("#file-detail");
  const f = state.files.find((x) => x.path === state.selected);
  if (!f) {
    pane.innerHTML = `<div class="empty"><div>${ICON.doc}<h3>Keine Datei ausgewählt</h3><p>Wähle links eine Datei, um sie anzusehen, zusammenzufassen oder daraus Lernkarten zu erstellen.</p></div></div>`;
    return;
  }
  const canAI = ["pdf", "txt", "md", "tex", "pptx", "docx"].includes(f.ext);
  const tabs = [["preview", "Vorschau"], ...(canAI ? [["summary", "Zusammenfassung"], ["flashcards", "Lernkarten"], ["qa", "Fragen"]] : [])];
  pane.innerHTML = `
    <div class="detail-head">
      <div class="detail-title">${fileIcon(f.ext)}<div class="row-main"><h2 class="selectable">${esc(f.name)}</h2>
        <div class="row-sub">${esc(f.course)}${f.folder ? " › " + esc(f.folder) : ""} · ${fmtSize(f.size)} · ${fmtDate(f.mtime)}</div></div></div>
      <div class="detail-actions">
        <div class="segmented">${tabs.map(([k, l]) => `<button data-tab="${k}" class="${state.tab === k ? "active" : ""}">${l}</button>`).join("")}</div>
        <span class="spacer"></span>
        ${canAI ? providerSelect() : ""}
        <button class="btn small" id="btn-reveal" title="Im Finder zeigen">${ICON.folder.replace("<svg", '<svg class="icon"')}</button>
        ${f.ext === "pdf" ? `<button class="btn small" id="btn-rm" title="Original ans reMarkable">${ICON.tablet.replace("<svg", '<svg class="icon"')}</button>` : ""}
      </div>
    </div>
    <div class="detail-body" id="detail-body"></div>`;
  $$("[data-tab]", pane).forEach((b) => b.addEventListener("click", () => { state.tab = b.dataset.tab; renderDetail(); }));
  $("#btn-reveal").addEventListener("click", () => api("/api/reveal", { method: "POST", body: { path: f.path } }).catch((e) => toast(e.message, true)));
  $("#btn-rm")?.addEventListener("click", () => share(f.path, "original", "remarkable"));
  $("#provider")?.addEventListener("change", (e) => { state.provider = e.target.value; });
  renderTab(f);
}

async function renderTab(f) {
  const body = $("#detail-body");
  if (state.tab === "preview") {
    if (["pdf", "txt", "png", "jpg", "jpeg", "gif", "md"].includes(f.ext)) {
      body.innerHTML = `<iframe src="/api/file?path=${encodeURIComponent(f.path)}&t=${encodeURIComponent(TOKEN)}"></iframe>`;
    } else {
      body.innerHTML = `<div class="empty"><div>${ICON.doc}<h3>Keine Vorschau</h3><p>Diesen Dateityp kann die App nicht anzeigen.</p><button class="btn" id="btn-open">Mit Standard-App öffnen</button></div></div>`;
      $("#btn-open").addEventListener("click", () => api("/api/open", { method: "POST", body: { path: f.path } }));
    }
    return;
  }
  body.innerHTML = `<div class="loading"><div class="spinner"></div>Lade …</div>`;
  let result;
  try { result = await api(`/api/ai/result?path=${encodeURIComponent(f.path)}`); }
  catch (e) { body.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`; return; }
  if (state.selected !== f.path) return;
  const busyKey = `${f.path}|${state.tab}`;

  if (state.tab === "qa") {
    body.innerHTML = `<div class="ai-pane">
      <form class="ask-bar" id="ask"><input class="field" id="question" placeholder="Frage zu diesem Dokument, z. B. „Was ist der Unterschied zwischen …?“" autocomplete="off"><button class="btn primary" ${state.busy[busyKey] ? "disabled" : ""}>Fragen</button></form>
      <div id="qa-list">${state.busy[busyKey] ? `<div class="loading"><div class="spinner"></div>Denke nach …</div>` : ""}
      ${result.qa.slice().reverse().map((a) => `<div class="qa-item"><div class="qa-q">${esc(a.question)}</div><div class="markdown">${markdown(a.output)}</div>${metaLine(a)}</div>`).join("") || (state.busy[busyKey] ? "" : `<div class="row-sub">Noch keine Fragen gestellt. Die Antworten stützen sich nur auf dieses Dokument.</div>`)}</div></div>`;
    $("#ask").addEventListener("submit", async (e) => {
      e.preventDefault();
      const question = $("#question").value.trim();
      if (!question) return;
      await runAI(f, "qa", question);
    });
    $("#question").focus();
    return;
  }

  const r = result[state.tab];
  const label = state.tab === "summary" ? "Zusammenfassung" : "Lernkarten";
  if (state.busy[busyKey]) {
    body.innerHTML = `<div class="loading"><div class="spinner"></div>${label} wird erstellt … (je nach Länge bis zu einer Minute)</div>`;
    return;
  }
  if (!r) {
    const icon = state.tab === "summary" ? ICON.sparkles : ICON.cards;
    const text = state.tab === "summary" ? "Kernaussagen, Begriffe und Prüfungsrelevantes auf einen Blick." : "12–20 Karteikarten zu den prüfungsrelevanten Inhalten, zum Lernen hier, in Telegram oder auf dem reMarkable.";
    body.innerHTML = `<div class="empty"><div>${icon}<h3>${label} erstellen</h3><p>${text}</p><button class="btn primary" id="btn-run">${label} erstellen</button></div></div>`;
    $("#btn-run").addEventListener("click", () => runAI(f, state.tab));
    return;
  }
  const actions = `<div class="detail-actions" style="margin-bottom:18px">
      ${state.tab === "flashcards" ? `<button class="btn primary small" id="btn-study">${ICON.play.replace("<svg", '<svg class="icon"')} Lernen</button>` : ""}
      <button class="btn small" id="btn-tg">${ICON.send.replace("<svg", '<svg class="icon"')} Telegram</button>
      <button class="btn small" id="btn-rm2">${ICON.tablet.replace("<svg", '<svg class="icon"')} reMarkable</button>
      ${state.tab === "flashcards" ? `<button class="btn small" id="btn-anki">Anki-Export</button>` : ""}
      <span class="spacer"></span>
      <button class="btn small" id="btn-redo">Neu erstellen</button>
    </div>`;
  const content = state.tab === "summary"
    ? `<div class="markdown">${markdown(r.output)}</div>`
    : `<div class="cards-grid">${r.output.cards.map((c) => `<div class="mini-card selectable"><b>${esc(c.front)}</b><span>${esc(c.back)}</span></div>`).join("")}</div>`;
  body.innerHTML = `<div class="ai-pane">${actions}${content}${metaLine(r)}</div>`;
  $("#btn-redo").addEventListener("click", () => runAI(f, state.tab, "", true));
  $("#btn-tg").addEventListener("click", () => share(f.path, state.tab, "telegram"));
  $("#btn-rm2").addEventListener("click", () => share(f.path, state.tab, "remarkable"));
  $("#btn-study")?.addEventListener("click", () => study(f.name, r.output.cards));
  $("#btn-anki")?.addEventListener("click", () => ankiExport(f.name, r.output.cards));
}

async function runAI(f, task, question = "", force = false) {
  const key = `${f.path}|${task}`;
  state.busy[key] = true;
  if (state.selected === f.path) renderTab(f);
  try {
    const r = await api("/api/ai/run", { method: "POST", body: { path: f.path, task, question, force, provider: state.provider } });
    if (!r.cached) toast(`Fertig in ${r.seconds} s`);
    f.ai[task === "qa" ? "qa" : task] = task === "qa" ? (f.ai.qa || 0) + 1 : true;
  } catch (e) {
    toast(e.message, true);
  } finally {
    delete state.busy[key];
    if (state.selected === f.path && state.view === "files") { renderFileList(); renderTab(f); }
    refreshStatus();
  }
}

async function share(path, task, target) {
  toast(target === "telegram" ? "Sende an Telegram …" : "Sende ans reMarkable …");
  try {
    const r = await api("/api/share", { method: "POST", body: { path, task, target } });
    toast(`Gesendet über ${r.via}`);
  } catch (e) { toast(e.message, true); }
}

function ankiExport(name, cards) {
  // Tab-getrennt: In Anki über Datei › Importieren direkt lesbar
  const clean = (s) => s.replace(/[\t\n]+/g, " ");
  const tsv = "#separator:tab\n#html:false\n" + cards.map((c) => `${clean(c.front)}\t${clean(c.back)}`).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([tsv], { type: "text/tab-separated-values" }));
  a.download = name.replace(/\.[^.]+$/, "") + " – Anki.txt";
  a.click();
  toast("Anki-Datei gespeichert (Datei › Importieren in Anki)");
}

// --- Lernmodus ----------------------------------------------------------------

function sheet(html) {
  $("#sheet-body").innerHTML = html;
  $("#sheet").hidden = false;
}
function closeSheet() { $("#sheet").hidden = true; document.onkeydown = null; }
$("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });

function study(name, cards) {
  let deck = cards.map((c, i) => ({ ...c, i })), index = 0, known = 0;
  const render = () => {
    if (index >= deck.length) {
      sheet(`<h3>Geschafft 🎉</h3><p>${known} von ${cards.length} Karten auf Anhieb gewusst.</p>
        <div class="sheet-actions"><button class="btn" onclick="closeSheet()">Schließen</button></div>`);
      document.onkeydown = (e) => e.key === "Escape" && closeSheet();
      return;
    }
    const c = deck[index];
    sheet(`<h3>${esc(name)}</h3><p>Karte ${index + 1} von ${deck.length} · Leertaste dreht um</p>
      <div class="study-progress"><div style="width:${(index / deck.length) * 100}%"></div></div>
      <div class="flip" id="flip"><div class="flip-inner">
        <div class="flip-face front selectable">${esc(c.front)}<div class="flip-hint">Klicken zum Umdrehen</div></div>
        <div class="flip-face back selectable">${esc(c.back)}</div></div></div>
      <div class="sheet-actions"><button class="btn" onclick="closeSheet()">Beenden</button><span style="flex:1"></span>
        <button class="btn" id="again">Nochmal</button><button class="btn primary" id="known">Gewusst</button></div>`);
    $("#flip").addEventListener("click", () => $("#flip").classList.toggle("flipped"));
    $("#again").addEventListener("click", () => { deck.push(c); index++; render(); });
    $("#known").addEventListener("click", () => { if (c.i >= 0 && !deck.slice(0, index).some((d) => d.i === c.i)) known++; index++; render(); });
    document.onkeydown = (e) => {
      if (e.key === " ") { e.preventDefault(); $("#flip").classList.toggle("flipped"); }
      if (e.key === "ArrowRight" || e.key === "Enter") $("#known").click();
      if (e.key === "ArrowLeft") $("#again").click();
      if (e.key === "Escape") closeSheet();
    };
  };
  render();
}

async function renderLearn() {
  const view = $("#view-learn");
  view.innerHTML = `<div class="loading"><div class="spinner"></div>Lade …</div>`;
  let items;
  try { items = (await api("/api/learn")).items; } catch (e) { toast(e.message, true); return; }
  if (!items.length) {
    view.innerHTML = `<div class="empty"><div>${ICON.star}<h3>Noch keine Lernhilfen</h3><p>Öffne eine Datei und lass dir eine Zusammenfassung oder Lernkarten erstellen. Sie erscheinen dann hier.</p><button class="btn primary" onclick="show('files')">Zu den Dateien</button></div></div>`;
    return;
  }
  const allCards = items.flatMap((i) => i.flashcards?.output.cards || []);
  view.innerHTML = `<div class="page" style="max-width:1100px">
    <div class="hero"><div><h2>Lernen</h2><p>${items.length} Dokumente · ${allCards.length} Lernkarten</p></div>
      <span style="flex:1"></span>${allCards.length ? `<button class="btn primary" id="study-all">${ICON.play.replace("<svg", '<svg class="icon"')} Alle Karten mischen</button>` : ""}</div>
    <div class="deck-grid">${items.map((i, n) => `
      <div class="deck" data-n="${n}">
        <div class="deck-course">${esc(i.course)}</div>
        <div class="deck-name">${esc(i.name.replace(/\.[^.]+$/, ""))}</div>
        <div class="row-sub" style="white-space:normal">${i.summary ? esc(String(i.summary.output).replace(/^#+[^\n]*\n/gm, "").replace(/[#*`]/g, "").replace(/\s+/g, " ").slice(0, 110)) + " …" : ""}</div>
        <div class="deck-foot">
          ${i.summary ? '<span class="chip">Zusammenfassung</span>' : ""}
          ${i.flashcards ? `<span class="chip purple">${i.flashcards.output.cards.length} Karten</span>` : ""}
          ${i.qa ? `<span class="chip green">${i.qa} ${i.qa === 1 ? "Frage" : "Fragen"}</span>` : ""}
        </div>
      </div>`).join("")}</div></div>`;
  $("#study-all")?.addEventListener("click", () => study("Alle Kurse", [...allCards].sort(() => Math.random() - 0.5)));
  $$(".deck", view).forEach((el) => el.addEventListener("click", () => {
    const i = items[+el.dataset.n];
    if (i.flashcards) study(i.name, i.flashcards.output.cards);
    else { state.tab = "summary"; openFile(i.path); }
  }));
}

// --- Kurse --------------------------------------------------------------------

async function renderCourses() {
  const view = $("#view-courses");
  let data;
  try { data = await api("/api/courses"); } catch (e) { toast(e.message, true); return; }
  if (!data.courses.length) {
    view.innerHTML = `<div class="empty"><div>${ICON.books}<h3>Noch keine Kurse</h3><p>Nach der Anmeldung bei ILIAS erscheinen hier deine Kurse und Gruppen.</p><button class="btn primary" onclick="show('settings')">Einrichten</button></div></div>`;
    return;
  }
  view.innerHTML = `<div class="page">
    <div class="section-title">Kurse und Gruppen aus „Meine Kurse“</div>
    <div class="group">${data.courses.map((c, n) => `
      <div class="row">
        <div class="row-main"><div class="row-title" data-rename="${n}" title="Doppelklick zum Umbenennen">${c.group ? "&nbsp;&nbsp;↳ " : ""}${esc(c.name)}</div>
        <div class="row-sub">${esc(c.title)}</div></div>
        ${c.files != null ? `<div class="row-value">${c.files} Dateien</div>` : ""}
        <label class="switch"><input type="checkbox" data-toggle="${n}" ${c.sync ? "checked" : ""}><span></span></label>
      </div>`).join("")}</div>
    <div class="group-footer">Doppelklick auf einen Namen benennt den Ordner um (auch schon geladene Dateien). Abgewählte Kurse werden nicht mehr geladen, vorhandene Dateien bleiben.</div>
    <div class="group"><div class="row"><div class="row-main"><div class="row-title">Neue Kurse automatisch übernehmen</div><div class="row-sub">z. B. im nächsten Semester</div></div>
      <label class="switch"><input type="checkbox" id="include-new" ${data.include_new ? "checked" : ""}><span></span></label></div></div>
  </div>`;
  $$("[data-toggle]", view).forEach((el) => el.addEventListener("change", async () => {
    const c = data.courses[+el.dataset.toggle];
    try { await api("/api/courses", { method: "PATCH", body: { title: c.title, sync: el.checked } }); }
    catch (e) { el.checked = !el.checked; toast(e.message, true); }
  }));
  $$("[data-rename]", view).forEach((el) => el.addEventListener("dblclick", () => {
    const c = data.courses[+el.dataset.rename];
    sheet(`<h3>Ordner umbenennen</h3><p>${esc(c.title)}</p>
      <input class="field" id="new-name" value="${esc(c.name)}" style="width:100%">
      <div class="sheet-actions"><button class="btn" onclick="closeSheet()">Abbrechen</button><button class="btn primary" id="save-name">Umbenennen</button></div>`);
    $("#new-name").select();
    const save = async () => {
      try { await api("/api/courses", { method: "PATCH", body: { title: c.title, name: $("#new-name").value } }); closeSheet(); renderCourses(); }
      catch (e) { toast(e.message, true); }
    };
    $("#save-name").addEventListener("click", save);
    $("#new-name").addEventListener("keydown", (e) => e.key === "Enter" && save());
  }));
  $("#include-new").addEventListener("change", (e) => api("/api/courses/include-new", { method: "POST", body: { include_new: e.target.checked } }));
}

// --- Einstellungen ------------------------------------------------------------

async function renderSettings() {
  const view = $("#view-settings");
  let s, p;
  try { [s, p] = await Promise.all([api("/api/settings"), api("/api/ai/providers")]); }
  catch (e) { toast(e.message, true); return; }
  state.providers = p;
  const sw = (id, on, disabled = false) => `<label class="switch"><input type="checkbox" id="${id}" ${on ? "checked" : ""} ${disabled ? "disabled" : ""}><span></span></label>`;
  view.innerHTML = `<div class="page">
    ${s.demo ? `<div class="banner"><div class="banner-main"><b>Demo-Modus</b>Beispieldaten in ${esc(s.data_dir)}. Kein Abruf von ILIAS, kein Zeitplan.</div></div>` : ""}
    <div class="banner"><div class="banner-main"><b>Einrichtungs-Assistent</b>Zugang, Kurse, Zielordner und KI Schritt für Schritt einrichten.</div><button class="btn primary" onclick="openWizard()">Starten</button></div>
    <div class="section-title">ILIAS-Zugang</div>
    <div class="group">
      <div class="row"><div class="row-main">Uni-ID</div><input type="text" id="uni-id" value="${esc(s.uni_id)}" placeholder="mmuster"></div>
      <div class="row"><div class="row-main">Passwort</div><input type="password" id="password" placeholder="${s.has_password ? "•••••••• (im Schlüsselbund)" : "Uni-Passwort"}"></div>
      <div class="row"><div class="row-main row-sub">Das Passwort liegt nur im macOS-Schlüsselbund und geht ausschließlich an idp.uni-mannheim.de.</div><button class="btn" id="save-account">Anmelden &amp; prüfen</button></div>
    </div>

    <div class="section-title">Synchronisierung</div>
    <div class="group">
      <div class="row"><div class="row-main"><div class="row-title">Zielordner</div><div class="row-sub">${esc(s.target_dir || "Noch nicht gewählt")}</div></div><button class="btn" id="pick-folder">Auswählen …</button></div>
      <div class="row"><div class="row-main"><div class="row-title">Automatisch abgleichen</div><div class="row-sub">zwischen 6 und 23 Uhr, auch nach dem Neustart</div></div>${sw("schedule", s.schedule_active, s.demo)}</div>
      <div class="row"><div class="row-main">Häufigkeit</div>
        <div class="segmented" id="interval"><button data-v="30" class="${s.interval === 30 ? "active" : ""}">30 Minuten</button><button data-v="60" class="${s.interval === 60 ? "active" : ""}">Stündlich</button></div></div>
    </div>

    <div class="section-title">KI-Lernhilfen</div>
    <div class="group">
      <div class="row"><div class="row-main"><div class="row-title">Standard-Modell</div><div class="row-sub">Gemma läuft lokal und kostenlos, Claude, ChatGPT und Gemini lesen auch gescannte Folien</div></div>
        <div class="segmented" id="ai-provider"><button data-v="claude" class="${s.ai_provider === "claude" ? "active" : ""}">Claude</button><button data-v="openai" class="${s.ai_provider === "openai" ? "active" : ""}">ChatGPT</button><button data-v="gemini" class="${s.ai_provider === "gemini" ? "active" : ""}">Gemini</button><button data-v="gemma" class="${s.ai_provider === "gemma" ? "active" : ""}">Gemma (lokal)</button></div></div>
      <div class="row"><div class="row-main">Claude-Modell</div>
        <select id="claude-model">${Object.entries(p.claude.models).map(([k, v]) => `<option value="${k}" ${k === s.claude_model ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      <div class="row"><div class="row-main"><div class="row-title">Anthropic-API-Key</div><div class="row-sub">${s.has_api_key ? "hinterlegt ✓" : s.has_profile ? "nicht nötig: angemeldet per „ant auth login“ ✓" : "console.anthropic.com › API Keys"}</div></div>
        <input type="password" id="api-key" placeholder="${s.has_api_key ? "•••••••• ersetzen" : "sk-ant-…"}"><button class="btn" id="save-key">Speichern</button></div>
      <div class="row"><div class="row-main">ChatGPT-Modell</div>
        <select id="openai-model">${Object.entries(p.openai.models).map(([k, v]) => `<option value="${k}" ${k === s.openai_model ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      <div class="row"><div class="row-main"><div class="row-title">OpenAI-API-Key</div><div class="row-sub">${s.has_openai_key ? "hinterlegt ✓" : "platform.openai.com › API Keys (ChatGPT Plus reicht nicht)"}</div></div>
        <input type="password" id="openai-key" placeholder="${s.has_openai_key ? "•••••••• ersetzen" : "sk-…"}"><button class="btn" id="save-openai-key">Speichern</button></div>
      <div class="row"><div class="row-main">Gemini-Modell</div>
        <select id="gemini-model">${Object.entries(p.gemini.models).map(([k, v]) => `<option value="${k}" ${k === s.gemini_model ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      <div class="row"><div class="row-main"><div class="row-title">Google-AI-API-Key</div><div class="row-sub">${s.has_google_key ? "hinterlegt ✓ (auch für Gemma über die Gemini API)" : "aistudio.google.com › API-Keys"}</div></div>
        <input type="password" id="google-key" placeholder="${s.has_google_key ? "•••••••• ersetzen" : "AIza…"}"><button class="btn" id="save-google-key">Speichern</button></div>
      <div class="row"><div class="row-main"><div class="row-title">Gemma 3 über Ollama</div><div class="row-sub">${p.gemma.ready ? `${esc(p.gemma.model)} bereit ✓` : p.gemma.ollama ? `Modell fehlt: im Terminal „ollama pull ${esc(p.gemma.model)}“` : "Ollama läuft nicht: Ollama-App von ollama.com/download installieren und starten"}</div></div>
        <div class="dot ${p.gemma.ready ? "ok" : "warn"}"></div></div>
    </div>
    <div class="group-footer">Ergebnisse werden pro Dateiinhalt gespeichert und nie doppelt bezahlt. Bei Claude, ChatGPT und Gemini ist das Dokument gecacht: Weitere Fragen zum selben Dokument kosten nur einen Bruchteil.</div>

    <div class="section-title">Study-Tutor</div>
    <div class="group">
      <div class="row"><div class="row-main"><div class="row-title">Gehirn des Tutors</div><div class="row-sub">erstellt Fragen und bewertet Antworten; Gemma ist kostenlos, Claude und ChatGPT bewerten deutlich verlässlicher</div></div>
        <div class="segmented" id="tutor-brain">${[["gemma", "Gemma"], ["claude", "Claude"], ["openai", "ChatGPT"], ["gemini", "Gemini"]].map(([k, l]) => `<button data-v="${k}" class="${s.tutor_brain === k ? "active" : ""}">${l}</button>`).join("")}</div></div>
      <div class="row"><div class="row-main"><div class="row-title">Fragen automatisch vorbereiten</div><div class="row-sub">erzeugt im Hintergrund mit Gemma (kostenlos) Fragen zu allen Kursdateien, auch zu neuen</div></div>
        <label class="switch"><input type="checkbox" id="tutor-auto" ${s.tutor_auto ? "checked" : ""}><span></span></label></div>
      <div class="row"><div class="row-main"><div class="row-title">ElevenLabs-API-Key</div><div class="row-sub">${s.has_elevenlabs_key ? "hinterlegt ✓ (Sprache an)" : "elevenlabs.io › API Keys, für Sprechen und Vorlesen"}</div></div>
        <input type="password" id="eleven-key" placeholder="${s.has_elevenlabs_key ? "•••••••• ersetzen" : "sk_…"}"><button class="btn" id="save-eleven-key">Speichern</button></div>
      <div class="row"><div class="row-main"><div class="row-title">Stimme (Voice-ID)</div><div class="row-sub">aus der ElevenLabs-Stimmenbibliothek; leer = Standardstimme</div></div>
        <input type="text" id="voice-id" value="${esc(s.voice_id)}"><button class="btn" id="save-voice">Speichern</button></div>
      <div class="row"><div class="row-main"><div class="row-title">ElevenLabs Agent-ID</div><div class="row-sub">${s.agent_id ? "hinterlegt ✓ (Gesprächsmodus an)" : "für den Gesprächsmodus; Einrichtung siehe docs/tutor/SETUP.md"}</div></div>
        <input type="text" id="agent-id" value="${esc(s.agent_id || "")}" placeholder="agent_…"><button class="btn" id="save-agent">Speichern</button></div>
    </div>
    <div class="group-footer">Das App-Fenster darf nicht aufs Mikrofon zugreifen. Zum Sprechen öffnet der Tutor sich im Browser; Vorlesen klappt auch im Fenster.</div>

    <div class="section-title">Benachrichtigungen &amp; Geräte</div>
    <div class="group">
      <div class="row"><div class="row-main"><div class="row-title">Telegram</div><div class="row-sub">${s.telegram ? "verbunden: neue Dateien, Zusammenfassungen und Karten kommen aufs Handy" : "eigener Bot über @BotFather"}</div></div>
        ${s.telegram ? `<button class="btn" id="tg-test">Test</button><button class="btn danger" id="tg-off">Trennen</button>` : `<button class="btn" id="tg-on">Verbinden …</button>`}</div>
      <div class="row"><div class="row-main"><div class="row-title">reMarkable</div><div class="row-sub">${s.remarkable.usb ? "per USB verbunden ✓" : s.remarkable.app ? "über die reMarkable-App für macOS" : "USB-Webinterface aktivieren oder reMarkable-App installieren"}</div></div><div class="dot ${s.remarkable.usb || s.remarkable.app ? "ok" : ""}"></div></div>
      <div class="row"><div class="row-main"><div class="row-title">GoodNotes-Import</div><div class="row-sub">${s.goodnotes_available ? "neue PDFs automatisch in GoodNotes öffnen" : "braucht Goodnotes für Mac (ab macOS 15.7)"}</div></div>${sw("goodnotes", s.goodnotes, !s.goodnotes_available)}</div>
      ${s.notion ? `<div class="row"><div class="row-main"><div class="row-title">Notion-To-do-Liste</div><div class="row-sub">eingerichtet</div></div><div class="dot ok"></div></div>` : ""}
    </div>
  </div>`;

  const patch = async (body, msg = "Gespeichert") => {
    try { await api("/api/settings", { method: "PATCH", body }); toast(msg); return true; }
    catch (e) { toast(e.message, true); return false; }
  };
  $("#save-account").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = "Prüfe (ca. 20 s) …";
    try {
      const r = await api("/api/account", { method: "POST", body: { uni_id: $("#uni-id").value, password: $("#password").value } });
      toast(`Angemeldet · ${r.courses} Kurse und Gruppen gefunden`);
      renderSettings(); refreshStatus();
    } catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = "Anmelden & prüfen"; }
  });
  $("#pick-folder").addEventListener("click", async () => {
    let folder = null;
    if (window.pywebview?.api) folder = await window.pywebview.api.pick_folder();
    else folder = prompt("Pfad zum Zielordner", s.target_dir || "~/Documents/ILIAS");
    if (folder && await patch({ target_dir: folder }, "Zielordner gespeichert")) renderSettings();
  });
  $("#schedule").addEventListener("change", async (e) => { if (!await patch({ schedule_active: e.target.checked }, e.target.checked ? "Automatischer Abgleich an" : "Automatischer Abgleich aus")) e.target.checked = !e.target.checked; });
  $$("#interval button").forEach((b) => b.addEventListener("click", async () => { if (await patch({ interval: +b.dataset.v })) renderSettings(); }));
  $$("#ai-provider button").forEach((b) => b.addEventListener("click", async () => { if (await patch({ ai_provider: b.dataset.v })) { state.provider = b.dataset.v; state.providers = null; renderSettings(); } }));
  $("#claude-model").addEventListener("change", (e) => { patch({ claude_model: e.target.value }); state.providers = null; });
  $("#save-key").addEventListener("click", async () => { if (await patch({ api_key: $("#api-key").value }, "API-Key im Schlüsselbund gespeichert")) { state.providers = null; renderSettings(); } });
  $("#openai-model").addEventListener("change", (e) => { patch({ openai_model: e.target.value }); state.providers = null; });
  $("#gemini-model").addEventListener("change", (e) => { patch({ gemini_model: e.target.value }); state.providers = null; });
  $("#save-openai-key").addEventListener("click", async () => { if (await patch({ openai_key: $("#openai-key").value }, "OpenAI-Key im Schlüsselbund gespeichert")) { state.providers = null; renderSettings(); } });
  $("#save-google-key").addEventListener("click", async () => { if (await patch({ google_key: $("#google-key").value }, "Google-AI-Key im Schlüsselbund gespeichert")) { state.providers = null; renderSettings(); } });
  $("#goodnotes").addEventListener("change", (e) => patch({ goodnotes: e.target.checked }));
  $$("#tutor-brain button").forEach((b) => b.addEventListener("click", async () => { if (await patch({ tutor_brain: b.dataset.v }, "Tutor-Gehirn gespeichert")) renderSettings(); }));
  $("#save-eleven-key").addEventListener("click", async () => { if (await patch({ elevenlabs_key: $("#eleven-key").value }, "ElevenLabs-Key im Schlüsselbund gespeichert")) renderSettings(); });
  $("#save-voice").addEventListener("click", () => patch({ voice_id: $("#voice-id").value }, "Stimme gespeichert"));
  $("#tutor-auto").addEventListener("change", (e) => patch({ tutor_auto: e.target.checked }, e.target.checked ? "Tutor bereitet Fragen automatisch vor" : "Automatische Vorbereitung aus"));
  $("#save-agent").addEventListener("click", async () => { if (await patch({ agent_id: $("#agent-id").value }, "Agent-ID gespeichert")) renderSettings(); });
  $("#tg-test")?.addEventListener("click", () => api("/api/telegram/test", { method: "POST" }).then(() => toast("Testnachricht gesendet")).catch((e) => toast(e.message, true)));
  $("#tg-off")?.addEventListener("click", async () => { await api("/api/telegram/disconnect", { method: "POST" }); renderSettings(); });
  $("#tg-on")?.addEventListener("click", telegramSetup);
}

function telegramSetup() {
  sheet(`<h3>Telegram verbinden</h3>
    <p>1. In Telegram den Chat mit <b>@BotFather</b> öffnen, <code>/newbot</code> schicken und den Schritten folgen.<br>
    2. Den Token, den BotFather schickt, hier einfügen.<br>
    3. Danach öffnet sich dein Bot: Schick ihm irgendeine Nachricht, z. B. <code>/start</code>.</p>
    <input class="field" id="tg-token" type="password" placeholder="123456789:ABC…" style="width:100%">
    <div class="sheet-actions"><button class="btn" onclick="closeSheet()">Abbrechen</button><button class="btn primary" id="tg-connect">Verbinden</button></div>`);
  $("#tg-connect").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    e.currentTarget.textContent = "Warte auf deine Nachricht an den Bot …";
    try {
      const r = await api("/api/telegram/connect", { method: "POST", body: { token: $("#tg-token").value } });
      closeSheet(); toast(`Verbunden mit @${r.bot} (${r.who})`); renderSettings();
    } catch (err) { toast(err.message, true); closeSheet(); }
  });
}

// --- Start --------------------------------------------------------------------

// Im nativen Fenster (v=1) scheint der macOS-Milchglas-Hintergrund durch die Seitenleiste
document.documentElement.classList.toggle("vibrant", new URLSearchParams(location.search).get("v") === "1");
// Link zur neuen Oberfläche StudyHub (ui/studyhub/), mit demselben Sitzungs-Token
$("#studyhub-link").href = `/ui/studyhub/index.html?t=${encodeURIComponent(TOKEN)}`;
show(location.hash === "#tutor" ? "tutor" : "overview");
setInterval(refreshStatus, 4000);

// Tastaturkürzel wie in Mac-Apps: ⌘1–6 Ansichten, ⌘R abgleichen, ⌘F suchen, ⌘, Einstellungen
document.addEventListener("keydown", (e) => {
  if (!e.metaKey || e.altKey || e.ctrlKey || !$("#wizard").hidden || !$("#sheet").hidden) return;
  const views = ["overview", "files", "learn", "tutor", "courses", "settings"];
  if (e.key >= "1" && e.key <= "6") show(views[+e.key - 1]);
  else if (e.key === ",") show("settings");
  else if (e.key === "r") { if (!$("#btn-sync").disabled) $("#btn-sync").click(); }
  else if (e.key === "f") { if (state.view !== "files") show("files"); $("#search").focus(); }
  else return;
  e.preventDefault();
});
