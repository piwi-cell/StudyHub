"""Ergebnisse weitergeben: Telegram, reMarkable, Claude Desktop (Lerncoach) und Anki.

reMarkable hat keine offizielle Schnittstelle. Zwei Wege, der erste verfügbare gewinnt:
1. USB-Webinterface: Tablet per USB verbunden und unter Einstellungen › Speicher
   „USB-Webinterface“ aktiviert, dann nimmt http://10.11.99.1/upload PDFs an.
2. reMarkable-App für macOS: Die PDF wird mit der App geöffnet, die sie in die Cloud lädt.

Anki: über das Add-on AnkiConnect (Code 2055492159), das bei laufendem Anki eine lokale Schnittstelle
auf 127.0.0.1:8765 anbietet (JSON {action, version: 6, params} → {result, error}).

Telegram-Bot: Solange die App läuft, holt sie Nachrichten an den eigenen Bot ab (getUpdates mit Long
Polling, kein Server im Netz nötig) und beantwortet Befehle wie /bib, aber nur aus dem eingerichteten Chat.

Claude Desktop öffnet sich über den offiziellen Link claude://claude.ai/new?q=… mit einem neuen Chat,
in dem der Lerncoach-Auftrag schon im Eingabefeld steht (gesendet wird erst nach Bestätigung).
"""

import html
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx2 as httpx  # kommt mit dem Anthropic-SDK, gleiche API wie httpx
import keyring
import keyring.errors

import telegram_bot
from core import KEYCHAIN_SERVICE, load_config, log

REMARKABLE_USB = "http://10.11.99.1"
REMARKABLE_APP_NAMES = ("reMarkable.app", "reMarkable Desktop.app")
ANKI_URL = "http://127.0.0.1:8765"
ANKI_ADDON = "2055492159"
ANKI_BASIC_MODELS = ("Basic", "Einfach")  # Standard-Notiztyp in englischem bzw. deutschem Anki
ANKI_DECK_PREFIX = "StudyHub"


class ShareError(Exception):
    pass


# --- Text aufbereiten ---------------------------------------------------------


def markdown_to_telegram(markdown: str) -> str:
    """Reduziert Markdown auf das HTML, das Telegram kennt (b, i, code)."""
    lines = []
    for line in markdown.splitlines():
        text = html.escape(line)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        if heading := re.match(r"^#{1,6}\s+(.*)", text):
            text = f"\n<b>{heading.group(1)}</b>"
        elif re.match(r"^\s*[-*]\s+", text):
            text = re.sub(r"^\s*[-*]\s+", "• ", text)
        lines.append(text)
    return "\n".join(lines).strip()


def result_as_text(title: str, task: str, output) -> str:
    if task == "flashcards":
        cards = output.get("cards", [])
        body = "\n\n".join(f"{n}. {c['front']}\n   → {c['back']}" for n, c in enumerate(cards, 1))
        return f"Lernkarten: {title}\n\n{body}\n"
    return f"Zusammenfassung: {title}\n\n{re.sub(r'[*`#]', '', output)}\n"


# --- Telegram -----------------------------------------------------------------


def send_telegram(title: str, task: str, output) -> None:
    if task == "flashcards":
        cards = output.get("cards", [])
        body = "\n".join(f"<b>{n}.</b> {html.escape(c['front'])}\n<tg-spoiler>{html.escape(c['back'])}</tg-spoiler>"
                         for n, c in enumerate(cards, 1))
        text = f"🃏 <b>Lernkarten · {html.escape(title)}</b>\n\n{body}"
    else:
        text = f"📝 <b>{html.escape(title)}</b>\n\n{markdown_to_telegram(output)}"
    try:
        telegram_bot.send(text)
    except telegram_bot.TelegramError as error:
        raise ShareError(f"Telegram: {error}") from None


BOT_COMMANDS = [
    {"command": "bib", "description": "Wie voll sind die Bibliotheken? (/bib a3 nur für A3)"},
    {"command": "hilfe", "description": "Was der Bot kann"},
]
BOT_HELP = ("📚 <b>StudyHub</b>\n"
            "/bib – Auslastung aller Bibliotheksbereiche der UB\n"
            "/bib a3 – nur Bereiche mit „a3“ im Namen (auch: /bib ehrenhof)\n\n"
            "Der Bot antwortet, solange StudyHub auf dem Mac läuft.")
MAX_COMMAND_AGE = 120  # Sekunden: ältere Befehle (App war zu) nicht nachträglich beantworten


def answer_command(text: str, handlers: dict[str, Callable[[str], str]]) -> str | None:
    """Antwort auf eine Nachricht an den Bot: „/bib a3“, „/bib@MeinBot“ oder einfach „bib“."""
    match = re.match(r"^/?([^\s@/]+)(?:@\w+)?\s*(.*)$", text.strip(), re.S)
    if not match:
        return None
    command, args = match.group(1).casefold(), match.group(2).strip()
    if command in handlers:
        try:
            return handlers[command](args)
        except Exception as error:  # ein Fehler im Befehl darf den Bot nicht anhalten
            log(f"Telegram-Bot: /{command} fehlgeschlagen ({type(error).__name__}: {error})")
            return "⚠️ Das hat nicht geklappt. Details stehen im Protokoll der App."
    if command in ("start", "hilfe", "help"):
        return BOT_HELP
    return "Diesen Befehl kenne ich nicht.\n\n" + BOT_HELP


def poll_commands(token: str, chat_id: str, offset: int | None,
                  handlers: dict[str, Callable[[str], str]]) -> int | None:
    """Ein Durchgang: neue Nachrichten abholen (wartet bis zu 25 s) und beantworten. Liefert den
    nächsten offset; damit gelten die abgeholten Nachrichten bei Telegram als gelesen."""
    updates = telegram_bot._call(token, "getUpdates", timeout=25, offset=offset, allowed_updates=["message"])
    for update in updates:
        offset = update["update_id"] + 1
        message = update.get("message") or {}
        # Nur der eingerichtete Chat bekommt Antworten: der Bot ist öffentlich auffindbar
        if str(message.get("chat", {}).get("id")) != str(chat_id):
            continue
        if time.time() - message.get("date", 0) > MAX_COMMAND_AGE:
            continue
        if reply := answer_command(message.get("text", ""), handlers):
            telegram_bot._call(token, "sendMessage", chat_id=chat_id, text=reply[:telegram_bot.MAX_LENGTH],
                               parse_mode="HTML", disable_web_page_preview=True)
    return offset


def run_telegram_bot(stop: threading.Event, handlers: dict[str, Callable[[str], str]]) -> None:
    """Beantwortet Befehle an den Bot, solange die App läuft. Ohne eingerichtetes Telegram wartet er nur.

    Token und Chat-ID liest er einmal pro Verbindung aus dem Schlüsselbund, nicht bei jedem Durchgang:
    macOS fragt beim Lesen unter Umständen nach dem Passwort, und ein abgelehnter Zugriff soll nicht
    alle paar Sekunden einen neuen Dialog auslösen."""
    offset, registered, last_error = None, "", ""
    credentials: tuple[str | None, str | None] | None = None
    while not stop.is_set():
        if not load_config()["telegram"]:
            credentials = None  # getrennt: beim nächsten Verbinden neu lesen
            stop.wait(10)
            continue
        try:
            if credentials is None:
                credentials = (keyring.get_password(KEYCHAIN_SERVICE, "Telegram-Token"),
                               keyring.get_password(KEYCHAIN_SERVICE, "Telegram-Chat"))
        except keyring.errors.KeyringError as error:  # z. B. Zugriff im Dialog abgelehnt
            log(f"Telegram-Bot: Schlüsselbund nicht lesbar ({error}); nächster Versuch beim Neustart der App")
            return
        token, chat_id = credentials
        if not (token and chat_id):
            stop.wait(10)
            continue
        try:
            if registered != token:  # Befehlsmenü in Telegram (Knopf „/“ neben dem Eingabefeld)
                telegram_bot._call(token, "setMyCommands", commands=BOT_COMMANDS)
                registered = token
            offset = poll_commands(token, chat_id, offset, handlers)
            last_error = ""
        except Exception as error:  # Netz weg, Token ungültig: später wieder versuchen
            if str(error) != last_error:  # nicht alle 30 Sekunden dieselbe Meldung
                hint = (" – der Bot wird noch woanders abgefragt (zweite StudyHub-App offen?)"
                        if "409" in str(error) else "")
                log(f"Telegram-Bot: {error}{hint}")
            last_error = str(error)
            stop.wait(30)


# --- reMarkable ---------------------------------------------------------------


def _remarkable_app() -> Path | None:
    for name in REMARKABLE_APP_NAMES:
        for base in (Path("/Applications"), Path.home() / "Applications"):
            if (base / name).exists():
                return base / name
    return None


def _usb_available() -> bool:
    try:
        return httpx.get(f"{REMARKABLE_USB}/documents/", timeout=1.5).status_code < 500
    except httpx.HTTPError:
        return False


def remarkable_status() -> dict:
    return {"usb": _usb_available(), "app": _remarkable_app() is not None}


def send_remarkable(pdf: Path) -> str:
    """Schickt eine PDF ans reMarkable. Liefert den genutzten Weg."""
    if _usb_available():
        with open(pdf, "rb") as file:
            response = httpx.post(f"{REMARKABLE_USB}/upload",
                                  files={"file": (pdf.name, file, "application/pdf")}, timeout=60)
        if response.status_code >= 400:
            raise ShareError(f"reMarkable (USB): HTTP {response.status_code}")
        return "USB"
    app = _remarkable_app()
    if app is None:
        raise ShareError("reMarkable nicht gefunden: Tablet per USB verbinden (USB-Webinterface an) "
                         "oder die reMarkable-App für macOS installieren")
    result = subprocess.run(["open", "-g", "-a", str(app), str(pdf)], capture_output=True, text=True)
    if result.returncode != 0:
        raise ShareError(f"reMarkable-App: {result.stderr.strip() or 'Öffnen fehlgeschlagen'}")
    return "reMarkable-App"


def text_to_pdf(text: str, name: str) -> Path:
    """Erzeugt mit dem macOS-Druckfilter eine einfache PDF (für Zusammenfassungen und Karten)."""
    folder = Path(tempfile.mkdtemp(prefix="ilias-sync-"))
    source, pdf = folder / "text.txt", folder / f"{re.sub(r'[/:]', '-', name)}.pdf"
    source.write_text(text, encoding="utf-8")
    with open(pdf, "wb") as out:
        result = subprocess.run(["cupsfilter", "-i", "text/plain", "-m", "application/pdf", str(source)],
                                stdout=out, stderr=subprocess.DEVNULL)
    if result.returncode != 0 or pdf.stat().st_size == 0:
        raise ShareError("PDF konnte nicht erzeugt werden")
    return pdf


# --- Claude Desktop als Lerncoach -----------------------------------------------


class AnkiError(ShareError):
    pass


def anki(action: str, timeout: float = 10, **params):
    """Ein Aufruf an AnkiConnect; Fehler von Anki kommen als AnkiError."""
    try:
        response = httpx.post(ANKI_URL, json={"action": action, "version": 6, "params": params}, timeout=timeout)
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise AnkiError(f"Anki nicht erreichbar: Anki öffnen und das Add-on AnkiConnect (Code {ANKI_ADDON}) "
                        "installieren") from None
    if not isinstance(data, dict) or "error" not in data:
        raise AnkiError("Unerwartete Antwort von AnkiConnect")
    if data["error"]:
        raise AnkiError(f"Anki: {data['error']}")
    return data["result"]


def anki_status() -> dict:
    """Läuft Anki mit AnkiConnect? Dann auch die Decks."""
    try:
        return {"ready": True, "decks": sorted(anki("deckNames", timeout=3), key=str.casefold)}
    except AnkiError as error:
        return {"ready": False, "decks": [], "hinweis": str(error)}


def anki_cards(deck: str) -> list[tuple[str, str]]:
    """Karten eines Decks (mit Unterdecks) als (Vorderseite, Rückseite): die ersten beiden Felder je Notiz."""
    query = 'deck:"{}"'.format(deck.replace("\\", "\\\\").replace('"', '\\"'))
    notes = anki("findNotes", query=query)
    if not notes:
        return []
    cards = []
    for note in anki("notesInfo", timeout=60, notes=notes):
        fields = [f["value"] for f in sorted(note["fields"].values(), key=lambda f: f["order"])]
        if len(fields) >= 2:
            cards.append((fields[0], fields[1]))
    return cards


def _anki_model() -> tuple[str, list[str]]:
    """Notiztyp für den Export: „Basic“/„Einfach“, sonst der erste mit genau zwei Feldern."""
    names = anki("modelNames")
    for name in [n for n in ANKI_BASIC_MODELS if n in names] + [n for n in names if n not in ANKI_BASIC_MODELS]:
        fields = anki("modelFieldNames", modelName=name)
        if len(fields) == 2 or (name in ANKI_BASIC_MODELS and len(fields) >= 2):
            return name, fields
    raise AnkiError("In Anki fehlt ein Notiztyp mit Vorder- und Rückseite (z. B. „Basic“)")


def anki_export(course: str, cards: list[tuple[str, str]]) -> dict:
    """Karten in das Deck „StudyHub::<Kurs>“; Karten, die Anki schon kennt, bleiben unverändert."""
    deck = f"{ANKI_DECK_PREFIX}::{course.replace('::', ' ')}"
    model, fields = _anki_model()

    def field(text: str) -> str:
        return html.escape(text.strip()).replace("\n", "<br>")

    notes = [{"deckName": deck, "modelName": model, "tags": [ANKI_DECK_PREFIX],
              "fields": {fields[0]: field(front), fields[1]: field(back)}} for front, back in cards]
    anki("createDeck", deck=deck)
    possible = anki("canAddNotes", notes=notes) if notes else []
    new = [n for n, ok in zip(notes, possible, strict=True) if ok]
    if new:
        anki("addNotes", timeout=60, notes=new)
    return {"deck": deck, "neu": len(new), "vorhanden": len(notes) - len(new)}
