// =====================================================
// StudyHub – Seite „Bibliotheken“: Auslastung der UB Mannheim
//
// Daten: GET /api/libraries (server/libraries.py). Die App misst selbst die öffentliche Seite
// „Freie Sitzplätze“ der UB und sammelt daraus einen Verlauf je Wochentag und Stunde
// (wie die Stoßzeiten bei Google Maps). Der Verlauf beginnt mit der ersten Messung.
// Jetzt messen: POST /api/libraries/refresh; Hintergrund an/aus: PATCH /api/libraries/background.
// Telegram-Bot: verbinden über POST /api/telegram/connect (Token, Chat-ID optional), Meldungen
// „voll / wieder Platz“ über PATCH /api/libraries/alerts, Stand senden über POST /api/libraries/telegram.
// Token und Chat-ID gehen nur an den lokalen Server (Schlüsselbund) und werden nie angezeigt.
// =====================================================

const BIBLIOTHEKEN = {
  daten: null, // Antwort von /api/libraries
  laedt: false,
  fehler: "",
  tag: null, // gewählter Wochentag im Verlauf (0 = Montag); null = heute
  tgBusy: "", // "verbinden" | "senden" während einer Telegram-Aktion
};

const STUFE_TEXT = { gering: "Geringe Auslastung", mittel: "Mittlere Auslastung", hoch: "Hohe Auslastung", unbekannt: "Auslastung" };
const VERLAUF_VON = 7; // Stunden im Diagramm (die Bereiche haben unterschiedliche Öffnungszeiten)
const VERLAUF_BIS = 23;

async function bibliothekenLaden(messen = false) {
  BIBLIOTHEKEN.laedt = true;
  try {
    let d = messen ? await api("/api/libraries/refresh", { method: "POST" }) : await api("/api/libraries");
    // Noch nie gemessen (frisch installiert): gleich einmal messen
    if (!messen && !d.stand) d = await api("/api/libraries/refresh", { method: "POST" });
    BIBLIOTHEKEN.daten = d;
    BIBLIOTHEKEN.fehler = "";
  } catch (fehler) {
    BIBLIOTHEKEN.fehler = fehler.message;
  } finally {
    BIBLIOTHEKEN.laedt = false;
    if (aktuelleRoute().seite === "bibliotheken") route();
  }
}

const uhrzeit = (ts) => new Date(ts * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
const datum = (ts) => new Date(ts * 1000).toLocaleDateString("de-DE", { day: "numeric", month: "long" });

function bibliothekVerlauf(b, d, tag) {
  const stunden = b.woche[tag].slice(VERLAUF_VON, VERLAUF_BIS + 1);
  const heute = tag === d.jetzt.wochentag;
  if (!stunden.some((s) => s.mittel != null)) {
    return `<p class="klein bib-leer">Für ${d.wochentage[tag]} gibt es noch zu wenige Messungen. Der Verlauf füllt sich mit jeder Messung.</p>`;
  }
  const saeulen = stunden.map((s) => {
    const jetzt = heute && s.stunde === d.jetzt.stunde;
    const titel = s.mittel == null ? `${d.wochentage[tag]} ${s.stunde}–${s.stunde + 1} Uhr: noch keine Daten`
      : `${d.wochentage[tag]} ${s.stunde}–${s.stunde + 1} Uhr: im Schnitt ${s.mittel} % belegt (${s.messungen} Messungen)`;
    return `
      <div class="bib-saeule ${jetzt ? "jetzt" : ""}" title="${titel}" role="img" aria-label="${titel}">
        ${s.mittel == null ? `<span class="bib-balken leer"></span>` : `<span class="bib-balken" style="height:${Math.max(4, s.mittel)}%"></span>`}
        ${jetzt && b.aktuell ? `<span class="bib-live" style="bottom:${b.aktuell.prozent}%" title="Jetzt: ${b.aktuell.prozent} %"></span>` : ""}
      </div>`;
  }).join("");
  const achse = stunden.map((s) => `<span>${s.stunde % 3 === 0 ? `${s.stunde}` : ""}</span>`).join("");
  return `
    <div class="bib-diagramm" aria-label="Typische Auslastung am ${d.wochentage[tag]}">${saeulen}</div>
    <div class="bib-achse" aria-hidden="true">${achse}</div>`;
}

function bibliothekKarte(b, d, tag) {
  const a = b.offen ? b.aktuell : null; // geschlossen: letzter Wert der UB sagt nichts über jetzt
  let vergleich = "";
  if (a && b.typischJetzt != null) {
    const diff = a.prozent - b.typischJetzt;
    vergleich = Math.abs(diff) < 8 ? `So voll wie üblich um diese Zeit (Ø ${b.typischJetzt} %)`
      : diff > 0 ? `Voller als üblich um diese Zeit (Ø ${b.typischJetzt} %)` : `Leerer als üblich um diese Zeit (Ø ${b.typischJetzt} %)`;
  }
  return `
    <article class="bib-karte glas">
      <header class="bib-kopf">
        <div>
          <h2><a href="${esc(b.url)}" target="_blank" rel="noreferrer">${esc(b.name)}</a></h2>
          <p class="klein bib-info">${esc(b.info)}</p>
          ${b.zeiten && !/öffnungszeit/i.test(b.info) ? `<p class="klein bib-zeiten">${icon("kalender", 13)} ${esc(b.zeiten)}</p>` : ""}
        </div>
        ${a ? `<div class="bib-wert"><span class="zahl-gross">${a.prozent}&nbsp;%</span><span class="klein">belegt</span></div>` : ""}
      </header>
      ${a ? `
        <p class="bib-status">
          <span class="ampel-punkt bib-stufe-${a.stufe}" aria-hidden="true"></span>
          <span><b>${STUFE_TEXT[a.stufe] || STUFE_TEXT.unbekannt}</b> · ca. ${a.frei} von ${a.plaetze} Plätzen frei</span>
        </p>` : !b.offen ? `
        <p class="bib-status bib-zu">
          <span class="ampel-punkt bib-stufe-zu" aria-hidden="true"></span>
          <span><b>Geschlossen</b>${b.oeffnet ? ` · öffnet ${esc(b.oeffnet)}` : ""}</span>
        </p>` : `<p class="klein">Zurzeit keine Angabe der UB.</p>`}
      ${vergleich ? `<p class="klein">${vergleich}</p>` : ""}
      <h3 class="mini-titel">Typische Auslastung · ${d.wochentage[tag]}</h3>
      ${bibliothekVerlauf(b, d, tag)}
    </article>`;
}

const SCHWELLEN = [80, 85, 90, 95, 100];

// Telegram: Einrichtung (Token, Chat-ID) oder, wenn verbunden, /bib und Meldungen „voll / wieder Platz“
function bibliothekTelegram(d) {
  const t = d.telegram;
  if (!t) return "";
  const kopf = (rechts = "") => `
    <header class="bib-tg-kopf">
      <div class="bib-tg-titel">
        <span class="bib-tg-symbol" aria-hidden="true">${icon("senden", 18)}</span>
        <div><h2>Telegram-Bot</h2>
          <p class="klein">Auslastung unterwegs abfragen und Bescheid bekommen, wenn eine Bibliothek voll ist oder wieder Platz hat.</p></div>
      </div>
      ${rechts}
    </header>`;

  if (d.demo) {
    return `<section class="bib-tg glas">${kopf()}<p class="klein">In der Demo-Version ausgeschaltet. In StudyHub.app lässt sich hier ein eigener Bot verbinden.</p></section>`;
  }

  if (!t.verbunden) {
    const wartet = BIBLIOTHEKEN.tgBusy === "verbinden";
    return `
      <section class="bib-tg glas">
        ${kopf()}
        <ol class="bib-tg-schritte">
          <li>In Telegram <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a> öffnen,
            <code>/newbot</code> schicken und einen Namen wählen.</li>
          <li>Den <b>Token</b>, den BotFather zurückschickt, unten einfügen.</li>
          <li><b>Chat-ID</b> leer lassen und auf „Verbinden“ klicken: Telegram öffnet sich, schick deinem Bot
            eine beliebige Nachricht, die App erkennt deinen Chat. Wer seine Chat-ID kennt, trägt sie ein
            (vorher dem Bot <code>/start</code> schicken).</li>
        </ol>
        <form class="bib-tg-form" data-form="bib-telegram">
          <input class="tutor-feld" name="token" type="password" autocomplete="off" required ${wartet ? "disabled" : ""}
            placeholder="Bot-Token, z. B. 123456789:ABC…" aria-label="Telegram-Bot-Token">
          <input class="tutor-feld bib-tg-chat" name="chat" inputmode="numeric" autocomplete="off" ${wartet ? "disabled" : ""}
            placeholder="Chat-ID (optional)" aria-label="Telegram-Chat-ID, optional">
          <button class="knopf-hell" ${wartet ? "disabled" : ""}>${wartet ? "Warte auf deine Nachricht an den Bot …" : "Verbinden"}</button>
        </form>
        <p class="klein">Token und Chat-ID landen nur im Schlüsselbund dieses Macs. Derselbe Bot schickt auch neue
          ILIAS-Dateien, Zusammenfassungen und Lernkarten (Einstellungen › Weitergabe).</p>
      </section>`;
  }

  const a = t.alarm;
  const alle = d.bereiche.map((b) => b.slug);
  const gewaehlt = a.bereiche.length ? a.bereiche : alle;
  const bot = t.bot ? `<a href="https://t.me/${encodeURIComponent(t.bot)}" target="_blank" rel="noreferrer">@${esc(t.bot)}</a>` : "deinem Bot";
  const senden = BIBLIOTHEKEN.tgBusy === "senden";
  return `
    <section class="bib-tg glas">
      ${kopf(`<button class="knopf-hell" data-aktion="bib-tg-senden" ${senden ? "disabled" : ""}>${icon("senden", 16)} ${senden ? "Sendet …" : "Stand jetzt senden"}</button>`)}
      <p class="hinweis-chip bib-tg-verbunden">${icon("haken", 16)} <span>Verbunden mit ${bot}</span></p>
      <div class="bib-tg-befehle">
        <p><code>/bib</code> <span class="klein">alle Bereiche, sortiert nach Belegung</span></p>
        <p><code>/bib a3</code> <span class="klein">nur Bereiche mit „a3“ im Namen, auch <code>/bib ehrenhof</code></span></p>
      </div>
      <label class="bib-schalter">
        <input type="checkbox" id="bib-alarm" ${a.aktiv ? "checked" : ""}>
        <span><b>Melden, wenn eine Bibliothek voll ist und wenn dort wieder Platz ist</b><br>
        <span class="klein">„Wieder Platz“ kommt erst ${d.alarmAbstand ?? 5} Punkte unter der Schwelle, damit Schwankungen um die Grenze nicht ständig Nachrichten auslösen.</span></span>
      </label>
      ${a.aktiv ? `
        <div class="bib-tg-optionen">
          <label class="bib-tg-schwelle">Voll ab
            <select id="bib-schwelle" aria-label="Schwelle für voll">
              ${SCHWELLEN.map((w) => `<option value="${w}" ${w === a.schwelle ? "selected" : ""}>${w}&nbsp;%</option>`).join("")}
            </select>
          </label>
          <div class="einst-chips" role="group" aria-label="Bereiche für Meldungen">
            ${d.bereiche.map((b) => `<button class="chip chip-klein" data-aktion="bib-tg-bereich" data-slug="${esc(b.slug)}"
              aria-pressed="${gewaehlt.includes(b.slug)}">${esc(b.name)}</button>`).join("")}
          </div>
        </div>` : ""}
      <p class="klein">Der Bot antwortet und meldet, solange gemessen wird: App offen oder „Auch messen, wenn die App
        geschlossen ist“ an. Trennen unter <a href="#/einstellungen">Einstellungen › Weitergabe</a>.</p>
    </section>`;
}

function seiteBibliotheken() {
  const kopf = (unter = "") => `
    <header class="modul-kopf mit-aura">
      <div class="aura aura-klein" aria-hidden="true"></div>
      <div><p class="eyebrow">Universitätsbibliothek Mannheim</p><h1>Bibliotheken</h1>${unter}</div>
    </header>`;
  if (!LIVE.token) {
    return `${kopf()}<div class="platzhalter glas"><h2>Nur in der App</h2><p>Die Auslastung misst die laufende App. Öffne dazu StudyHub.app.</p></div>`;
  }
  const d = BIBLIOTHEKEN.daten;
  if (!d) {
    if (!BIBLIOTHEKEN.laedt && !BIBLIOTHEKEN.fehler) bibliothekenLaden();
    return BIBLIOTHEKEN.fehler
      ? `${kopf()}<div class="platzhalter glas"><h2>Konnte nicht geladen werden</h2><p>${esc(BIBLIOTHEKEN.fehler)}</p>
          <button class="knopf-hell" data-aktion="bib-messen">Nochmal versuchen</button></div>`
      : `${kopf()}<div class="schimmer"><span></span><span></span><span></span></div>`;
  }

  const tag = BIBLIOTHEKEN.tag ?? d.jetzt.wochentag;
  const alterText = (min) => (min < 120 ? `${min} Min.` : min < 2880 ? `${Math.round(min / 60)} Std.` : `${Math.round(min / 1440)} Tagen`);
  const offen = d.bereiche.filter((b) => b.aktuell && b.offen);
  const leerste = offen.filter((b) => b.aktuell.stufe !== "hoch").sort((x, y) => x.aktuell.prozent - y.aktuell.prozent)[0];
  const takt = d.taktMinuten ? ` · die UB aktualisiert etwa alle ${d.taktMinuten} Min.` : "";
  const unter = `<p class="klein">${d.stand ? `Stand ${uhrzeit(d.stand)} Uhr${d.alterMinuten > 1 ? ` (vor ${alterText(d.alterMinuten)})` : ""}` : "Noch keine Messung"}${takt}
    · <a href="${esc(d.quelle)}" target="_blank" rel="noreferrer">Quelle: UB Mannheim</a></p>`;

  const tage = d.wochentage.map((name, i) => `
    <button class="segment-knopf" data-aktion="bib-tag" data-tag="${i}" aria-pressed="${i === tag}">${name}${i === d.jetzt.wochentag ? " · heute" : ""}</button>`).join("");

  return `
    ${kopf(unter)}
    <div class="bib-leiste">
      ${leerste ? `<p class="hinweis-chip">${icon("haken", 16)} <span>Jetzt am leersten: <b>${esc(leerste.name)}</b> (${leerste.aktuell.prozent}&nbsp;%)</span></p>` : ""}
      <button class="knopf-hell" data-aktion="bib-messen" ${BIBLIOTHEKEN.laedt ? "disabled" : ""}>${icon("sync", 16)} ${BIBLIOTHEKEN.laedt ? "Misst …" : "Jetzt messen"}</button>
    </div>
    <div class="segment segment-scroll" role="group" aria-label="Wochentag für den Verlauf">${tage}</div>
    <div class="bib-raster">${d.bereiche.map((b) => bibliothekKarte(b, d, tag)).join("")}</div>
    ${bibliothekTelegram(d)}
    <section class="bib-fuss glas">
      ${d.demo ? `<p class="klein"><b>Demo-Version:</b> misst nicht selbst und nicht im Hintergrund.</p>` : `
      <label class="bib-schalter">
        <input type="checkbox" id="bib-hintergrund" ${d.hintergrund ? "checked" : ""}>
        <span><b>Auch messen, wenn die App geschlossen ist</b><br>
        <span class="klein">Alle ${d.intervallMinuten || 5} Minuten im Hintergrund. Ohne diese Option wächst der Verlauf nur, solange die App offen ist.</span></span>
      </label>`}
      <p class="klein">Verlauf ${d.seit ? `seit ${datum(d.seit)} · ${d.messungen} Messungen` : "beginnt mit der ersten Messung"}.
        Aussagekräftig wird er nach etwa zwei Wochen. Messungen außerhalb der Öffnungszeiten zählen nicht. Die Werte sind Schätzungen der UB aus der WLAN-Nutzung und
        Zählungen des Personals, keine exakten Platzzahlen.</p>
    </section>`;
}

// Klicks (data-aktion="bib-…") und der Hintergrund-Schalter
function bibliothekenKlick(ds) {
  if (ds.aktion === "bib-tag") {
    BIBLIOTHEKEN.tag = Number(ds.tag);
    route();
  } else if (ds.aktion === "bib-messen") {
    BIBLIOTHEKEN.fehler = "";
    bibliothekenLaden(true);
    route();
  } else if (ds.aktion === "bib-tg-senden") {
    telegramSenden();
  } else if (ds.aktion === "bib-tg-bereich") {
    // Leere Auswahl heißt „alle“; mindestens ein Bereich bleibt gewählt
    const alle = BIBLIOTHEKEN.daten.bereiche.map((b) => b.slug);
    const jetzt = new Set(BIBLIOTHEKEN.daten.telegram.alarm.bereiche.length ? BIBLIOTHEKEN.daten.telegram.alarm.bereiche : alle);
    jetzt.has(ds.slug) ? jetzt.delete(ds.slug) : jetzt.add(ds.slug);
    if (!jetzt.size) return zeigeToast("Mindestens ein Bereich bleibt ausgewählt");
    alarmSpeichern({ bereiche: jetzt.size === alle.length ? [] : [...jetzt] });
  }
}

async function alarmSpeichern(aenderung, meldung = "") {
  try {
    BIBLIOTHEKEN.daten.telegram = await api("/api/libraries/alerts", { method: "PATCH", body: aenderung });
    if (meldung) zeigeToast(meldung);
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
  route();
}

async function telegramSenden() {
  BIBLIOTHEKEN.tgBusy = "senden";
  route();
  try {
    await api("/api/libraries/telegram", { method: "POST" });
    zeigeToast("Stand an Telegram gesendet");
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
  BIBLIOTHEKEN.tgBusy = "";
  route();
}

// Telegram verbinden: ohne Chat-ID wartet der Server bis zu 5 Minuten auf eine Nachricht an den Bot
document.addEventListener("submit", async (e) => {
  const form = e.target.closest('[data-form="bib-telegram"]');
  if (!form) return;
  e.preventDefault();
  const token = form.elements.token.value.trim();
  const chat = form.elements.chat.value.trim();
  if (!token) return;
  BIBLIOTHEKEN.tgBusy = "verbinden";
  route();
  try {
    const r = await api("/api/telegram/connect", { method: "POST", body: { token, chat } });
    zeigeToast(`Verbunden mit @${r.bot} · schreib ihm /bib`);
    if (typeof EINSTELLUNGEN !== "undefined") EINSTELLUNGEN.settings = null; // Einstellungen neu laden
    BIBLIOTHEKEN.tgBusy = "";
    await bibliothekenLaden();
    return;
  } catch (fehler) {
    zeigeToast(fehler.message);
  }
  BIBLIOTHEKEN.tgBusy = "";
  route();
});

document.addEventListener("change", (e) => {
  if (e.target.id === "bib-alarm") {
    alarmSpeichern({ aktiv: e.target.checked }, e.target.checked ? "Meldungen an" : "Meldungen aus");
  } else if (e.target.id === "bib-schwelle") {
    alarmSpeichern({ schwelle: Number(e.target.value) }, `Voll ab ${e.target.value} %`);
  }
});

document.addEventListener("change", async (e) => {
  if (e.target.id !== "bib-hintergrund") return;
  try {
    const r = await api("/api/libraries/background", { method: "PATCH", body: { aktiv: e.target.checked } });
    BIBLIOTHEKEN.daten.hintergrund = r.aktiv;
    zeigeToast(r.aktiv ? "Misst jetzt auch im Hintergrund" : "Messung im Hintergrund aus");
  } catch (fehler) {
    e.target.checked = !e.target.checked;
    zeigeToast(fehler.message);
  }
});
