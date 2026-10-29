"""Gemeinsame Pfade, Einstellungen, Zustand und Log von ILIAS-Sync."""

import copy
import json
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# ILIAS_SYNC_HOME: eigener Datenordner, z. B. für Demo-Daten oder Tests
_HOME = os.environ.get("ILIAS_SYNC_HOME")
APP_DIR = Path(_HOME) if _HOME else Path.home() / "Library/Application Support/ILIAS-Sync"
CODE_DIR = Path(__file__).resolve().parent
# Die Mac-App startet PFERD mit ihrem eigenen Python, die Terminal-Installation mit ihrem venv
PYTHON = Path(os.environ.get("ILIAS_SYNC_PYTHON", APP_DIR / "venv/bin/python"))
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "state.json"
# PFERD arbeitet in diesem lokalen Spiegel, nie direkt im Zielordner: iCloud Drive und
# OneDrive lagern Dateien auf "nur online" aus, und Hintergrund-Jobs können solche
# Dateien nicht lesen. In den Zielordner wird nur kopiert.
MIRROR_DIR = APP_DIR / "Spiegel"
LOG_DIR = APP_DIR / "Logs" if _HOME else Path.home() / "Library/Logs"
LOG_FILE = LOG_DIR / "ILIAS-Sync.log"
PFERD_LOG = LOG_DIR / "ILIAS-Sync-pferd.log"
KEYCHAIN_SERVICE = "ILIAS-Sync"  # Konten: <Uni-ID>, "Notion", "Telegram-Token", "Telegram-Chat"
ILIAS_URL = "https://ilias.uni-mannheim.de"
COURSES_URL = f"{ILIAS_URL}/ilias.php?baseClass=ilmembershipoverviewgui"

DEFAULT_CONFIG = {
    "uni_id": "",
    "target_dir": "",
    "interval_minutes": 30,
    "include_new_courses": True,
    # ILIAS-Titel -> {"name": Ordnername, "sync": bool, "url": ..., "group": bool}
    "courses": {},
    "goodnotes": False,
    "telegram": False,
    "notion": {},  # database_id, data_source_id, url, open_view, course_views
}
DEFAULT_STATE = {
    "published": {},  # relativer Pfad -> Änderungszeit der kopierten Fassung
    "crawl_failures": 0,
    "notion_files": {},
    "notion_failures": 0,
}


def load_json(path: Path, default: dict) -> dict:
    data = copy.deepcopy(default)
    if path.exists():
        data.update(json.loads(path.read_text(encoding="utf-8")))
    return data


def save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def update_json(path: Path, fields: dict) -> None:
    """Felder in einer kleinen JSON-Datei ergänzen (z. B. Fortschritt des Abgleichs)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    save_json(path, {**data, **fields})


def load_config() -> dict:
    return load_json(CONFIG_FILE, DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    save_json(CONFIG_FILE, config)


def update_config(change) -> dict:
    """Konfiguration frisch laden, mit change(config) ändern und speichern. Für den Abgleich: Er dauert Minuten,
    und seine Kopie vom Start würde überschreiben, was zwischendurch in der App geändert wurde."""
    config = load_config()
    change(config)
    save_config(config)
    return config


def load_state() -> dict:
    return load_json(STATE_FILE, DEFAULT_STATE)


def save_state(state: dict) -> None:
    save_json(STATE_FILE, state)


def log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    print(line, flush=True)
    # im Terminal oder aus der Mac-App gestartet; launchd leitet die Ausgabe selbst ins Protokoll
    if sys.stdout.isatty() or os.environ.get("ILIAS_SYNC_APP"):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as file:
            file.write(line + "\n")


def trim_log() -> None:
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2_000_000:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        LOG_FILE.write_text("\n".join(lines[-2000:]) + "\n", encoding="utf-8")


def nfc(text: str) -> str:
    """macOS speichert Dateinamen teils zerlegt (NFD); verglichen wird immer in NFC."""
    return unicodedata.normalize("NFC", text)
