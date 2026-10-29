"""Automatischer Abgleich über launchd: von 6 bis 23 Uhr alle 30 oder 60 Minuten und beim Anmelden."""

import os
import plistlib
import subprocess
from pathlib import Path

from core import CODE_DIR, LOG_FILE, PYTHON

LABEL = "local.ilias-sync"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
DOMAIN = f"gui/{os.getuid()}"
FIRST_HOUR, LAST_HOUR = 6, 22  # letzter Start 22:30; sync.py hält zusätzlich 23–6 Uhr Ruhe


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def is_active() -> bool:
    return _launchctl("print", f"{DOMAIN}/{LABEL}").returncode == 0


def start(interval_minutes: int) -> None:
    """Schreibt den Job neu und aktiviert ihn (bleibt über Neustarts aktiv). Gleicht sofort einmal ab."""
    minutes = [0, 30] if interval_minutes == 30 else [0]
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST, "wb") as file:
        plistlib.dump({
            "Label": LABEL,
            "ProgramArguments": [str(PYTHON), str(CODE_DIR / "sync.py"), "--scheduled"],
            "StartCalendarInterval": [
                {"Hour": hour, "Minute": minute} for hour in range(FIRST_HOUR, LAST_HOUR + 1) for minute in minutes
            ],
            "RunAtLoad": True,
            "ProcessType": "Background",
            "StandardOutPath": str(LOG_FILE),
            "StandardErrorPath": str(LOG_FILE),
        }, file)
    _launchctl("enable", f"{DOMAIN}/{LABEL}")
    _launchctl("bootout", f"{DOMAIN}/{LABEL}")
    _launchctl("bootstrap", DOMAIN, str(PLIST))


def stop() -> None:
    """Hält den Abgleich an; bleibt auch nach einem Neustart aus."""
    _launchctl("bootout", f"{DOMAIN}/{LABEL}")
    _launchctl("disable", f"{DOMAIN}/{LABEL}")


def remove() -> None:
    _launchctl("bootout", f"{DOMAIN}/{LABEL}")
    _launchctl("enable", f"{DOMAIN}/{LABEL}")  # ein früheres "stop" vergessen
    PLIST.unlink(missing_ok=True)
