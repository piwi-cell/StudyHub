"""Karteikarten: Lernstand nach SM-2 und eigene Karten (Anki-Import, Textdateien).

KI-Karten stehen im KI-Cache der jeweiligen Datei; hier liegt nur ihr Lernstand. Importierte
Karten (Anki, Textdatei) gehören zu einem Kurs und liegen komplett hier. Jede Karte hat eine
stabile ID aus Herkunft und Vorderseite, damit der Lernstand ein erneutes Erzeugen übersteht,
solange die Frage gleich bleibt.

SM-2 (Wozniak 1990) mit den drei Knöpfen der Oberfläche:
  nochmal → q=1: Wiederholung von vorn, wieder fällig in 10 Minuten
  schwer  → q=3: bestanden, Abstand wächst, Leichtigkeit sinkt
  gewusst → q=5: bestanden, Abstand wächst, Leichtigkeit steigt
"""

import hashlib
import html
import re
import time

import core

STATE_FILE = core.APP_DIR / "karten.json"
RATINGS = {"nochmal": 1, "schwer": 3, "gewusst": 5}
START_EASE = 2.5
MIN_EASE = 1.3
RELEARN_SECONDS = 600
DAY = 86400
MAX_IMPORT = 5000  # Karten pro Import
MAX_FIELD = 4000  # Zeichen pro Seite


class CardError(Exception):
    pass


def card_id(source: str, front: str) -> str:
    """Stabile Karten-ID: Herkunft (Dateipfad bzw. „anki:Kurs“) und Vorderseite."""
    return hashlib.sha1(f"{core.nfc(source)}\x00{front.strip()}".encode()).hexdigest()[:16]


def load() -> dict:
    return core.load_json(STATE_FILE, {"reviews": {}, "imported": {}})


def save(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    core.save_json(STATE_FILE, data)


# --- SM-2 -----------------------------------------------------------------------


def schedule(review: dict | None, rating: str, now: float) -> dict:
    """Neuer Lernstand einer Karte nach einer Bewertung."""
    if rating not in RATINGS:
        raise CardError(f"Unbekannte Bewertung {rating}")
    q = RATINGS[rating]
    r = {"ease": START_EASE, "interval": 0, "reps": 0, "lapses": 0, **(review or {})}
    if q < 3:
        r.update(reps=0, interval=0, lapses=r["lapses"] + 1, due=now + RELEARN_SECONDS)
    else:
        interval = 1 if r["reps"] == 0 else 6 if r["reps"] == 1 else round(r["interval"] * r["ease"])
        r.update(reps=r["reps"] + 1, interval=max(1, interval), due=now + max(1, interval) * DAY)
    r["ease"] = round(max(MIN_EASE, r["ease"] + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)), 3)
    r["last"] = now
    return r


def review(cid: str, rating: str, now: float | None = None) -> dict:
    if not re.fullmatch(r"[0-9a-f]{16}", cid or ""):
        raise CardError("Ungültige Karten-ID")
    data = load()
    data["reviews"][cid] = schedule(data["reviews"].get(cid), rating, now or time.time())
    save(data)
    return data["reviews"][cid]


def state_of(review: dict | None, now: float) -> dict:
    """Für die Oberfläche: neu, fällig oder erst später (mit Tagen bis zur nächsten Wiederholung)."""
    if not review:
        return {"neu": True, "faellig": True, "inTagen": 0}
    days = max(0, round((review["due"] - now) / DAY))
    return {"neu": False, "faellig": review["due"] <= now, "inTagen": days}


# --- Eigene Karten ----------------------------------------------------------------


def add_cards(course: str, cards: list[tuple[str, str]], origin: str) -> dict:
    """Fügt Karten (Vorder-, Rückseite) einem Kurs hinzu. Doppelte Vorderseiten werden übersprungen."""
    course = core.nfc(course)
    data = load()
    added = 0
    for front, back in cards[:MAX_IMPORT]:
        front, back = front.strip()[:MAX_FIELD], back.strip()[:MAX_FIELD]
        if not front or not back:
            continue
        cid = card_id(f"eigene:{course}", front)
        if cid in data["imported"]:
            continue
        data["imported"][cid] = {"kurs": course, "front": front, "back": back, "quelle": origin,
                                 "created": time.time(), "nr": len(data["imported"])}  # nr: Reihenfolge
        added += 1
    save(data)
    core.log(f"Karten: {added} aus {origin} in {course} übernommen")
    return {"neu": added, "doppelt": len(cards[:MAX_IMPORT]) - added, "gekuerzt": len(cards) > MAX_IMPORT}


def course_cards(course: str, data: dict | None = None) -> list[dict]:
    """Eigene Karten eines Kurses: [{id, front, back, quelle}]."""
    data = data or load()
    course = core.nfc(course)
    own = [{"id": cid, **c} for cid, c in data["imported"].items() if c["kurs"] == course]
    return sorted(own, key=lambda c: c.get("nr", 0))


def all_for_course(course: str, ai_entries: dict[str, dict]) -> list[tuple[str, str]]:
    """Alle Karten eines Kurses für den Export: KI-Karten aus dem KI-Cache und eigene Karten."""
    course = core.nfc(course)
    result = []
    for path, entry in sorted(ai_entries.items()):
        if core.nfc(path).split("/", 1)[0] == course:
            result += [(c["front"], c["back"])
                       for c in ((entry.get("flashcards") or {}).get("output") or {}).get("cards", [])]
    return result + [(c["front"], c["back"]) for c in course_cards(course)]


# --- Textdateien (Anki: „Notizen als Text“) -----------------------------------------


def plain(field: str) -> str:
    """Anki-Feld (HTML) → einfacher Text mit Zeilenumbrüchen."""
    text = re.sub(r"<br\s*/?>|</div>|</p>|</li>", "\n", field, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[sound:[^\]]*\]", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def parse_text(text: str) -> list[tuple[str, str]]:
    """Textexport aus Anki oder eigene Liste: eine Karte pro Zeile, Vorder- und Rückseite durch
    Tabulator getrennt (Kopfzeilen wie „#separator:tab“ werden beachtet, sonst auch ; oder |)."""
    separator, cards = None, []
    names = {"tab": "\t", "semicolon": ";", "comma": ",", "pipe": "|", "space": " "}
    for line in text.lstrip("﻿").splitlines():
        if line.startswith("#"):
            if match := re.match(r"#separator:(\S+)", line):
                separator = names.get(match.group(1).lower(), match.group(1))
            continue
        if not line.strip():
            continue
        sep = separator or next((s for s in ("\t", ";", "|") if s in line), None)
        if not sep:
            continue
        fields = [plain(f.strip().strip('"')) for f in line.split(sep)]
        fields = [f for f in fields if f]
        if len(fields) >= 2:
            cards.append((fields[0], fields[1]))
    if not cards:
        raise CardError("Keine Karten gefunden: eine Karte pro Zeile, Vorder- und Rückseite durch Tabulator getrennt")
    return cards


def to_text(cards: list[tuple[str, str]]) -> str:
    """Textdatei für den Anki-Import (Datei › Importieren): Tabulator, HTML, Zeilenumbruch als <br>."""
    def field(text: str) -> str:
        return html.escape(text.strip()).replace("\t", " ").replace("\r", "").replace("\n", "<br>")

    lines = ["#separator:tab", "#html:true"]
    lines += [f"{field(front)}\t{field(back)}" for front, back in cards]
    return "\n".join(lines) + "\n"
