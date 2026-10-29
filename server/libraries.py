"""Auslastung der Bibliotheksbereiche der Universitätsbibliothek Mannheim.

Quelle: https://www.bib.uni-mannheim.de/standorte/freie-sitzplaetze/ (öffentliche Seite, keine API).
Je Bereich nennt sie Belegung in Prozent, Zahl der Arbeitsplätze und eine Ampel; dazu
„Stand: TT.MM.JJ, HH:MM Uhr“. Die UB berechnet die Werte aus der WLAN-Nutzung und Zählungen
des Personals; es sind Schätzwerte, keine exakten Platzzahlen.

Die App misst selbst (während sie läuft, auf Wunsch auch im Hintergrund über launchd) und
speichert jede neue Messung in bibliothek.sqlite3. Daraus entsteht der Verlauf je Wochentag und
Stunde, ähnlich den Stoßzeiten bei Google Maps. Eine Messung wird nur gespeichert, wenn die Seite
einen neuen Stand hat.

Telegram (eigener Bot, Einrichtung in StudyHub): /bib beantwortet die App mit dem aktuellen Stand;
auf Wunsch meldet sie, wenn ein Bereich voll wird und wenn dort wieder Platz ist (Schwelle mit
Abstand nach unten, damit Schwankungen um die Grenze nicht ständig Nachrichten auslösen).

Aufruf für den Hintergrund-Job:  .venv/bin/python server/libraries.py --sample
"""

import html
import os
import plistlib
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

if __name__ == "__main__":  # als Skript (launchd): Module wie in app.py finden
    sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "core"), str(Path(__file__).resolve().parent)]

import httpx2 as httpx  # kommt mit dem Anthropic-SDK, gleiche API wie httpx

import core
import telegram_bot

URL = "https://www.bib.uni-mannheim.de/standorte/freie-sitzplaetze/"
SITE = "https://www.bib.uni-mannheim.de"
DB_FILE = core.APP_DIR / "bibliothek.sqlite3"
USER_AGENT = "StudyHub/1.0 (Lern-App von Studierenden der Uni Mannheim)"
INTERVAL = 300  # Sekunden zwischen zwei Abrufen (die UB aktualisiert alle 5 Minuten)
LEVELS = {"ampel_gruen": "gering", "ampel_gelb": "mittel", "ampel_rot": "hoch"}
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MIN_SAMPLES = 2  # so viele Messungen braucht eine Stunde, bevor der Verlauf sie zeigt
ALERT_DEFAULT = {"aktiv": False, "schwelle": 90, "bereiche": []}  # bereiche leer = alle
ALERT_GAP = 5  # „wieder Platz“ erst unter Schwelle minus so viele Prozentpunkte
LEVEL_ICON = {"gering": "🟢", "mittel": "🟡", "hoch": "🔴"}

# Öffnungszeiten laut den Seiten der Bereiche (www.bib.uni-mannheim.de/standorte/<slug>/, Stand 27.10.2026):
# (Mo–Fr, Sa/So/Feiertage) als (von, bis) in vollen Stunden; None = geschlossen. Unbekannte Bereiche gelten
# als offen. Feiertage: gesetzliche in Baden-Württemberg (Annahme: so hält es die UB).
HOURS = {
    "ausleihzentrum-schloss-westfluegel": ((8, 18), None),
    "bb-a3": ((8, 23), (10, 23)),
    "bb-a5": ((8, 23), (10, 23)),
    "bb-schloss-ehrenhof": ((8, 23), (10, 23)),
    "bb-schloss-schneckenhof": ((8, 23), (10, 23)),
}

LABEL = "local.ilias-lerner.bibliothek"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
DOMAIN = f"gui/{os.getuid()}" if hasattr(os, "getuid") else ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (stand REAL NOT NULL, fetched REAL NOT NULL, slug TEXT NOT NULL,
                                    percent INTEGER NOT NULL, seats INTEGER NOT NULL, level TEXT NOT NULL,
                                    PRIMARY KEY (stand, slug));
CREATE TABLE IF NOT EXISTS libraries (slug TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
                                      info TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alert_state (slug TEXT PRIMARY KEY, full INTEGER NOT NULL);
"""


class LibraryError(Exception):
    pass


# --- Seite lesen ------------------------------------------------------------------


def _text(fragment: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xad", "")
    return re.sub(r"\s+", " ", text).strip()


def parse(page: str) -> dict:
    """Seite → {"stand": Zeitstempel (lokale Zeit) oder None, "bereiche": [{slug, name, url, info,
    percent, seats, level}]}. Wirft LibraryError, wenn die Seite nicht mehr so aussieht wie erwartet."""
    areas = []
    for row in re.findall(r"<tr>(.*?)</tr>", page, re.S):
        values = re.search(r'title="(\d+)\s*%\s*von\s*(\d+)\s*Arbeitspl', row)
        link = re.search(r'<h4>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', row, re.S)
        if not (values and link):
            continue
        level = re.search(r'data-identifier="(ampel_\w+)"', row)
        info = re.search(r"</h4>\s*<div>(.*?)</div>", row, re.S)
        href = link.group(1)
        areas.append({
            "slug": href.strip("/").rsplit("/", 1)[-1] or _text(link.group(2)),
            "name": _text(link.group(2)),
            "url": href if href.startswith("http") else SITE + href,
            "info": _text(info.group(1)) if info else "",
            "percent": min(100, int(values.group(1))),
            "seats": int(values.group(2)),
            "level": LEVELS.get(level.group(1) if level else "", "unbekannt"),
        })
    if not areas:
        raise LibraryError("Auf der Seite der UB wurden keine Bibliotheksbereiche gefunden (Aufbau geändert?)")
    stand = None
    if match := re.search(r"Stand:\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4}),\s*(\d{1,2}):(\d{2})", page):
        day, month, year, hour, minute = (int(x) for x in match.groups())
        year += 2000 if year < 100 else 0
        stand = time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))
    return {"stand": stand, "bereiche": areas}


def fetch() -> dict:
    try:
        response = httpx.get(URL, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise LibraryError(f"Seite der UB nicht erreichbar ({error.__class__.__name__})") from None
    return parse(response.text)


# --- Speichern ------------------------------------------------------------------


def connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def store(data: dict, fetched: float) -> bool:
    """Speichert eine Messung; False, wenn dieser Stand schon gespeichert ist."""
    stand = data["stand"] or fetched
    with closing(connect()) as db, db:
        if db.execute("SELECT 1 FROM samples WHERE stand = ? LIMIT 1", (stand,)).fetchone():
            return False
        for a in data["bereiche"]:
            db.execute("INSERT OR REPLACE INTO libraries VALUES (?, ?, ?, ?)",
                       (a["slug"], a["name"], a["url"], a["info"]))
            db.execute("INSERT OR IGNORE INTO samples VALUES (?, ?, ?, ?, ?, ?)",
                       (stand, fetched, a["slug"], a["percent"], a["seats"], a["level"]))
    return True


def sample(now: float | None = None) -> dict:
    """Abrufen und speichern; bei neuem Stand Voll/Frei-Meldungen prüfen. Liefert {"neu": bool, "stand": …}."""
    data = fetch()
    new = store(data, now or time.time())
    if new:
        try:
            send_alerts(data["bereiche"], data["stand"])
        except Exception as error:  # eine Meldung darf die Messung nie abbrechen
            core.log(f"Bibliotheken: Telegram-Meldung fehlgeschlagen ({type(error).__name__}: {error})")
    return {"neu": new, "stand": data["stand"]}


# --- Öffnungszeiten ------------------------------------------------------------------


def _easter(year: int) -> date:
    """Ostersonntag (gregorianisch, anonymer Algorithmus nach Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    weekday = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday) // 451
    n = h + weekday - 7 * m + 114
    return date(year, n // 31, n % 31 + 1)


def holidays(year: int) -> set[date]:
    """Gesetzliche Feiertage in Baden-Württemberg."""
    easter = _easter(year)
    fixed = {date(year, m, d) for m, d in ((1, 1), (1, 6), (5, 1), (10, 3), (11, 1), (12, 25), (12, 26))}
    return fixed | {easter + timedelta(days=n) for n in (-2, 1, 39, 50, 60)}


def _hours(slug: str, ts: float) -> tuple[int, int] | None | bool:
    """Öffnungszeit am Tag von ts; True, wenn für den Bereich nichts bekannt ist."""
    if slug not in HOURS:
        return True
    t = time.localtime(ts)
    free_day = t.tm_wday >= 5 or date(t.tm_year, t.tm_mon, t.tm_mday) in holidays(t.tm_year)
    return HOURS[slug][1 if free_day else 0]


def is_open(slug: str, ts: float) -> bool:
    hours = _hours(slug, ts)
    if hours is True:
        return True
    t = time.localtime(ts)
    return bool(hours) and hours[0] <= t.tm_hour + t.tm_min / 60 < hours[1]


def opens_at(slug: str, ts: float) -> str:
    """Nächste Öffnung als Text, z. B. „heute 10 Uhr“, „morgen 8 Uhr“, „Mo 8 Uhr“."""
    day = date.fromtimestamp(ts)
    for n in range(8):
        noon = time.mktime((day + timedelta(days=n)).timetuple()) + 12 * 3600
        hours = _hours(slug, noon)
        if hours is True:
            return ""
        if hours and (n or time.localtime(ts).tm_hour < hours[0]):
            when = "heute" if n == 0 else "morgen" if n == 1 else WEEKDAYS[(day + timedelta(days=n)).weekday()]
            return f"{when} {hours[0]} Uhr"
    return ""


def hours_text(slug: str) -> str:
    if slug not in HOURS:
        return ""
    week, free = HOURS[slug]
    return (f"Mo–Fr {week[0]}–{week[1]} Uhr · "
            + (f"Sa, So, Feiertage {free[0]}–{free[1]} Uhr" if free else "Sa, So, Feiertage geschlossen"))


# --- Auswerten ------------------------------------------------------------------


def _hour_key(ts: float) -> tuple[int, int]:
    t = time.localtime(ts)
    return t.tm_wday, t.tm_hour


def overview(now: float | None = None) -> dict:
    """Aktueller Stand je Bereich und Verlauf (Mittel je Wochentag und Stunde) für StudyHub."""
    now = now or time.time()
    with closing(connect()) as db:
        latest = db.execute("SELECT MAX(stand) FROM samples").fetchone()[0]
        libraries = {r["slug"]: dict(r) for r in db.execute("SELECT * FROM libraries")}
        current = {r["slug"]: dict(r) for r in db.execute("SELECT * FROM samples WHERE stand = ?", (latest,))}
        rows = db.execute("SELECT stand, slug, percent FROM samples").fetchall()
        first = db.execute("SELECT MIN(stand), COUNT(DISTINCT stand) FROM samples").fetchone()
        stands = [r[0] for r in db.execute("SELECT DISTINCT stand FROM samples ORDER BY stand DESC LIMIT 50")]

    sums: dict[tuple, list[int]] = {}
    for r in rows:
        if is_open(r["slug"], r["stand"]):  # Werte bei geschlossenem Bereich verfälschen den Verlauf
            sums.setdefault((r["slug"], *_hour_key(r["stand"])), []).append(r["percent"])
    weekday, hour = _hour_key(now)
    areas = []
    for slug, lib in sorted(libraries.items(), key=lambda kv: kv[1]["name"].casefold()):
        week = []
        for day in range(7):
            hours = []
            for h in range(24):
                values = sums.get((slug, day, h), [])
                hours.append({"stunde": h, "mittel": round(sum(values) / len(values)) if len(values) >= MIN_SAMPLES
                              else None, "messungen": len(values)})
            week.append(hours)
        now_row = current.get(slug)
        offen = is_open(slug, now)
        areas.append({
            **lib, "aktuell": now_row and {"prozent": now_row["percent"], "plaetze": now_row["seats"],
                                           "frei": round(now_row["seats"] * (100 - now_row["percent"]) / 100),
                                           "stufe": now_row["level"]},
            "offen": offen, "oeffnet": "" if offen else opens_at(slug, now), "zeiten": hours_text(slug),
            "typischJetzt": week[weekday][hour]["mittel"] if offen else None, "woche": week,
        })
    # Häufigster Abstand zwischen zwei neuen Ständen (Pausen über eine Stunde, z. B. nachts oder bei
    # geschlossener App, zählen nicht): so oft aktualisiert die UB tatsächlich
    gaps = [round((a - b) / 60) for a, b in zip(stands, stands[1:], strict=False) if 0 < a - b <= 3600]
    takt = min(set(gaps), key=lambda g: (-gaps.count(g), g)) if gaps else None
    return {
        "stand": latest, "alterMinuten": round((now - latest) / 60) if latest else None,
        "seit": first[0], "messungen": first[1], "taktMinuten": takt,
        "jetzt": {"wochentag": weekday, "stunde": hour}, "wochentage": WEEKDAYS,
        "bereiche": areas, "hintergrund": background_active(), "quelle": URL,
        "intervallMinuten": INTERVAL // 60, "alarmAbstand": ALERT_GAP, "telegram": telegram_status(),
    }


# --- Telegram: /bib und Voll/Frei-Meldungen ------------------------------------------


def short_name(name: str) -> str:
    """Für Telegram: „Bibliotheksbereich A5“ → „A5“ (auf dem Handy zählt jede Zeile)."""
    return html.escape(name.removeprefix("Bibliotheksbereich "))


def alert_settings() -> dict:
    return {**ALERT_DEFAULT, **core.load_config().get("bib_alarm", {})}


def save_alert_settings(aktiv: bool | None = None, schwelle: int | None = None,
                        bereiche: list[str] | None = None) -> dict:
    """Ändert die Meldungs-Einstellungen. Neue Schwelle oder Auswahl: Zustand neu erfassen, damit
    die erste Messung danach keine Meldung für einen längst vollen Bereich auslöst."""
    config = core.load_config()
    settings = {**ALERT_DEFAULT, **config.get("bib_alarm", {})}
    changed = False
    if aktiv is not None:
        changed |= aktiv and not settings["aktiv"]
        settings["aktiv"] = aktiv
    if schwelle is not None:
        changed |= schwelle != settings["schwelle"]
        settings["schwelle"] = schwelle
    if bereiche is not None:
        changed |= sorted(bereiche) != sorted(settings["bereiche"])
        settings["bereiche"] = sorted(set(bereiche))
    config["bib_alarm"] = settings
    core.save_config(config)
    if changed:
        with closing(connect()) as db, db:
            db.execute("DELETE FROM alert_state")
    return settings


def telegram_status() -> dict:
    config = core.load_config()
    return {"verbunden": bool(config["telegram"]), "bot": config.get("telegram_bot", ""), "alarm": alert_settings()}


def alerts(areas: list[dict], now: float | None = None) -> list[str]:
    """Vergleicht die neue Messung mit dem gespeicherten Zustand (voll/nicht voll) und liefert die
    Meldungen (Telegram-HTML). Voll ab der Schwelle, wieder Platz erst ALERT_GAP Punkte darunter.
    Geschlossene Bereiche melden nichts."""
    now = now or time.time()
    settings = alert_settings()
    if not settings["aktiv"]:
        return []
    limit, chosen = settings["schwelle"], set(settings["bereiche"])
    messages = []
    with closing(connect()) as db, db:
        state = {r["slug"]: bool(r["full"]) for r in db.execute("SELECT * FROM alert_state")}
        for a in areas:
            if chosen and a["slug"] not in chosen:
                continue
            if not is_open(a["slug"], now):  # nach dem Öffnen neu erfassen, keine Meldung um 8 Uhr
                db.execute("DELETE FROM alert_state WHERE slug = ?", (a["slug"],))
                continue
            was = state.get(a["slug"])
            full = a["percent"] >= limit if was is not True else a["percent"] >= limit - ALERT_GAP
            if was is not None and full != was:
                name = short_name(a["name"])
                free = round(a["seats"] * (100 - a["percent"]) / 100)
                messages.append(f"🔴 <b>{name}</b> ist voll: {a['percent']} % belegt" if full else
                                f"🟢 <b>{name}</b> hat wieder Platz: {a['percent']} % belegt, ca. {free} frei")
            db.execute("INSERT OR REPLACE INTO alert_state VALUES (?, ?)", (a["slug"], int(full)))
    return messages


def send_alerts(areas: list[dict], stand: float | None = None) -> None:
    if not core.load_config()["telegram"]:
        return
    if messages := alerts(areas, stand):
        telegram_bot.send("\n".join(messages) + "\n\n/bib für alle Bereiche")


def status_text(query: str = "", now: float | None = None) -> str:
    """Antwort auf /bib (Telegram-HTML): Stand aller Bereiche oder der Bereiche, deren Name query enthält."""
    data = overview(now)
    if not data["stand"]:
        return "Noch keine Messung. Die App misst, sobald sie läuft."
    areas = [b for b in data["bereiche"] if b["aktuell"] or not b["offen"]]
    if query:
        wanted = query.casefold().replace(" ", "")
        hits = [b for b in areas if wanted in b["name"].casefold().replace(" ", "") or wanted in b["slug"]]
        if not hits:
            names = ", ".join(short_name(b["name"]) for b in areas)
            return f"Keinen Bereich „{html.escape(query)}“ gefunden. Es gibt: {names}"
        areas = hits
    stand = time.strftime("%H:%M", time.localtime(data["stand"]))
    old = f" (vor {data['alterMinuten']} Min.)" if data["alterMinuten"] and data["alterMinuten"] > 15 else ""
    lines = [f"📚 <b>Bibliotheken der UB</b> · Stand {stand} Uhr{old}"]
    open_areas = [b for b in areas if b["offen"] and b["aktuell"]]
    for b in sorted(open_areas, key=lambda b: b["aktuell"]["prozent"]):
        a = b["aktuell"]
        typical = f" · üblich {b['typischJetzt']} %" if b["typischJetzt"] is not None else ""
        lines.append(f"{LEVEL_ICON.get(a['stufe'], '⚪')} <b>{short_name(b['name'])}</b>: {a['prozent']} %, "
                     f"ca. {a['frei']} von {a['plaetze']} frei{typical}")
    for b in areas:
        if not b["offen"]:
            lines.append(f"⚫ <b>{short_name(b['name'])}</b>: geschlossen"
                         + (f", öffnet {b['oeffnet']}" if b["oeffnet"] else ""))
    best = min(open_areas, key=lambda b: b["aktuell"]["prozent"], default=None)
    if len(open_areas) > 1 and best["aktuell"]["stufe"] != "hoch":
        lines.append(f"\nAm leersten: {short_name(best['name'])}")
    return "\n".join(lines)


_last_fetch = 0.0


def answer_bib(query: str = "") -> str:
    """/bib: vorher neu messen, wenn der letzte Stand älter als ein Takt ist (höchstens einmal pro Minute)."""
    global _last_fetch
    data = overview()
    stale = not data["stand"] or (data["alterMinuten"] or 0) >= INTERVAL // 60
    if stale and time.time() - _last_fetch > 60:
        _last_fetch = time.time()
        try:
            sample()
        except LibraryError as error:
            return f"⚠️ {html.escape(str(error))}\n\n" + status_text(query)
    return status_text(query)


# --- Messen im Hintergrund (launchd, auch wenn die App zu ist) ----------------------


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def background_active() -> bool:
    return PLIST.exists() and _launchctl("print", f"{DOMAIN}/{LABEL}").returncode == 0


def _job() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(core.PYTHON), str(Path(__file__).resolve()), "--sample"],
        "StartInterval": INTERVAL,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(core.LOG_FILE),
        "StandardErrorPath": str(core.LOG_FILE),
    }


def background_start() -> None:
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST, "wb") as file:
        plistlib.dump(_job(), file)
    _launchctl("bootout", f"{DOMAIN}/{LABEL}")
    _launchctl("bootstrap", DOMAIN, str(PLIST))
    core.log("Bibliotheken: Messung im Hintergrund eingeschaltet")


def background_refresh() -> bool:
    """Eingeschalteten Job an den aktuellen Stand anpassen (Intervall nach einem Update, Pfade nach
    einem Umzug des Projektordners). True, wenn er neu geschrieben wurde."""
    if not PLIST.exists():
        return False
    try:
        current = plistlib.loads(PLIST.read_bytes())
    except (plistlib.InvalidFileException, ValueError, OSError):
        current = {}
    if current == _job():
        return False
    background_start()
    core.log(f"Bibliotheken: Hintergrund-Job aktualisiert (alle {INTERVAL // 60} Minuten)")
    return True


def background_stop() -> None:
    _launchctl("bootout", f"{DOMAIN}/{LABEL}")
    PLIST.unlink(missing_ok=True)
    core.log("Bibliotheken: Messung im Hintergrund ausgeschaltet")


if __name__ == "__main__" and "--sample" in sys.argv[1:]:
    try:
        sample()
    except LibraryError as error:
        core.log(f"Bibliotheken: {error}")
