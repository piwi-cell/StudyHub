// =====================================================
// StudyHub – App-Logik (ohne Framework, bewusst einfach)
//
// Aufbau:
//   1) Zustand & Konstanten
//   2) Hilfsfunktionen (Ring, Datum, Toast, Vorlesen …)
//   3) Lernplan-Logik (Status, Fortschritt)
//   4) Register (Sidebar)
//   5) Seiten: Startseite, Modulseite
//   6) Tabs: Übersicht, Dokumente, Lernplan, Zusammenfassung,
//            Karteikarten, Sprachtutor, Skill hinzufügen, eigene Skills
//   7) Router (welche Seite?) & Klicks
//
// Navigation läuft über den Teil der URL hinter dem #:
//   #/                          → Startseite
//   #/modul/fima/uebersicht     → Modul Finanzmathematik, Tab Übersicht
// =====================================================

// ---------- 1) Zustand & Konstanten ----------

const $ = (selektor) => document.querySelector(selektor);

const zustand = {
  // Welche Semester im Register aufgeklappt sind (aktuelle offen, alte zu)
  offeneSemester: new Set(DATEN.semester.filter((s) => s.status === "aktuell").map((s) => s.id)),
  animieren: true, // Seite beim nächsten Zeichnen einblenden (nur bei Seitenwechsel)

  // Lernplan
  lernplanFilter: "alles", // alles | nochmal | offen
  offeneBereiche: new Set(["tut3"]),
  offeneNotizen: new Set(),
  ausgeblendetOffen: new Set(), // Module, deren Liste „Ausgeblendet“ aufgeklappt ist

  // Zusammenfassung
  thema: { fima: 3 }, // gerade geöffnetes Thema pro Modul
  einfach: new Set(), // Themen in „Einfacher erklären“-Ansicht, z. B. "fima-3"
  zfLaedt: null, // "karten" | "einfach" während einer simulierten KI-Aktion
  zfEditor: null, // Modul-ID, solange dort eine eigene Zusammenfassung geschrieben wird

  // Karteikarten (wird beim ersten Öffnen befüllt)
  karten: null,

  // Sprachtutor
  tutor: { phase: "start", schritt: -1, ton: true, lauf: 0 },

  // Skills
  skills: { fima: [] }, // hinzugefügte Skills pro Modul (echte Kurse: vom Server, live.js)
  vorschauOhneZusammenfassung: false,
};

const STATUS = {
  offen: { label: "offen", klasse: "status-offen" },
  inArbeit: { label: "in Arbeit", klasse: "status-arbeit" },
  erledigt: { label: "erledigt", klasse: "status-erledigt" },
  nochmal: { label: "nochmal üben", klasse: "status-nochmal" },
};
// Antippen schaltet in dieser Reihenfolge weiter
const STATUS_REIHENFOLGE = ["offen", "inArbeit", "erledigt", "nochmal"];

const AMPEL = { sitzt: "sitzt", unsicher: "unsicher", offen: "offen" };

// Tabs der Modulseite in drei Gruppen. Hinzugefügte Skills kommen vor das „+“.
function tabGruppen(modulId) {
  const eigeneSkills = (zustand.skills[modulId] || []).map((id) => {
    const skill = SKILL_KATALOG.find((s) => s.id === id);
    return { id: `skill-${id}`, name: skill.name, icon: skill.icon, skill: id };
  });

  // Echte Kurse: Lernplan steckt im Tab „Dokumente“ (jede Datei direkt abhaken)
  const grundlage = MODUL_DETAILS[modulId]?.live
    ? [{ id: "dokumente", name: "Dokumente", icon: "dokument" }]
    : [{ id: "dokumente", name: "Dokumente", icon: "dokument" }, { id: "lernplan", name: "Lernplan", icon: "lernplan" }];

  return [
    { label: "Start", tabs: [{ id: "uebersicht", name: "Übersicht", icon: "uebersicht" }] },
    { label: "Grundlage", tabs: grundlage },
    {
      label: "Skills",
      tabs: [
        { id: "zusammenfassung", name: "Zusammenfassung", icon: "zusammenfassung" },
        { id: "karteikarten", name: "Karteikarten", icon: "karten" },
        { id: "sprachtutor", name: "Sprachtutor", icon: "stimme" },
        ...eigeneSkills,
        { id: "skill-hinzufuegen", name: "Skill hinzufügen", icon: "plus", nurIcon: true },
      ],
    },
  ];
}

// ---------- 2) Hilfsfunktionen ----------

// Alle Module aus allen Semestern (Kopie mit Verweis aufs Semester)
function alleModule() {
  return DATEN.semester.flatMap((sem) => sem.module.map((m) => ({ ...m, semester: sem })));
}

function findeModul(id) {
  return alleModule().find((m) => m.id === id);
}

// Das Original-Objekt in DATEN (zum Ändern, z. B. Fortschritt)
function modulDaten(id) {
  return DATEN.semester.flatMap((s) => s.module).find((m) => m.id === id);
}

// „1 Datei“, „3 Dateien“
function anzahl(n, eins, mehr) {
  return `${n} ${n === 1 ? eins : mehr}`;
}

function begruessung() {
  const stunde = new Date().getHours();
  if (stunde < 11) return "Guten Morgen";
  if (stunde < 18) return "Guten Tag";
  return "Guten Abend";
}

// "2026-10-21" → "21. Okt."
function datumKurz(iso) {
  return new Date(iso).toLocaleDateString("de-DE", { day: "numeric", month: "short" });
}

function heuteLang() {
  return new Date().toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });
}

const pause = (ms) => new Promise((r) => setTimeout(r, ms));

// Fortschrittsring als SVG. prozent = null bedeutet "noch nicht gestartet"
function ring(prozent, groesse = 44, dicke = 4, mitText = true) {
  const radius = (groesse - dicke) / 2;
  const umfang = 2 * Math.PI * radius;
  const versatz = umfang * (1 - (prozent ?? 0) / 100);
  const mitte = groesse / 2;
  const text = prozent == null ? "–" : `${prozent}%`;
  const ariaText = prozent == null ? "Lernstand: noch nicht gestartet" : `Lernstand ${prozent} Prozent`;

  return `
    <span class="ring-wrap" role="img" aria-label="${ariaText}">
      <svg width="${groesse}" height="${groesse}" viewBox="0 0 ${groesse} ${groesse}" aria-hidden="true">
        <circle class="ring-spur" cx="${mitte}" cy="${mitte}" r="${radius}" fill="none" stroke-width="${dicke}"/>
        <circle class="ring-wert" cx="${mitte}" cy="${mitte}" r="${radius}" fill="none" stroke-width="${dicke}"
          stroke-linecap="round" stroke-dasharray="${umfang}" stroke-dashoffset="${versatz}"
          transform="rotate(-90 ${mitte} ${mitte})"/>
      </svg>
      ${mitText ? `<span class="ring-text" style="font-size:${Math.round(groesse * 0.27)}px">${text}</span>` : ""}
    </span>`;
}

// Formel als HTML: entweder einfacher Text oder mit echtem Bruch (Zähler über Nenner)
function formelAusdruck(f) {
  if (f.bruch) {
    return `${f.vor || ""} <span class="bruch"><span>${f.bruch[0]}</span><span>${f.bruch[1]}</span></span>`;
  }
  return f.text;
}

// Kurze Meldung unten einblenden
let toastTimer;
function zeigeToast(text) {
  const toast = $("#toast");
  toast.textContent = text;
  toast.classList.add("sichtbar");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("sichtbar"), 2800);
}

// HTML-Tags und Zeichen-Codes (&amp; …) entfernen, z. B. fürs Vorlesen
function nurText(html) {
  const el = document.createElement("textarea");
  el.innerHTML = String(html).replace(/<[^>]+>/g, " ");
  return el.value.replace(/\s+/g, " ").trim();
}

// Vorlesen. Mit laufender App über ElevenLabs (live.js), sonst mit der Browser-Stimme.
// Gibt ein Promise zurück, das fertig ist, wenn der Text zu Ende gesprochen wurde.
function sprich(text, optionen = {}) {
  if (LIVE.aktiv && LIVE.voiceReady && !optionen.stumm) return LIVE.sprechen(nurText(text));
  return sprichBrowser(text, optionen);
}

function sprichBrowser(text, { stumm = false } = {}) {
  return new Promise((fertig) => {
    const schaetzung = Math.min(12000, 800 + text.length * 55); // falls es keine Stimme gibt
    if (stumm || !("speechSynthesis" in window)) {
      setTimeout(fertig, schaetzung);
      return;
    }
    speechSynthesis.cancel();
    const satz = new SpeechSynthesisUtterance(nurText(text));
    satz.lang = "de-DE";
    const stimme = speechSynthesis.getVoices().find((v) => v.lang.startsWith("de"));
    if (stimme) satz.voice = stimme;
    let erledigt = false;
    const ende = () => { if (!erledigt) { erledigt = true; fertig(); } };
    satz.onend = ende;
    satz.onerror = ende;
    setTimeout(ende, schaetzung + 8000); // Sicherheitsnetz, falls onend nie kommt
    speechSynthesis.speak(satz);
  });
}

function vorlesen(text) {
  zeigeToast("Wird vorgelesen …");
  sprich(text);
}

// Füllt alle Elemente mit data-icon="…" mit dem passenden Icon (für die Top-Bar)
function iconsEinsetzen() {
  document.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icon(el.dataset.icon, el.dataset.icon === "logo" ? 22 : 18);
  });
}

// ---------- 3) Lernplan-Logik ----------

function alleEintraege(lp) {
  return [...lp.kapitel.flatMap((k) => k.eintraege), ...lp.bereiche.flatMap((b) => b.aufgaben)];
}

function zaehleStatus(liste) {
  const zahl = (status) => liste.filter((e) => e.status === status).length;
  return { erledigt: zahl("erledigt"), nochmal: zahl("nochmal"), gesamt: liste.length };
}

// Stand beim Laden merken, damit Änderungen die Gesamtzahlen (52 von 217) verschieben
const LERNPLAN_START = {};
for (const [id, d] of Object.entries(MODUL_DETAILS)) {
  LERNPLAN_START[id] = zaehleStatus(alleEintraege(d.lernplan));
}

// Gesamtfortschritt: Mock-Gesamtzahlen + alles, was in der Demo geändert wurde
function lernstand(modulId) {
  const lp = MODUL_DETAILS[modulId].lernplan;
  const jetzt = zaehleStatus(alleEintraege(lp));
  if (!lp.basis) {
    // Echte Kurse: nur das zählen, was wirklich da ist
    return {
      erledigt: jetzt.erledigt,
      nochmal: jetzt.nochmal,
      offen: jetzt.gesamt - jetzt.erledigt - jetzt.nochmal,
      gesamt: jetzt.gesamt,
      prozent: jetzt.gesamt ? Math.round((jetzt.erledigt / jetzt.gesamt) * 100) : 0,
    };
  }
  const start = LERNPLAN_START[modulId];
  const erledigt = lp.basis.erledigt + jetzt.erledigt - start.erledigt;
  const nochmal = lp.basis.nochmal + jetzt.nochmal - start.nochmal;
  return {
    erledigt,
    nochmal,
    offen: lp.basis.gesamt - erledigt - nochmal,
    gesamt: lp.basis.gesamt,
    prozent: Math.round((erledigt / lp.basis.gesamt) * 100),
  };
}

function findeEintrag(modulId, eintragId) {
  return alleEintraege(MODUL_DETAILS[modulId].lernplan).find((e) => e.id === eintragId);
}

function setzeStatus(modulId, eintragId, status) {
  const e = findeEintrag(modulId, eintragId);
  if (!e) return;
  e.status = status;
  LIVE.eintragGeaendert(e); // bei echten Kursen im Browser speichern
  const stand = lernstand(modulId);
  const m = modulDaten(modulId);
  m.fortschritt = stand.prozent;
  m.zeile = `${stand.erledigt} von ${stand.gesamt} ${MODUL_DETAILS[modulId].live ? "erledigt" : "Einträgen"}`;
}

// Die nächsten Aufgaben aus der Vorlesung (alles, was nicht erledigt ist)
function naechsteAufgaben(lp, anzahl = 3) {
  return lp.kapitel
    .flatMap((k) => k.eintraege.map((e) => ({ ...e, kapitel: `${k.nr} ${k.titel}` })))
    .filter((e) => e.status !== "erledigt")
    .slice(0, anzahl);
}

function statusKnopf(modulId, e) {
  const s = STATUS[e.status];
  return `<button class="status ${s.klasse}" data-aktion="status-weiter" data-modul="${modulId}" data-id="${e.id}"
    data-fokus="status-${e.id}" aria-label="${e.titel}: Status ${s.label}. Antippen zum Weiterschalten">${s.label}</button>`;
}

// ---------- 4) Register (Sidebar) ----------

function renderSidebar(aktivesModulId, seite = "start") {
  const istStart = !aktivesModulId && seite === "start";
  const navLink = (ziel, iconName, text) => {
    const aktiv = seite === ziel;
    return `<a href="#/${ziel}" class="nav-start nav-unten ${aktiv ? "aktiv" : ""}" ${aktiv ? 'aria-current="page"' : ""}>${icon(iconName)} ${text}</a>`;
  };

  const semesterHtml = DATEN.semester
    .map((sem) => {
      const offen = zustand.offeneSemester.has(sem.id);
      const module = sem.module
        .map((m) => {
          const aktiv = m.id === aktivesModulId;
          return `
            <li>
              <a href="#/modul/${m.id}/uebersicht" class="modul-link ${aktiv ? "aktiv" : ""}" ${aktiv ? 'aria-current="page"' : ""}>
                ${ring(m.fortschritt, 26, 3, false)}
                <span class="modul-name">${m.name}${m.beispiel && LIVE.aktiv ? ' <span class="mini">Beispiel</span>' : ""}</span>
                <span class="modul-prozent">${m.fortschritt == null ? "–" : m.fortschritt + " %"}</span>
              </a>
            </li>`;
        })
        .join("");

      return `
        <section class="semester">
          <button class="semester-kopf" data-aktion="semester-umschalten" data-id="${sem.id}" data-fokus="sem-${sem.id}"
            aria-expanded="${offen}" aria-controls="sem-${sem.id}">
            <span>${sem.name} · ${sem.status}</span>${icon("chevron", 16)}
          </button>
          <ul id="sem-${sem.id}" ${offen ? "" : "hidden"}>${module}</ul>
        </section>`;
    })
    .join("");

  $("#sidebar").innerHTML = `
    <a href="#/" class="nav-start ${istStart ? "aktiv" : ""}" ${istStart ? 'aria-current="page"' : ""}>
      ${icon("start")} Startseite
    </a>
    <div class="sidebar-trenner" role="separator"></div>
    ${semesterHtml}
    <div class="sidebar-unten">
      <button class="ilias-knopf" data-aktion="modul-hinzufuegen">${icon("plus", 18)} Modul aus ILIAS hinzufügen</button>
      ${navLink("bibliotheken", "bibliothek", "Bibliotheken")}
      ${navLink("kurse", "glossar", "Kurse")}
      ${navLink("einstellungen", "einstellungen", "Einstellungen")}
    </div>`;
}

// ---------- 5a) Startseite ----------

function seiteStart() {
  // Mit echten Daten gibt es keinen Klausurtermin (ILIAS kennt keinen) und keinen Vornamen
  const klausurModul = DATEN.naechsteKlausur ? findeModul(DATEN.naechsteKlausur.modulId) : null;
  const aktuell = DATEN.semester.find((s) => s.status === "aktuell") || DATEN.semester[0];
  const name = DATEN.nutzer.vorname ? `, ${DATEN.nutzer.vorname}` : "";
  const unterzeile = klausurModul
    ? `${icon("kalender", 18)} Klausur ${klausurModul.name} in <strong>${DATEN.naechsteKlausur.tage} Tagen</strong>`
    : `${icon("uebersicht", 18)} <strong>${aktuell.module.filter((m) => !m.beispiel).length} Module</strong> in ${aktuell.name}`;
  const weiterModul = klausurModul || findeModul(DATEN.heuteDran[0]?.modulId) || aktuell.module[0];
  const weiterTab = klausurModul ? "karteikarten" : DATEN.heuteDran[0]?.tab || "uebersicht";

  const heuteChips = DATEN.heuteDran
    .map((a) => `<a class="chip" href="#/modul/${a.modulId}/${a.tab}">${icon(a.icon, 18)}${a.text}</a>`)
    .join("");

  return `
    <section class="hero mit-aura">
      <div class="aura" aria-hidden="true"></div>
      <p class="eyebrow">${heuteLang()}</p>
      <h1>${begruessung()}${name}</h1>
      <p class="hero-sub">${unterzeile}</p>
    </section>

    ${LIVE.aktiv && !LIVE.sync.demo && !LIVE.sync.configured ? `
      <section class="hinweis-leiste glas">
        <p><b>ILIAS ist noch nicht verbunden.</b> Melde dich einmal mit deiner Uni-ID an, dann holt StudyHub deine Kurse.</p>
        <a class="pille" href="#/einrichtung">Mit Uni-Login verbinden</a>
      </section>` : ""}

    <section class="heute glas" aria-labelledby="heute-titel">
      <h2 id="heute-titel" class="mini-titel">Heute dran</h2>
      <div class="heute-liste">${heuteChips || '<p class="klein">Gerade ist nichts fällig. Neue Dateien und fällige Karteikarten erscheinen hier.</p>'}</div>
      ${weiterModul ? `<a class="pille" href="#/modul/${weiterModul.id}/${weiterTab}">Weiterlernen ${icon("pfeil", 18)}</a>` : ""}
    </section>

    <section aria-labelledby="module-titel">
      <div class="abschnitt-kopf">
        <h2 id="module-titel">${aktuell.name} · aktuell</h2>
        <span class="klein">${aktuell.module.length} Module</span>
      </div>
      <div class="kachel-raster">
        ${aktuell.module.map(modulKachel).join("")}
        <button class="kachel-neu" data-aktion="modul-hinzufuegen">
          <span>${icon("plus", 24)}<br>Modul aus ILIAS hinzufügen</span>
        </button>
      </div>
    </section>`;
}

// Modul-Kachel = Mini-Version der Modul-Übersicht
function modulKachel(m) {
  const neuBadge = m.neu ? `<span class="badge badge-neu">${m.neu} neu</span>` : "";
  return `
    <a class="kachel glas" href="#/modul/${m.id}/uebersicht" aria-label="${m.name} öffnen">
      <div class="kachel-kopf">
        ${ring(m.fortschritt, 60, 5)}
        <span class="kachel-pfeil">${icon("pfeil", 16)}</span>
      </div>
      <h3>${m.name}</h3>
      <p class="kachel-info">${m.info}</p>
      <div class="kachel-fuss">
        <span class="klein">${m.zeile}</span>
        ${neuBadge}
      </div>
    </a>`;
}

// ---------- 5b) Modulseite ----------

function seiteModul(modulId, tabId) {
  const m = findeModul(modulId);
  if (!m) return seiteNichtGefunden();

  const d = MODUL_DETAILS[modulId];
  if (d?.live && tabId === "lernplan") tabId = "dokumente";
  const alleTabs = tabGruppen(modulId).flatMap((g) => g.tabs);
  const tab = alleTabs.find((t) => t.id === tabId) || alleTabs[0];

  let inhalt;
  if (!d) inhalt = hinweisKeineDaten(m);
  else if (tab.skill) inhalt = tabSkill(m, d, tab.skill);
  else if (d.live && tab.id === "zusammenfassung") inhalt = LIVE.tabZusammenfassung(m, d);
  else if (d.live && tab.id === "sprachtutor") inhalt = LIVE.tabSprachtutor(m, d);
  else inhalt = TAB_INHALT[tab.id](m, d);

  // Echte Kurse: Termin von Hand (m.klausur), anklickbar zum Ändern; Beispielmodul: Mock-Termin
  const klausur = d?.live ? LIVE.klausurBadge(m)
    : DATEN.naechsteKlausur?.modulId === m.id
      ? `<span class="badge">${icon("kalender", 14)} Klausur in ${DATEN.naechsteKlausur.tage} Tagen</span>` : "";
  const neu = m.neu ? `<span class="badge badge-neu">${anzahl(m.neu, "neue Datei", "neue Dateien")}</span>` : "";
  const herkunft = d?.live ? `<span class="badge badge-neu">● Live aus ILIAS</span>`
    : m.beispiel && LIVE.aktiv ? `<span class="badge">Beispieldaten</span>` : "";

  return `
    <header class="modul-kopf">
      <div>
        <p class="eyebrow">${m.semester.name} · ${m.semester.status}</p>
        <h1>${m.name}</h1>
        <div class="modul-kopf-infos">${herkunft}${klausur}${neu}<span class="badge">${m.zeile}</span></div>
      </div>
    </header>

    ${tabbar(m.id, tab.id)}

    <div role="tabpanel" aria-label="${tab.name}">${inhalt}</div>`;
}

// Tabbar mit den Gruppen Start │ Grundlage ┃ Skills
function tabbar(modulId, aktiverTab) {
  const gruppen = tabGruppen(modulId).map((gruppe, i) => {
    const tabs = gruppe.tabs
      .map((t) => {
        const aktiv = t.id === aktiverTab;
        const inhalt = t.nurIcon ? icon(t.icon, 18) : t.name;
        return `<a class="tab ${t.nurIcon ? "tab-plus" : ""}" role="tab" href="#/modul/${modulId}/${t.id}"
          aria-selected="${aktiv}" ${t.nurIcon ? `aria-label="${t.name}"` : ""}>${inhalt}</a>`;
      })
      .join("");

    // Trenner VOR der Gruppe: dünn nach "Start", kräftig vor "Skills"
    const trenner = i === 0 ? "" : `<span class="tab-trenner ${gruppe.label === "Skills" ? "stark" : ""}" aria-hidden="true"></span>`;

    return `${trenner}
      <div class="tab-gruppe">
        <div class="tab-gruppe-tabs">${tabs}</div>
        <span class="tab-gruppe-label" aria-hidden="true">${gruppe.label}</span>
      </div>`;
  }).join("");

  return `<nav class="tabbar glas" role="tablist" aria-label="Bereiche des Moduls">${gruppen}</nav>`;
}

// ---------- 6a) Tab „Übersicht“ ----------

function tabUebersicht(m, d) {
  return `
    <div class="widget-raster mit-aura">
      <div class="aura" aria-hidden="true"></div>
      ${widgetLernplan(m, d)}
      ${widgetKarteikarten(m, d)}
      ${widgetZusammenfassung(m, d)}
      ${widgetDokumente(m, d)}
    </div>`;
}

// Kopfzeile eines Widgets mit "Alle anzeigen"
function widgetKopf(titel, iconName, modulId, tabId) {
  return `
    <div class="widget-kopf">
      <h2>${icon(iconName)} ${titel}</h2>
      <a class="link-alle" href="#/modul/${modulId}/${tabId}" aria-label="${titel}: alle anzeigen">
        Alle anzeigen ${icon("pfeil", 16)}
      </a>
    </div>`;
}

function widgetLernplan(m, d) {
  const stand = lernstand(m.id);
  const aufgaben = naechsteAufgaben(d.lernplan)
    .map((a) => `
      <li class="zeile">
        <span class="nr">${a.nr}</span>
        <div class="zeile-text">
          <p class="zeile-titel">${a.titel}</p>
          <p class="klein">${a.kapitel}</p>
        </div>
        ${statusKnopf(m.id, a)}
      </li>`)
    .join("");

  return `
    <article class="widget glas">
      ${widgetKopf("Lernplan", "lernplan", m.id, "lernplan")}
      <div class="lernplan-stand">
        <span class="zahl-gross">${stand.prozent} %</span>
        <span class="klein">${stand.erledigt} von ${stand.gesamt} Einträgen erledigt</span>
      </div>
      <div class="balken" role="progressbar" aria-valuenow="${stand.prozent}" aria-valuemin="0" aria-valuemax="100"
        aria-label="Lernplan-Fortschritt"><span style="width:${stand.prozent}%"></span></div>
      <div class="lernplan-zahlen">
        <span><b>${stand.offen}</b> offen</span>
        <span><b>${stand.nochmal}</b> nochmal üben</span>
      </div>
      <div>
        <h3 class="mini-titel" style="margin-bottom:4px">Als Nächstes</h3>
        <ul class="liste-zeilen">${aufgaben || '<li class="klein">Alles erledigt 🎉</li>'}</ul>
      </div>
    </article>`;
}

function widgetKarteikarten(m, d) {
  const k = d.karten;
  if (!k.gesamt) {
    return `
      <article class="widget glas widget-karten">
        ${widgetKopf("Karteikarten", "karten", m.id, "karteikarten")}
        <p>Noch keine Karteikarten. Sie entstehen aus der Zusammenfassung.</p>
        <a class="pille" href="#/modul/${m.id}/zusammenfassung">Zur Zusammenfassung ${icon("pfeil", 18)}</a>
      </article>`;
  }
  const ersteKarte = k.liste.find((x) => x.frage === k.beispielFrage) || k.liste[0];
  const thema = d.themen.find((t) => t.nr === ersteKarte.thema);
  return `
    <article class="widget glas widget-karten">
      ${widgetKopf("Karteikarten", "karten", m.id, "karteikarten")}
      <div class="karten-stapel" aria-hidden="true">
        <span></span><span></span>
        <div class="karte-vorschau">
          <span class="mini">${thema ? `Thema ${thema.nr} · ${thema.titel}` : ersteKarte.quelle}</span>
          ${k.beispielFrage}
        </div>
      </div>
      <div>
        <p class="karten-zahl"><span class="zahl-gross">${k.faellig}</span><span>fällig</span></p>
        <p class="klein">von ${k.gesamt} Karten${k.faellig || k.naechste == null ? "" : ` · nächste in ${k.naechste} T.`}</p>
      </div>
      <a class="pille" href="#/modul/${m.id}/karteikarten">Lernen starten ${icon("pfeil", 18)}</a>
    </article>`;
}

function widgetZusammenfassung(m, d) {
  const themen = d.themen
    .map((t) => `
      <li>
        <a class="zeile zeile-link" href="#/modul/${m.id}/zusammenfassung" data-aktion="thema-waehlen" data-modul="${m.id}" data-nr="${t.nr}">
          <span class="nr">${t.nr}</span>
          <span class="zeile-text"><span class="zeile-titel">${t.titel}</span></span>
          <span class="ampel ampel-${t.stand}">${AMPEL[t.stand]}</span>
        </a>
      </li>`)
    .join("");

  const zaehle = (stand) => d.themen.filter((t) => t.stand === stand).length;

  return `
    <article class="widget glas">
      ${widgetKopf("Zusammenfassung", "zusammenfassung", m.id, "zusammenfassung")}
      <div class="ampel-legende">
        <span>${zaehle("sitzt")} sitzen</span><span>${zaehle("unsicher")} unsicher</span><span>${zaehle("offen")} offen</span>
      </div>
      <ul class="liste-zeilen">${themen}</ul>
    </article>`;
}

function alleDateien(d) {
  return d.dokumente.flatMap((g) => g.dateien.map((f) => ({ ...f, gruppe: g.gruppe })));
}

function widgetDokumente(m, d) {
  // Nach Datum sortieren (neueste zuerst), die ersten 3 nehmen
  const neueste = alleDateien(d).sort((a, b) => b.datum.localeCompare(a.datum)).slice(0, 3);

  const zeilen = neueste
    .map((f) => `
      <li class="zeile">
        <span class="datei-icon">${icon("dokument", 18)}</span>
        <div class="zeile-text">
          <p class="zeile-titel">${f.name}</p>
          <p class="klein">${f.gruppe} · ${datumKurz(f.datum)}</p>
        </div>
        ${f.neu ? '<span class="badge badge-neu">neu</span>' : ""}
      </li>`)
    .join("");

  return `
    <article class="widget glas">
      ${widgetKopf("Dokumente", "dokument", m.id, "dokumente")}
      <p class="klein">${anzahl(alleDateien(d).length, "Datei", "Dateien")} aus ILIAS · sortiert nach Vorlesung, Tutorium, Übung</p>
      <ul class="liste-zeilen">${zeilen}</ul>
    </article>`;
}

// ---------- 6b) Tab „Dokumente“ ----------

function tabDokumente(m, d) {
  if (d.live) return tabDokumenteLernplan(m, d);
  const dateien = alleDateien(d);
  const neu = dateien.filter((f) => f.neu).length;

  const gruppen = d.dokumente
    .map((g) => {
      const zeilen = g.dateien
        .map((f) => `
          <li>
            <button class="zeile dok-zeile" ${d.live ? `data-aktion="live-dokument" data-id="${f.id}"` : `data-aktion="dokument-oeffnen" data-name="${f.name}"`}>
              <span class="datei-icon">${icon("dokument", 18)}</span>
              <span class="zeile-text">
                <span class="zeile-titel">${f.name}</span>
                <span class="klein">${f.art || "PDF"} · ${f.seiten ? `${f.seiten} Seiten` : f.groesse} · ${datumKurz(f.datum)}</span>
              </span>
              ${f.zusammengefasst ? `<span class="dok-status">${icon("haken", 14)} In Zusammenfassung</span>` : ""}
              ${f.neu ? '<span class="badge badge-neu">neu</span>' : ""}
            </button>
          </li>`)
        .join("");

      return `
        <section class="dok-gruppe" aria-labelledby="grp-${g.gruppe}">
          <div class="abschnitt-kopf">
            <h2 id="grp-${g.gruppe}">${g.gruppe}</h2>
            <span class="klein">${anzahl(g.dateien.length, "Datei", "Dateien")}</span>
          </div>
          <ul class="glas liste-karte">${zeilen}</ul>
        </section>`;
    })
    .join("");

  return `
    <div class="tab-inhalt">
      <div class="info-leiste mit-aura">
        <div class="aura aura-klein" aria-hidden="true"></div>
        <p><b>${anzahl(dateien.length, "Datei", "Dateien")}</b> aus ILIAS · ${neu} neu${d.live ? " · Klick öffnet die Datei" : ""}</p>
        <p class="klein">Automatisch sortiert nach Vorlesung, Tutorium und Übung</p>
        ${d.live ? `<div class="hochladen-zeile">
          <button class="knopf-hell" data-aktion="live-hochladen" data-modul="${m.id}">${icon("plus", 18)} Eigene Dateien hinzufügen</button>
          <span class="klein">oder Dateien ins Fenster ziehen · landen unter „Eigene Dateien“</span>
        </div>` : ""}
      </div>
      ${gruppen}
    </div>`;
}

// Echte Kurse: Dokumente und Lernplan in einem. Jede Datei ist ein Lernplan-Eintrag (gleiche Kurz-ID,
// siehe aufbereiten() in live.js): Haken setzen = erledigt, Status-Chip für „in Arbeit“ und „nochmal üben“.
function dokumentZeile(m, f) {
  const e = findeEintrag(m.id, f.id); // eigene Zusammenfassungen haben keinen Eintrag
  const erledigt = e?.status === "erledigt";
  const notizOffen = e && zustand.offeneNotizen.has(e.id);
  const haken = e
    ? `<button class="abhaken" data-aktion="abhaken" data-modul="${m.id}" data-id="${e.id}" data-fokus="abhaken-${e.id}"
        role="checkbox" aria-checked="${erledigt}" aria-label="${e.titel}: ${erledigt ? "erledigt" : "als erledigt abhaken"}"
        title="${erledigt ? "Erledigt · antippen für offen" : "Als erledigt abhaken"}">${erledigt ? icon("haken", 16) : ""}</button>`
    : `<span class="abhaken-platz" aria-hidden="true"></span>`;
  return `
    <li class="lp-eintrag dok-eintrag ${erledigt ? "ist-erledigt" : ""}">
      <div class="zeile">
        ${haken}
        <button class="dok-zeile dok-oeffnen" data-aktion="live-dokument" data-id="${f.id}" title="${f.name} öffnen">
          <span class="datei-icon">${icon("dokument", 18)}</span>
          <span class="zeile-text">
            <span class="zeile-titel">${f.name}</span>
            <span class="klein">${f.art || "PDF"} · ${f.groesse} · ${datumKurz(f.datum)}</span>
          </span>
        </button>
        ${f.zusammengefasst ? `<span class="dok-status">${icon("haken", 14)} In Zusammenfassung</span>` : ""}
        ${f.neu ? '<span class="badge badge-neu">neu</span>' : ""}
        <button class="icon-knopf klein-knopf dok-ausblenden" data-aktion="live-ausblenden" data-id="${f.id}" data-name="${f.name}"
          aria-label="${f.name} in der App ausblenden" title="In der App ausblenden (bleibt auf dem Mac)">${icon("ausblenden", 16)}</button>
        ${e ? `
          <button class="icon-knopf klein-knopf ${e.notiz ? "hat-notiz" : ""}" data-aktion="notiz-umschalten" data-id="${e.id}"
            data-fokus="notiz-${e.id}" aria-label="Notiz zu ${e.titel}" aria-expanded="${notizOffen}">${icon("notiz", 16)}</button>
          ${statusKnopf(m.id, e)}` : ""}
      </div>
      ${notizOffen ? `
        <label class="notiz">
          <span class="sr-only">Notiz zu ${e.titel}</span>
          <textarea data-notiz="${e.id}" data-modul="${m.id}" rows="2" placeholder="Notiz, z. B. was du nochmal ansehen willst …">${e.notiz}</textarea>
        </label>` : ""}
    </li>`;
}

function tabDokumenteLernplan(m, d) {
  const dateien = alleDateien(d);
  const neu = dateien.filter((f) => f.neu).length;
  const stand = lernstand(m.id);
  const filter = [
    { id: "alles", name: "Alles" },
    { id: "offen", name: "Noch nicht erledigt" },
    { id: "nochmal", name: "Nur „nochmal üben“" },
  ]
    .map((f) => `<button class="segment-knopf" data-aktion="lernplan-filter" data-wert="${f.id}" data-fokus="filter-${f.id}"
      aria-pressed="${zustand.lernplanFilter === f.id}">${f.name}</button>`)
    .join("");

  const gruppen = d.dokumente
    .map((g) => {
      const eintraege = g.dateien.map((f) => findeEintrag(m.id, f.id)).filter(Boolean);
      const sichtbar = zustand.lernplanFilter === "alles" ? g.dateien
        : g.dateien.filter((f) => { const e = findeEintrag(m.id, f.id); return e && passtZumFilter(e); });
      if (!sichtbar.length) return "";
      const z = zaehleStatus(eintraege);
      const zahl = z.gesamt
        ? `<span class="mini-balken" aria-hidden="true"><span style="width:${(z.erledigt / z.gesamt) * 100}%"></span></span>
           <span class="klein">${z.erledigt} / ${z.gesamt} erledigt</span>`
        : `<span class="klein">${g.dateien.length} ${g.dateien.length === 1 ? "Datei" : "Dateien"}</span>`;
      return `
        <section class="dok-gruppe" aria-label="${g.gruppe}">
          <div class="abschnitt-kopf dok-gruppe-kopf">
            <h2>${g.gruppe}</h2>
            <span class="dok-gruppe-stand">${zahl}</span>
          </div>
          <ul class="glas liste-karte liste-zeilen">${sichtbar.map((f) => dokumentZeile(m, f)).join("")}</ul>
        </section>`;
    })
    .join("");

  const versteckt = d.ausgeblendet || [];
  const verstecktOffen = zustand.ausgeblendetOffen.has(m.id);
  const ausgeblendet = versteckt.length ? `
    <section class="dok-gruppe dok-ausgeblendet">
      <button class="bereich-kopf" data-aktion="ausgeblendet-umschalten" data-modul="${m.id}" data-fokus="ausgeblendet-${m.id}"
        aria-expanded="${verstecktOffen}" aria-controls="ausgeblendet-${m.id}">
        ${icon("ausblenden", 16)} <span class="bereich-titel">Ausgeblendet</span>
        <span class="klein bereich-zahl">${versteckt.length} ${versteckt.length === 1 ? "Datei" : "Dateien"} · nur in der App, auf dem Mac noch da</span>
        ${icon("chevron", 16)}
      </button>
      <ul class="glas liste-karte liste-zeilen" id="ausgeblendet-${m.id}" ${verstecktOffen ? "" : "hidden"}>
        ${versteckt.map((f) => `
          <li class="zeile">
            <span class="datei-icon">${icon("dokument", 18)}</span>
            <span class="zeile-text"><span class="zeile-titel">${f.name}</span><span class="klein">${f.ordner}</span></span>
            <button class="knopf-hell" data-aktion="live-einblenden" data-id="${f.id}" data-name="${f.name}">${icon("einblenden", 16)} Einblenden</button>
          </li>`).join("")}
      </ul>
    </section>` : "";

  const leer = gruppen ? "" : `<div class="platzhalter glas"><h2>Nichts gefunden</h2><p>${dateien.length
    ? "Für diesen Filter gibt es gerade keine Dateien." : "Noch keine Dateien. Sie erscheinen nach dem nächsten Abgleich mit ILIAS."}</p></div>`;

  return `
    <div class="tab-inhalt">
      <section class="lp-kopf glas mit-aura">
        <div class="aura" aria-hidden="true"></div>
        ${ring(stand.prozent, 96, 8)}
        <div class="lp-kopf-text">
          <h2>Lernplan</h2>
          <p class="lp-kopf-zahl"><b>${stand.prozent} %</b> · ${stand.erledigt} von ${stand.gesamt} Dateien erledigt</p>
          <div class="lp-kopf-chips">
            <span class="status status-erledigt">${stand.erledigt} erledigt</span>
            <span class="status status-offen">${stand.offen} offen</span>
            <span class="status status-nochmal">${stand.nochmal} nochmal üben</span>
          </div>
          <p class="klein">${anzahl(dateien.length, "Datei", "Dateien")} aus ILIAS · ${neu} neu · sortiert nach Vorlesung, Tutorium und Übung</p>
        </div>
      </section>

      <div class="lp-werkzeuge">
        <div class="segment" role="group" aria-label="Dateien filtern">${filter}</div>
        <p class="klein">Haken setzen: erledigt · Chip antippen: offen → in Arbeit → erledigt → nochmal üben · Name öffnet die Datei</p>
      </div>
      <div class="hochladen-zeile">
        <button class="knopf-hell" data-aktion="live-hochladen" data-modul="${m.id}">${icon("plus", 18)} Eigene Dateien hinzufügen</button>
        <span class="klein">oder Dateien ins Fenster ziehen · landen unter „Eigene Dateien“</span>
      </div>
      ${gruppen}${leer}${ausgeblendet}
    </div>`;
}

// ---------- 6c) Tab „Lernplan“ ----------

function passtZumFilter(e) {
  if (zustand.lernplanFilter === "nochmal") return e.status === "nochmal";
  if (zustand.lernplanFilter === "offen") return e.status !== "erledigt";
  return true;
}

function lernplanZeile(modulId, e) {
  const notizOffen = zustand.offeneNotizen.has(e.id);
  return `
    <li class="lp-eintrag">
      <div class="zeile">
        <span class="nr">${e.nr}</span>
        <span class="zeile-text"><span class="zeile-titel">${e.titel}</span></span>
        <button class="icon-knopf klein-knopf ${e.notiz ? "hat-notiz" : ""}" data-aktion="notiz-umschalten" data-id="${e.id}"
          data-fokus="notiz-${e.id}" aria-label="Notiz zu ${e.nr} ${e.titel}" aria-expanded="${notizOffen}">${icon("notiz", 16)}</button>
        ${statusKnopf(modulId, e)}
      </div>
      ${notizOffen ? `
        <label class="notiz">
          <span class="sr-only">Notiz zu ${e.titel}</span>
          <textarea data-notiz="${e.id}" data-modul="${modulId}" rows="2" placeholder="Notiz, z. B. was du nochmal ansehen willst …">${e.notiz}</textarea>
        </label>` : ""}
    </li>`;
}

function tabLernplan(m, d) {
  const lp = d.lernplan;
  const stand = lernstand(m.id);

  const filter = [
    { id: "alles", name: "Alles" },
    { id: "nochmal", name: "Nur „nochmal üben“" },
    { id: "offen", name: "Noch nicht erledigt" },
  ]
    .map((f) => `<button class="segment-knopf" data-aktion="lernplan-filter" data-wert="${f.id}" data-fokus="filter-${f.id}"
      aria-pressed="${zustand.lernplanFilter === f.id}">${f.name}</button>`)
    .join("");

  // Vorlesung: Kapitel mit Einträgen
  const kapitel = lp.kapitel
    .map((k) => {
      const eintraege = k.eintraege.filter(passtZumFilter);
      if (!eintraege.length) return "";
      const z = zaehleStatus(k.eintraege);
      return `
        <section class="lp-kapitel">
          <div class="lp-kapitel-kopf">
            <h3>${k.nr} ${k.titel}</h3>
            <span class="klein">${z.erledigt} / ${z.gesamt}</span>
          </div>
          <ul class="liste-zeilen">${eintraege.map((e) => lernplanZeile(m.id, e)).join("")}</ul>
        </section>`;
    })
    .join("");

  // Tutorien & Übungen: aufklappbar mit Mini-Fortschrittsbalken
  const bereiche = lp.bereiche
    .map((b) => {
      const aufgaben = b.aufgaben.filter(passtZumFilter);
      if (!aufgaben.length) return "";
      const z = zaehleStatus(b.aufgaben);
      const offen = zustand.offeneBereiche.has(b.id);
      return `
        <div class="bereich glas">
          <button class="bereich-kopf" data-aktion="bereich-umschalten" data-id="${b.id}" data-fokus="bereich-${b.id}"
            aria-expanded="${offen}" aria-controls="ber-${b.id}">
            <span class="bereich-titel">${b.titel}</span>
            <span class="mini-balken" aria-hidden="true"><span style="width:${(z.erledigt / z.gesamt) * 100}%"></span></span>
            <span class="klein bereich-zahl">${z.erledigt}/${z.gesamt}</span>
            ${icon("chevron", 16)}
          </button>
          <ul class="liste-zeilen bereich-liste" id="ber-${b.id}" ${offen ? "" : "hidden"}>
            ${aufgaben.map((e) => lernplanZeile(m.id, e)).join("")}
          </ul>
        </div>`;
    })
    .join("");

  const leer = !kapitel && !bereiche
    ? `<div class="platzhalter glas"><h2>Nichts gefunden</h2><p>Für diesen Filter gibt es gerade keine Einträge.</p></div>` : "";

  return `
    <div class="tab-inhalt">
      <section class="lp-kopf glas mit-aura">
        <div class="aura" aria-hidden="true"></div>
        ${ring(stand.prozent, 96, 8)}
        <div class="lp-kopf-text">
          <h2>Gesamtfortschritt</h2>
          <p class="lp-kopf-zahl"><b>${stand.prozent} %</b> · ${stand.erledigt} von ${stand.gesamt} Einträgen</p>
          <div class="lp-kopf-chips">
            <span class="status status-erledigt">${stand.erledigt} erledigt</span>
            <span class="status status-offen">${stand.offen} offen</span>
            <span class="status status-nochmal">${stand.nochmal} nochmal üben</span>
          </div>
        </div>
      </section>

      <div class="lp-werkzeuge">
        <div class="segment" role="group" aria-label="Lernplan filtern">${filter}</div>
        <p class="klein">Status antippen: offen → in Arbeit → erledigt → nochmal üben</p>
      </div>

      ${kapitel ? `<section><h2 class="abschnitt-titel">${d.live ? "Unterlagen" : "Vorlesung"}</h2>${kapitel}</section>` : ""}
      ${bereiche ? `<section><h2 class="abschnitt-titel">Tutorien & Übungen</h2><div class="bereich-liste-aussen">${bereiche}</div></section>` : ""}
      ${leer}
    </div>`;
}

// ---------- 6d) Tab „Zusammenfassung“ ----------

function tabZusammenfassung(m, d) {
  const nr = zustand.thema[m.id] || d.themen[0].nr;
  const t = d.themen.find((x) => x.nr === nr);
  const schluessel = `${m.id}-${t.nr}`;
  const einfach = zustand.einfach.has(schluessel);

  const liste = d.themen
    .map((x) => `
      <li>
        <button class="thema-knopf" data-aktion="thema-waehlen" data-modul="${m.id}" data-nr="${x.nr}" data-fokus="thema-${x.nr}"
          aria-current="${x.nr === t.nr}">
          <span class="nr">${x.nr}</span>
          <span class="zeile-text"><span class="zeile-titel">${x.titel}</span></span>
          <span class="ampel-punkt ampel-${x.stand}" aria-label="${AMPEL[x.stand]}"></span>
        </button>
      </li>`)
    .join("");

  // Kernidee: normal oder „einfacher erklärt“ (mit kurzem Lade-Schimmer)
  let kernidee;
  if (zustand.zfLaedt === "einfach") {
    kernidee = `<div class="schimmer" aria-label="Wird einfacher erklärt"><span></span><span></span><span></span></div>`;
  } else if (einfach) {
    kernidee = `<p class="zf-text"><span class="badge badge-neu">${icon("einfach", 12)} einfacher erklärt</span><br>${t.einfacher}</p>`;
  } else {
    kernidee = `<p class="zf-text">${t.kernidee}</p>`;
  }

  const formeln = t.formeln
    .map((f) => `
      <div class="formel glas-stark">
        <span class="mini">${f.name}</span>
        <div class="formel-ausdruck">${formelAusdruck(f)}</div>
      </div>`)
    .join("");

  const kartenLaedt = zustand.zfLaedt === "karten";

  return `
    <div class="zf-layout">
      <nav class="zf-themen glas" aria-label="Themen">
        <h2 class="mini-titel">Themen</h2>
        <ul>${liste}</ul>
        <div class="ampel-legende zf-legende">
          <span><i class="ampel-punkt ampel-sitzt"></i>sitzt</span>
          <span><i class="ampel-punkt ampel-unsicher"></i>unsicher</span>
          <span><i class="ampel-punkt ampel-offen"></i>offen</span>
        </div>
      </nav>

      <article class="zf-detail mit-aura">
        <div class="aura" aria-hidden="true"></div>
        <header class="zf-kopf">
          <p class="eyebrow">Thema ${t.nr} · aus ${t.quelle.split(",")[0]}</p>
          <div class="zf-titelzeile">
            <h2>${t.titel}</h2>
            <span class="ampel ampel-${t.stand}">${AMPEL[t.stand]}</span>
          </div>
        </header>

        <div class="zf-aktionen">
          <button class="pille" data-aktion="karten-erstellen" data-modul="${m.id}" data-nr="${t.nr}" ${kartenLaedt ? "disabled" : ""}>
            ${icon(kartenLaedt ? "sync" : "karten", 18)} ${kartenLaedt ? "Karten werden erstellt …" : "Karten erstellen"}
          </button>
          <a class="knopf-hell" href="#/modul/${m.id}/sprachtutor" data-aktion="tutor-zuruecksetzen">${icon("stimme", 18)} Abfragen lassen</a>
          <button class="knopf-hell" data-aktion="einfacher-erklaeren" data-schluessel="${schluessel}" data-fokus="einfacher"
            aria-pressed="${einfach}">${icon("einfach", 18)} ${einfach ? "Original anzeigen" : "Einfacher erklären"}</button>
          <button class="knopf-hell" data-aktion="vorlesen-thema" data-modul="${m.id}" data-nr="${t.nr}">${icon("lautsprecher", 18)} Vorlesen</button>
        </div>

        <section class="zf-abschnitt">
          <h3 class="mini-titel">Kernidee</h3>
          ${kernidee}
        </section>

        <section class="zf-abschnitt">
          <h3 class="mini-titel">Formeln</h3>
          <div class="formel-raster">${formeln}</div>
        </section>

        <section class="falle">
          <h3>${icon("flagge", 18)} Typische Klausurfalle</h3>
          <p>${t.falle}</p>
        </section>

        <p class="quelle">${icon("dokument", 14)} Quelle: ${t.quelle}</p>
      </article>
    </div>`;
}

// ---------- 6e) Tab „Karteikarten“ ----------

// Neue Lernrunde für ein Thema (oder alle) vorbereiten. Ohne „alle“ nur fällige und neue Karten
// (Lernstand nach SM-2 vom Server; Beispielkarten haben keinen und gelten als fällig).
function neueRunde(modulId, filter = "alle", zaehlerBehalten = false, alleKarten = false) {
  const d = MODUL_DETAILS[modulId];
  const alt = zustand.karten;
  const imThema = d.karten.liste.filter((k) => filter === "alle" || k.thema === Number(filter));
  zustand.karten = {
    modul: modulId,
    filter,
    alleKarten,
    imThema: imThema.length,
    stapel: alleKarten ? imThema : imThema.filter((k) => k.faellig !== false),
    index: 0,
    aufgedeckt: false,
    gewusst: zaehlerBehalten && alt ? alt.gewusst : d.karten.runde.gewusst,
    nochmal: zaehlerBehalten && alt ? alt.nochmal : d.karten.runde.nochmal,
  };
}

function tabKarteikarten(m, d) {
  const werkzeuge = d.live ? LIVE.kartenWerkzeuge(m, d) : "";
  if (!d.karten.liste.length) {
    return `
      <div class="platzhalter glas">
        <div class="platzhalter-icon">${icon("karten", 28)}</div>
        <h2>Noch keine Karteikarten</h2>
        <p>Karteikarten entstehen aus der Zusammenfassung: Thema öffnen und „Karten erstellen“ wählen.
          ${d.live ? "Oder Karten aus Anki bzw. einer Textdatei übernehmen." : ""}</p>
        <a class="pille" href="#/modul/${m.id}/zusammenfassung">Zur Zusammenfassung ${icon("pfeil", 18)}</a>
      </div>
      ${werkzeuge}`;
  }
  if (!zustand.karten || zustand.karten.modul !== m.id) neueRunde(m.id);
  const k = zustand.karten;
  const gesamt = k.stapel.length;
  const offen = Math.max(0, gesamt - k.index);

  const eigene = d.karten.liste.some((x) => x.thema === 0)
    ? [{ id: "0", name: "Eigene & Anki" }] : [];
  const filter = [{ id: "alle", name: "Alle Themen" }, ...d.themen.map((t) => ({ id: String(t.nr), name: `${t.nr} ${t.titel}` })), ...eigene]
    .map((f) => `<button class="segment-knopf" data-aktion="karten-filter" data-wert="${f.id}" data-fokus="kfilter-${f.id}"
      aria-pressed="${k.filter === f.id}">${f.name}</button>`)
    .join("");

  const statistik = `
    <div class="runde-stats" aria-label="Diese Runde">
      <span class="mini-titel">Diese Runde</span>
      <span><i class="ampel-punkt ampel-sitzt"></i><b>${k.gewusst}</b> gewusst</span>
      <span><i class="ampel-punkt ampel-nochmal"></i><b>${k.nochmal}</b> nochmal</span>
      <span><i class="ampel-punkt ampel-offen"></i><b>${offen}</b> offen</span>
    </div>`;

  // Nichts fällig (und noch nichts geübt): Hinweis auf die nächste Wiederholung
  if (!k.stapel.length) {
    const naechste = d.karten.naechste;
    return `
      <div class="tab-inhalt">
        <div class="segment segment-scroll" role="group" aria-label="Nach Thema filtern">${filter}</div>
        <div class="karte-buehne mit-aura">
          <div class="aura" aria-hidden="true"></div>
          <div class="karte glas karte-fertig">
            <span class="platzhalter-icon">${icon("haken", 28)}</span>
            <h2>Heute nichts fällig</h2>
            <p>${naechste == null ? "Alle Karten sind wiederholt." : naechste <= 1 ? "Die nächsten Karten sind morgen fällig." : `Die nächsten Karten sind in ${naechste} Tagen fällig.`}
              Du kannst trotzdem alle ${k.imThema} Karten üben; das verschiebt ihre Termine.</p>
            <button class="pille" data-aktion="karten-alle-ueben">Trotzdem alle üben</button>
          </div>
        </div>
        ${werkzeuge}
      </div>`;
  }

  // Stapel leer → Runde geschafft
  if (k.index >= k.stapel.length) {
    return `
      <div class="tab-inhalt">
        <div class="segment segment-scroll" role="group" aria-label="Nach Thema filtern">${filter}</div>
        <div class="karte-buehne mit-aura">
          <div class="aura" aria-hidden="true"></div>
          <div class="karte glas karte-fertig">
            <span class="platzhalter-icon">${icon("haken", 28)}</span>
            <h2>Runde geschafft!</h2>
            <p>${k.gewusst} gewusst · ${k.nochmal} nochmal. „Nochmal“-Themen stehen jetzt im Lernplan.</p>
            <button class="pille" data-aktion="karten-neue-runde">Neue Runde starten</button>
          </div>
        </div>
        ${statistik}
        ${werkzeuge}
      </div>`;
  }

  const karte = k.stapel[k.index];
  const thema = d.themen.find((t) => t.nr === karte.thema); // fehlt bei eigenen und Anki-Karten
  const position = k.index + 1;
  const etikett = thema ? `Thema ${thema.nr} · ${thema.titel}` : karte.quelle;
  const zustandKarte = karte.neu ? "neu" : karte.faellig === false ? `erst in ${karte.inTagen} T. fällig` : "fällig";

  const vorne = `
    <div class="karte glas" aria-live="polite">
      <div class="karte-oben">
        <span class="mini">${etikett}${karte.faellig === undefined ? "" : ` · ${zustandKarte}`}</span>
        <button class="icon-knopf" data-aktion="karte-vorlesen" aria-label="Frage vorlesen">${icon("lautsprecher", 18)}</button>
      </div>
      <h2 class="karte-frage">${karte.frage}</h2>
      <span class="mini karte-hinweis">Erst selbst überlegen, dann umdrehen</span>
    </div>`;

  const hinten = `
    <div class="karte glas karte-hinten" aria-live="polite">
      <div class="karte-oben">
        <span class="mini">Antwort · ${karte.frage}</span>
        <button class="icon-knopf" data-aktion="karte-vorlesen" aria-label="Antwort vorlesen">${icon("lautsprecher", 18)}</button>
      </div>
      ${karte.formel ? `<div class="formel-ausdruck karte-formel">${formelAusdruck(karte.formel)}</div>` : ""}
      <p class="karte-antwort">${karte.antwort}</p>
      <p class="quelle">${icon("dokument", 14)} Quelle: ${karte.quelle}</p>
    </div>`;

  const aktionen = k.aufgedeckt
    ? `
      <div class="bewertungen" role="group" aria-label="Wie gut wusstest du es?">
        <button class="bewertung bewertung-nochmal" data-aktion="karte-bewerten" data-wert="nochmal" data-fokus="bew-nochmal">Nochmal <kbd>1</kbd></button>
        <button class="bewertung bewertung-schwer" data-aktion="karte-bewerten" data-wert="schwer" data-fokus="bew-schwer">Schwer <kbd>2</kbd></button>
        <button class="bewertung bewertung-gewusst" data-aktion="karte-bewerten" data-wert="gewusst" data-fokus="bew-gewusst">Gewusst <kbd>3</kbd></button>
      </div>`
    : `<button class="pille pille-gross" data-aktion="karte-aufdecken" data-fokus="aufdecken">Antwort zeigen <kbd>Leertaste</kbd></button>`;

  return `
    <div class="tab-inhalt">
      <div class="karten-kopf">
        ${thema ? `<a class="hinweis-chip" href="#/modul/${m.id}/zusammenfassung" data-aktion="thema-waehlen" data-modul="${m.id}" data-nr="${thema.nr}">
          ${icon("zusammenfassung", 16)} basiert auf Zusammenfassung · Thema ${thema.nr}
        </a>` : `<span class="hinweis-chip">${icon("karten", 16)} ${karte.quelle}</span>`}
        <span class="klein">Karte <b>${position}</b> von ${gesamt}${k.alleKarten ? "" : " fälligen"}</span>
      </div>
      <div class="segment segment-scroll" role="group" aria-label="Nach Thema filtern">${filter}</div>

      <div class="karte-buehne mit-aura">
        <div class="aura" aria-hidden="true"></div>
        ${k.aufgedeckt ? hinten : vorne}
      </div>

      <div class="karte-aktionen">${aktionen}</div>

      <div class="karten-fuss">
        ${statistik}
        <button class="link-leise" data-aktion="karte-melden">${icon("flagge", 14)} Karte als falsch melden</button>
      </div>
      ${werkzeuge}
    </div>`;
}

function karteBewerten(wert) {
  const k = zustand.karten;
  const karte = k.stapel[k.index];
  k.aufgedeckt = false;
  LIVE.karteBewertet(k.modul, karte, wert); // bei echten Kursen im Browser speichern

  if (wert === "gewusst" || wert === "schwer") {
    // Schwer zählt als gewusst; der Abstand bis zur nächsten Wiederholung wächst nur langsamer
    k.gewusst++;
    k.index++;
  } else {
    // „Nochmal“-Karten markieren das Thema im Lernplan (eigene und Anki-Karten haben keinen Eintrag)
    k.nochmal++;
    k.index++;
    const eintrag = karte.lernplan ? findeEintrag(k.modul, karte.lernplan) : null;
    if (eintrag) {
      setzeStatus(k.modul, karte.lernplan, "nochmal");
      zeigeToast(`${eintrag.nr} ${nurText(eintrag.titel)} im Lernplan auf „nochmal üben“ gesetzt`);
    }
  }
  neuZeichnen("aufdecken");
}

// ---------- 6f) Tab „Sprachtutor“ ----------

const TUTOR_STATUS = {
  start: "Bereit, wenn du es bist",
  spricht: "Tutor spricht …",
  deinZug: "Tippe aufs Mikrofon und antworte",
  hoert: "Ich höre zu …",
  denkt: "Einen Moment …",
  fertig: "Gespräch beendet · 2 von 2 richtig",
};

function tabSprachtutor(m, d) {
  const t = zustand.tutor;
  const thema = d.themen.find((x) => x.nr === d.tutor.thema);
  const sichtbar = d.tutor.verlauf.slice(0, t.schritt + 1);

  const blasen = sichtbar
    .map((z, i) => `
      <li class="blase blase-${z.von} ${i === t.schritt ? "blase-neu" : ""}">
        <span class="mini">${z.von === "tutor" ? "Tutor" : "Du"}</span>
        <p>${z.text}</p>
      </li>`)
    .join("");

  const knopf = {
    start: `<button class="pille" data-aktion="tutor-start">${icon("stimme", 18)} Gespräch starten</button>`,
    fertig: `
      <a class="pille" href="#/modul/${m.id}/karteikarten">${icon("karten", 18)} Zur Karteikarte</a>
      <button class="knopf-hell" data-aktion="tutor-zuruecksetzen">${icon("wiederholen", 18)} Nochmal</button>`,
  }[t.phase] || "";

  return `
    <div class="tutor">
      <section class="tutor-buehne glas mit-aura">
        <div class="aura" aria-hidden="true"></div>
        <div class="tutor-oben">
          <span class="hinweis-chip">${icon("zusammenfassung", 16)} Thema ${thema.nr} · ${thema.titel}</span>
          <button class="icon-knopf" data-aktion="tutor-ton" aria-pressed="${!t.ton}"
            aria-label="${t.ton ? "Ton ausschalten" : "Ton einschalten"}">${icon(t.ton ? "lautsprecher" : "stumm", 18)}</button>
        </div>
        <button class="orb orb-${t.phase}" data-aktion="tutor-mikro" ${t.phase === "deinZug" ? "" : "disabled"}
          aria-label="Antworten">
          <span class="orb-welle"></span><span class="orb-welle"></span>
          <span class="orb-kern">${icon("stimme", 36)}</span>
        </button>
        <p class="tutor-status" role="status">${TUTOR_STATUS[t.phase]}</p>
        <div class="tutor-knoepfe">${knopf}</div>
      </section>

      <section class="tutor-verlauf" aria-label="Gesprächsverlauf">
        <h2 class="mini-titel">Gespräch</h2>
        ${blasen ? `<ol class="blasen">${blasen}</ol>` : `<p class="klein">Der Tutor stellt dir Fragen zu deiner Zusammenfassung. Du antwortest einfach per Stimme.</p>`}
      </section>
    </div>`;
}

// Ablauf des Demo-Gesprächs. "lauf" verhindert, dass ein abgebrochenes Gespräch weiterläuft.
async function tutorSprechen() {
  const t = zustand.tutor;
  const lauf = t.lauf;
  const verlauf = MODUL_DETAILS.fima.tutor.verlauf;
  t.phase = "spricht";
  neuZeichnen();
  await sprich(verlauf[t.schritt].text, { stumm: !t.ton });
  if (lauf !== t.lauf) return;
  t.phase = t.schritt >= verlauf.length - 1 ? "fertig" : "deinZug";
  neuZeichnen();
}

async function tutorStart() {
  const t = zustand.tutor;
  t.schritt = 0;
  await tutorSprechen();
}

async function tutorAntworten() {
  const t = zustand.tutor;
  const lauf = t.lauf;
  t.phase = "hoert";
  neuZeichnen();
  await pause(2200); // simuliertes Zuhören
  if (lauf !== t.lauf) return;
  t.schritt++; // deine Antwort erscheint
  t.phase = "denkt";
  neuZeichnen();
  await pause(900);
  if (lauf !== t.lauf) return;
  t.schritt++; // Antwort des Tutors
  await tutorSprechen();
}

function tutorZuruecksetzen() {
  const t = zustand.tutor;
  t.lauf++;
  t.phase = "start";
  t.schritt = -1;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

// ---------- 6g) Tab „+ Skill hinzufügen“ ----------

function tabSkillHinzufuegen(m, d) {
  const hatZusammenfassung = d.zusammenfassungFertig && !zustand.vorschauOhneZusammenfassung;
  const hinzugefuegt = zustand.skills[m.id] || [];
  // Die Probeklausur gibt es bisher nur mit Beispieldaten
  const katalog = SKILL_KATALOG.filter((s) => !(d.live && s.id === "probeklausur"));

  const kacheln = katalog.map((s) => {
    const gesperrt = s.brauchtZusammenfassung && !hatZusammenfassung;
    const istDa = hinzugefuegt.includes(s.id);

    let fuss;
    if (gesperrt) {
      fuss = `<span class="skill-sperre">${icon("schloss", 14)} Erst Zusammenfassung erstellen</span>`;
    } else if (istDa) {
      fuss = `<a class="knopf-hell" href="#/modul/${m.id}/skill-${s.id}">${icon("haken", 16)} Öffnen</a>`;
    } else {
      fuss = `<button class="knopf-hell" data-aktion="skill-hinzufuegen" data-skill="${s.id}" data-modul="${m.id}">${icon("plus", 16)} Hinzufügen</button>`;
    }

    return `
      <article class="skill-kachel glas ${gesperrt ? "gesperrt" : ""}" ${gesperrt ? 'aria-disabled="true"' : ""}>
        <span class="skill-icon">${icon(s.icon, 22)}</span>
        <h3>${s.name}</h3>
        <p>${s.text}</p>
        <span class="skill-nutzt">${icon("funken", 14)} ${s.nutzt}</span>
        <div class="skill-fuss">${fuss}</div>
      </article>`;
  }).join("");

  return `
    <div class="tab-inhalt">
      <div class="skill-kopf">
        <div>
          <h2>Skill hinzufügen</h2>
          <p class="klein">Skills bauen auf deinen Unterlagen auf und erscheinen danach als eigener Tab.</p>
        </div>
        ${d.live ? "" : `<button class="knopf-hell" data-aktion="vorschau-umschalten" data-fokus="vorschau" aria-pressed="${zustand.vorschauOhneZusammenfassung}">
          ${zustand.vorschauOhneZusammenfassung ? "Mit Zusammenfassung ansehen" : "Ansicht ohne Zusammenfassung"}
        </button>`}
      </div>
      <div class="skill-raster mit-aura">
        <div class="aura" aria-hidden="true"></div>
        ${kacheln}
      </div>
    </div>`;
}

// ---------- 6h) Hinzugefügte Skills ----------

function tabSkill(m, d, skillId) {
  const s = SKILL_KATALOG.find((x) => x.id === skillId);
  let inhalt = "";

  const leer = (text) => `<div class="platzhalter glas"><div class="platzhalter-icon">${icon(s.icon, 28)}</div><h2>${s.name}</h2><p>${text}</p></div>`;

  if (skillId === "formelsammlung" && !d.themen.some((t) => t.formeln.length)) {
    inhalt = leer("In den Zusammenfassungen dieses Moduls wurden noch keine Formeln gefunden.");
  } else if (skillId === "glossar" && !d.glossar.length) {
    inhalt = leer("Das Glossar füllt sich aus den „Wichtigen Begriffen“ deiner Zusammenfassungen. Erstelle zuerst eine Zusammenfassung.");
  } else if (skillId === "probeklausur" && !d.probeklausur.length) {
    inhalt = leer("Die Probeklausur für echte Kurse kommt als Nächstes: Sie nutzt die Fragen des Sprachtutors und Altklausuren.");
  } else if (skillId === "formelsammlung") {
    inhalt = d.themen.map((t) => `
      <section class="zf-abschnitt">
        <h3 class="mini-titel">${t.nr} ${t.titel}</h3>
        <div class="formel-raster">${t.formeln.map((f) => `
          <div class="formel glas-stark"><span class="mini">${f.name}</span><div class="formel-ausdruck">${formelAusdruck(f)}</div></div>`).join("")}
        </div>
      </section>`).join("");
  } else if (skillId === "glossar") {
    inhalt = `<dl class="glossar glas">${d.glossar.map((g) => `<div><dt>${g.begriff}</dt><dd>${g.text}</dd></div>`).join("")}</dl>`;
  } else if (skillId === "probeklausur") {
    const summe = d.probeklausur.reduce((n, a) => n + a.punkte, 0);
    inhalt = `
      <p class="klein">${d.probeklausur.length} Aufgaben · ${summe} Punkte · 60 Minuten · im Stil von Altklausur_HWS2025.pdf</p>
      <ol class="aufgaben-liste">${d.probeklausur.map((a, i) => `
        <li class="glas aufgabe-karte">
          <div class="aufgabe-kopf"><b>Aufgabe ${i + 1}</b><span class="badge">${a.punkte} Punkte</span><span class="mini">Thema ${a.thema}</span></div>
          <p>${a.text}</p>
        </li>`).join("")}
      </ol>`;
  } else if (skillId === "mindmap") {
    inhalt = `
      <div class="mindmap glas">
        <div class="mindmap-mitte">${m.name}</div>
        <div class="mindmap-aeste">${d.themen.map((t) => `
          <div class="mindmap-ast">
            <span class="mindmap-thema"><i class="ampel-punkt ampel-${t.stand}"></i>${t.nr} ${t.titel}</span>
            <div class="mindmap-blaetter">${(t.formeln.length ? t.formeln : t.begriffe || []).slice(0, 8).map((f) => `<span class="chip chip-klein">${f.name}</span>`).join("")}</div>
          </div>`).join("")}
        </div>
      </div>`;
  } else if (skillId === "uebungsaufgaben") {
    const quellen = d.dokumente.filter((g) => g.gruppe !== "Vorlesung").flatMap((g) => g.dateien);
    inhalt = `<ul class="glas liste-karte">${quellen.map((f) => `
      <li class="zeile"><span class="datei-icon">${icon("lernplan", 18)}</span>
        <span class="zeile-text"><span class="zeile-titel">${f.name.replace(".pdf", "").replaceAll("_", " ")}</span>
        <span class="klein">${f.seiten ? `${f.seiten} Seiten` : f.groesse} · ${datumKurz(f.datum)}</span></span></li>`).join("")}</ul>`;
  }

  return `
    <div class="tab-inhalt">
      <div class="skill-kopf">
        <div>
          <h2>${icon(s.icon, 22)} ${s.name}</h2>
          <p class="klein">${s.nutzt}</p>
        </div>
        <button class="knopf-hell" data-aktion="skill-entfernen" data-skill="${s.id}" data-modul="${m.id}">Tab entfernen</button>
      </div>
      ${inhalt}
    </div>`;
}

// ---------- 6i) Platzhalter & Hinweise ----------

function hinweisKeineDaten(m) {
  return `
    <div class="platzhalter glas">
      <div class="platzhalter-icon">${icon("uebersicht", 28)}</div>
      <h2>${m.name}</h2>
      ${LIVE.aktiv ? `<p>Für diesen Kurs gibt es noch keine Unterlagen. Sie erscheinen nach dem nächsten Abgleich mit ILIAS.</p>`
        : `<p>Für die Demo ist nur Finanzmathematik ausgearbeitet.</p>
      <a class="knopf-hell" href="#/modul/fima/uebersicht">Finanzmathematik öffnen</a>`}
    </div>`;
}

function seiteNichtGefunden() {
  return `
    <div class="platzhalter glas">
      <h2>Seite nicht gefunden</h2>
      <a class="knopf-hell" href="#/">Zur Startseite</a>
    </div>`;
}

// Welche Funktion zeichnet welchen Tab?
const TAB_INHALT = {
  uebersicht: tabUebersicht,
  dokumente: tabDokumente,
  lernplan: tabLernplan,
  zusammenfassung: tabZusammenfassung,
  karteikarten: tabKarteikarten,
  sprachtutor: tabSprachtutor,
  "skill-hinzufuegen": tabSkillHinzufuegen,
};

// ---------- 7) Router & Klicks ----------

function aktuelleRoute() {
  const teile = (location.hash || "#/").replace(/^#\/?/, "").split("/");
  if (teile[0] === "modul") return { modul: teile[1], tab: teile[2] || "uebersicht" };
  if (["kurse", "einstellungen", "einrichtung", "bibliotheken"].includes(teile[0])) return { modul: null, seite: teile[0] };
  return { modul: null, seite: "start" };
}

// Liest die URL und zeichnet die passende Seite
function route() {
  if (LIVE.wartet()) { // mit Token nie Beispieldaten zeigen (live.js)
    $("#inhalt").innerHTML = `<div class="seite">${LIVE.wartenSeite()}</div>`;
    $("#sidebar").innerHTML = "";
    return;
  }
  const r = aktuelleRoute();
  const html = r.modul ? seiteModul(r.modul, r.tab)
    : r.seite === "kurse" ? EINSTELLUNGEN.seiteKurse()
      : r.seite === "einstellungen" ? EINSTELLUNGEN.seiteEinstellungen()
        : r.seite === "einrichtung" ? EINSTELLUNGEN.seiteEinrichtung()
        : r.seite === "bibliotheken" ? seiteBibliotheken()
        : seiteStart();
  $("#inhalt").innerHTML = `<div class="seite ${zustand.animieren ? "einblenden" : ""}">${html}</div>`;
  zustand.animieren = false;
  renderSidebar(r.modul, r.seite);

  // Auf schmalen Bildschirmen den aktiven Tab in der Tabbar sichtbar machen
  const tabbarEl = document.querySelector(".tabbar");
  const aktiv = document.querySelector('.tab[aria-selected="true"]');
  if (tabbarEl && aktiv) tabbarEl.scrollLeft = aktiv.offsetLeft - tabbarEl.clientWidth / 2 + aktiv.offsetWidth / 2;
}

// Neu zeichnen und den Fokus auf denselben Knopf zurücksetzen (für Tastatur-Nutzung)
function neuZeichnen(fokusErsatz) {
  const fokus = document.activeElement?.getAttribute("data-fokus");
  route();
  const ziel = (fokus && document.querySelector(`[data-fokus="${fokus}"]`))
    || (fokusErsatz && document.querySelector(`[data-fokus="${fokusErsatz}"]`));
  ziel?.focus({ preventScroll: true });
}

window.addEventListener("hashchange", () => {
  zustand.animieren = true;
  // Gespräch des Sprachtutors abbrechen, wenn man den Tab verlässt
  if (aktuelleRoute().tab !== "sprachtutor") {
    if (zustand.tutor.phase !== "start") tutorZuruecksetzen();
    if (LIVE.aktiv) LIVE.tutorStopp();
  }
  route();
  sidebarMobil(false);
  window.scrollTo({ top: 0 });
  $("#inhalt").focus({ preventScroll: true }); // Screenreader landen auf dem neuen Inhalt
});

// Ein zentraler Klick-Handler für alle Elemente mit data-aktion="…"
document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-aktion]");
  if (!el) return;
  const ds = el.dataset;

  switch (ds.aktion) {
    case "semester-umschalten":
      zustand.offeneSemester.has(ds.id) ? zustand.offeneSemester.delete(ds.id) : zustand.offeneSemester.add(ds.id);
      neuZeichnen();
      break;

    case "modul-hinzufuegen":
      // Mit laufender App: Kurse werden auf der Seite „Kurse“ ausgewählt
      if (LIVE.aktiv) location.hash = "#/kurse";
      else zeigeToast("ILIAS-Import kommt mit dem Onboarding-Screen");
      break;

    // --- Lernplan ---
    case "status-weiter": {
      const e = findeEintrag(ds.modul, ds.id);
      const pos = STATUS_REIHENFOLGE.indexOf(e.status);
      setzeStatus(ds.modul, ds.id, STATUS_REIHENFOLGE[(pos + 1) % STATUS_REIHENFOLGE.length]);
      neuZeichnen();
      break;
    }
    case "abhaken": {
      const e = findeEintrag(ds.modul, ds.id);
      setzeStatus(ds.modul, ds.id, e.status === "erledigt" ? "offen" : "erledigt");
      neuZeichnen();
      break;
    }
    case "ausgeblendet-umschalten":
      zustand.ausgeblendetOffen.has(ds.modul) ? zustand.ausgeblendetOffen.delete(ds.modul) : zustand.ausgeblendetOffen.add(ds.modul);
      neuZeichnen();
      break;
    case "lernplan-filter":
      zustand.lernplanFilter = ds.wert;
      neuZeichnen();
      break;
    case "bereich-umschalten":
      zustand.offeneBereiche.has(ds.id) ? zustand.offeneBereiche.delete(ds.id) : zustand.offeneBereiche.add(ds.id);
      neuZeichnen();
      break;
    case "notiz-umschalten":
      zustand.offeneNotizen.has(ds.id) ? zustand.offeneNotizen.delete(ds.id) : zustand.offeneNotizen.add(ds.id);
      neuZeichnen();
      if (zustand.offeneNotizen.has(ds.id)) document.querySelector(`[data-notiz="${ds.id}"]`)?.focus();
      break;

    // --- Dokumente ---
    case "dokument-oeffnen":
      zeigeToast(`${ds.name} wird geöffnet …`);
      break;

    // --- Zusammenfassung ---
    case "thema-waehlen":
      zustand.thema[ds.modul] = Number(ds.nr);
      if (el.tagName === "BUTTON") neuZeichnen();
      break;
    case "einfacher-erklaeren":
      if (zustand.einfach.has(ds.schluessel)) {
        zustand.einfach.delete(ds.schluessel);
        neuZeichnen();
      } else {
        zustand.einfach.add(ds.schluessel);
        zustand.zfLaedt = "einfach"; // kurz „denken“ lassen
        neuZeichnen();
        setTimeout(() => { zustand.zfLaedt = null; neuZeichnen(); }, 1100);
      }
      break;
    case "vorlesen-thema": {
      const t = MODUL_DETAILS[ds.modul].themen.find((x) => x.nr === Number(ds.nr));
      const einfach = zustand.einfach.has(`${ds.modul}-${t.nr}`);
      vorlesen(`${t.titel}. ${einfach ? t.einfacher : t.kernidee} Typische Klausurfalle: ${t.falle}`);
      break;
    }
    case "karten-erstellen": {
      zustand.zfLaedt = "karten";
      neuZeichnen();
      const anzahl = MODUL_DETAILS[ds.modul].karten.liste.filter((k) => k.thema === Number(ds.nr)).length;
      setTimeout(() => {
        zustand.zfLaedt = null;
        neueRunde(ds.modul, ds.nr, true);
        zeigeToast(`${anzahl} Karten zu Thema ${ds.nr} erstellt`);
        location.hash = `#/modul/${ds.modul}/karteikarten`;
      }, 1500);
      break;
    }

    // --- Karteikarten ---
    case "karten-filter":
      neueRunde(zustand.karten.modul, ds.wert, true);
      neuZeichnen();
      break;
    case "karte-aufdecken":
      zustand.karten.aufgedeckt = true;
      neuZeichnen("bew-gewusst");
      break;
    case "karte-bewerten":
      karteBewerten(ds.wert);
      break;
    case "karte-vorlesen": {
      const k = zustand.karten;
      const karte = k.stapel[k.index];
      const formel = karte.formel ? `${nurText(formelAusdruck(karte.formel))}. ` : "";
      vorlesen(nurText(k.aufgedeckt ? `${formel}${karte.antwort}` : karte.frage));
      break;
    }
    case "karten-alle-ueben":
      neueRunde(zustand.karten.modul, zustand.karten.filter, true, true);
      neuZeichnen();
      break;
    case "karten-neue-runde": {
      const modul = zustand.karten.modul;
      zustand.karten = null;
      neueRunde(modul);
      zustand.karten.gewusst = 0;
      zustand.karten.nochmal = 0;
      neuZeichnen();
      break;
    }
    case "karte-melden":
      zeigeToast("Danke! Die Karte wird geprüft.");
      break;

    // --- Sprachtutor ---
    case "tutor-start":
      tutorStart();
      break;
    case "tutor-mikro":
      if (zustand.tutor.phase === "deinZug") tutorAntworten();
      break;
    case "tutor-ton":
      zustand.tutor.ton = !zustand.tutor.ton;
      if (!zustand.tutor.ton && "speechSynthesis" in window) speechSynthesis.cancel();
      neuZeichnen();
      break;
    case "tutor-zuruecksetzen":
      tutorZuruecksetzen();
      if (el.tagName === "BUTTON") neuZeichnen();
      break;

    // --- Skills ---
    case "skill-hinzufuegen":
    case "skill-entfernen": {
      const skill = SKILL_KATALOG.find((s) => s.id === ds.skill);
      const bisher = zustand.skills[ds.modul] || [];
      const neu = ds.aktion === "skill-hinzufuegen" ? [...bisher, ds.skill] : bisher.filter((id) => id !== ds.skill);
      // Echte Kurse: auf dem Mac merken (sonst wären die Tabs nach einem Neustart weg)
      const gespeichert = MODUL_DETAILS[ds.modul]?.live ? LIVE.skillsSpeichern(ds.modul, neu) : Promise.resolve(true);
      gespeichert.then((ok) => {
        if (!ok) return;
        zustand.skills[ds.modul] = neu;
        if (ds.aktion === "skill-hinzufuegen") {
          zeigeToast(`${skill.name} hinzugefügt`);
          location.hash = `#/modul/${ds.modul}/skill-${ds.skill}`;
        } else {
          zeigeToast(`${skill.name} entfernt`);
          location.hash = `#/modul/${ds.modul}/skill-hinzufuegen`;
        }
      });
      break;
    }
    case "vorschau-umschalten":
      zustand.vorschauOhneZusammenfassung = !zustand.vorschauOhneZusammenfassung;
      neuZeichnen();
      break;

    // Alles, was mit der echten App spricht, steht in live.js
    default:
      if (ds.aktion.startsWith("live-")) LIVE.klick(ds);
      else if (ds.aktion.startsWith("bib-")) bibliothekenKlick(ds);
  }
});

// Notizen direkt beim Tippen speichern (ohne neu zu zeichnen, sonst springt der Cursor)
document.addEventListener("input", (event) => {
  const feld = event.target.closest("[data-notiz]");
  if (!feld) return;
  const eintrag = findeEintrag(feld.dataset.modul, feld.dataset.notiz);
  eintrag.notiz = esc(feld.value); // maskiert, weil die Notiz beim Neuzeichnen als HTML eingesetzt wird
  LIVE.eintragGeaendert(eintrag, true);
  document.querySelector(`[data-fokus="notiz-${feld.dataset.notiz}"]`)?.classList.toggle("hat-notiz", feld.value.trim() !== "");
});

// "Synchronisieren": mit laufender App echt, sonst nur simuliert (Beispieldaten und Demo-Modus)
$("#sync-knopf").addEventListener("click", () => {
  if (LIVE.aktiv && !LIVE.sync.demo) {
    LIVE.synchronisieren();
    return;
  }
  if (LIVE.wartet()) {
    zeigeToast("Noch keine Verbindung zur App");
    return;
  }
  const knopf = $("#sync-knopf");
  const status = $("#sync-status");
  knopf.disabled = true;
  knopf.classList.add("laedt");
  status.classList.add("laedt");
  $("#sync-text").textContent = "Synchronisiere mit ILIAS …";

  setTimeout(() => {
    knopf.disabled = false;
    knopf.classList.remove("laedt");
    status.classList.remove("laedt");
    $("#sync-text").textContent = "ILIAS verbunden · Sync gerade eben";
    zeigeToast("Alles aktuell · 3 neue Dateien in Finanzmathematik");
  }, 1800);
});

// "Claude": neuer Chat in Claude Desktop, der über den MCP-Server als Lerncoach arbeitet
$("#claude-knopf").addEventListener("click", () => {
  if (!LIVE.aktiv) {
    zeigeToast("Claude öffnet sich nur aus der laufenden App");
    return;
  }
  LIVE.claudeOeffnen(aktuelleRoute().modul);
});

// Register auf dem Handy ein-/ausklappen
function sidebarMobil(offen) {
  $("#sidebar").classList.toggle("offen", offen);
  $("#menue-knopf").setAttribute("aria-expanded", String(offen));
}
$("#menue-knopf").addEventListener("click", () => {
  sidebarMobil(!$("#sidebar").classList.contains("offen"));
});

// Tastatur: ⌘K = Suche; auf den Karteikarten Leertaste = umdrehen, 1/2/3 = bewerten
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    $("#suche").focus();
    return;
  }

  const r = aktuelleRoute();
  const k = zustand.karten;
  if (r.tab !== "karteikarten" || !k || k.index >= k.stapel.length) return;
  if (event.target.closest("input, textarea, [contenteditable]")) return;
  const aufKnopf = event.target.closest("button, a"); // dort löst die Leertaste schon selbst einen Klick aus

  if (event.key === " " && !k.aufgedeckt && !aufKnopf) {
    event.preventDefault();
    k.aufgedeckt = true;
    neuZeichnen();
  } else if (k.aufgedeckt && ["1", "2", "3"].includes(event.key)) {
    karteBewerten({ 1: "nochmal", 2: "schwer", 3: "gewusst" }[event.key]);
  }
});

// Start: ohne Token sofort die Beispieldaten zeichnen; mit Token erst „Lädt …“, dann die echten Daten
iconsEinsetzen();
route();
LIVE.start();
