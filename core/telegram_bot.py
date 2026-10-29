"""Telegram-Benachrichtigungen über einen eigenen Bot (optional).

Bot-Token und Chat-ID liegen im macOS-Schlüsselbund.
"""

import getpass
import json
import subprocess
import time
import urllib.error
import urllib.request

import keyring
from keyring.errors import PasswordDeleteError

from core import KEYCHAIN_SERVICE

MAX_LENGTH = 4000  # Telegram erlaubt 4096 Zeichen pro Nachricht


class TelegramError(Exception):
    pass


def _call(token: str, method: str, **params) -> dict | list:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    # Fehlermeldungen nie mit der URL weiterreichen: sie enthält den Token
    try:
        with urllib.request.urlopen(request, timeout=params.get("timeout", 0) + 20) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            description = json.load(error).get("description", "")
        except ValueError:
            description = ""
        raise TelegramError(f"HTTP {error.code} {description}".strip()) from None
    except (urllib.error.URLError, OSError) as error:
        raise TelegramError(str(getattr(error, "reason", error))) from None
    if not result.get("ok"):
        raise TelegramError(result.get("description", "unbekannter Fehler"))
    return result["result"]


def send(text: str) -> None:
    """Schickt text (Telegram-HTML) an den eingerichteten Chat. Ohne Einrichtung passiert nichts."""
    token = keyring.get_password(KEYCHAIN_SERVICE, "Telegram-Token")
    chat_id = keyring.get_password(KEYCHAIN_SERVICE, "Telegram-Chat")
    if not token or not chat_id:
        return
    if len(text) > MAX_LENGTH:
        # an einer Zeilengrenze kürzen, damit kein HTML-Tag halbiert wird
        text = text[:MAX_LENGTH].rsplit("\n", 1)[0] + "\n…"
    _call(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)


def _wait_for_private_chat(token: str) -> dict:
    offset, deadline = None, time.monotonic() + 300
    while time.monotonic() < deadline:
        for update in _call(token, "getUpdates", timeout=30, offset=offset):
            offset = update["update_id"] + 1
            chat = update.get("message", {}).get("chat", {})
            if chat.get("type") == "private":
                _call(token, "getUpdates", offset=offset)  # Nachricht als gelesen markieren
                return chat
    raise TelegramError("Keine Nachricht an den Bot erhalten (5 Minuten gewartet)")


def setup() -> bool:
    """Interaktiv: Bot verbinden. True, wenn eingerichtet."""
    print("  1. Öffne in Telegram den Chat mit @BotFather, schicke /newbot und folge den Schritten.")
    print("  2. BotFather antwortet mit einem Token (Form: 123456789:ABC…).")
    token = getpass.getpass("     Token einfügen (bleibt unsichtbar): ").strip()
    try:
        bot = _call(token, "getMe")
        print(f"     Bot gefunden: @{bot['username']}")
        print(f"  3. Schicke deinem Bot jetzt eine beliebige Nachricht, z. B. /start (https://t.me/{bot['username']}).")
        subprocess.run(["open", f"https://t.me/{bot['username']}"], check=False)
        chat = _wait_for_private_chat(token)
    except TelegramError as error:
        print(f"     Telegram: {error}")
        return False
    who = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
    handle = f" (@{chat['username']})" if chat.get("username") else ""
    if input(f"     Nachricht von {who}{handle}. Ist das dein Account? [J/n] ").strip().lower().startswith("n"):
        return False
    keyring.set_password(KEYCHAIN_SERVICE, "Telegram-Token", token)
    keyring.set_password(KEYCHAIN_SERVICE, "Telegram-Chat", str(chat["id"]))
    send("✅ <b>ILIAS-Sync ist mit Telegram verbunden.</b>\nHier kommen neue ILIAS-Dateien und Warnungen an.")
    print("     Verbunden, Testnachricht gesendet.")
    return True


def remove() -> None:
    for account in ("Telegram-Token", "Telegram-Chat"):
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, account)
        except PasswordDeleteError:
            pass
