"""Mitteilungen auf dem Mac und, falls eingerichtet, per Telegram."""

import html
import subprocess
import time

import telegram_bot
from core import APP_DIR, load_config, log


def notify(title: str, message: str, details: str = "", icon: str = "ℹ️") -> bool:
    """Mac-Mitteilung und Telegram-Nachricht; details (Telegram-HTML) ersetzt dort message.

    False, wenn Telegram eingerichtet ist, die Nachricht aber nicht ankam.
    """
    script = ["on run argv", "display notification (item 2 of argv) with title (item 1 of argv)", "end run"]
    args = [part for line in script for part in ("-e", line)]
    subprocess.run(["osascript", *args, title, message], check=False, capture_output=True)
    if not load_config()["telegram"]:
        return True
    try:
        telegram_bot.send(f"{icon} <b>{html.escape(title)}</b>\n{details or html.escape(message)}")
    except Exception as error:  # eine Benachrichtigung darf den Abgleich nie abbrechen
        log(f"Telegram: {type(error).__name__}: {error}")
        return False
    return True


def notify_once_a_day(key: str, title: str, message: str, details: str = "") -> None:
    marker = APP_DIR / f".meldung-{key}"
    if marker.exists() and time.time() - marker.stat().st_mtime < 24 * 3600:
        return
    # erst als gemeldet vermerken, wenn die Nachricht angekommen ist (z. B. kein Netz nach dem Aufwachen)
    if notify(title, message, details, icon="⚠️"):
        marker.touch()


def clear_once_a_day(key: str) -> None:
    (APP_DIR / f".meldung-{key}").unlink(missing_ok=True)
