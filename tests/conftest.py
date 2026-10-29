"""Testumgebung: eigener Datenordner, Schlüsselbund nur im Speicher, kein Netz.

core.py liest ILIAS_SYNC_HOME beim Import, deshalb wird alles gesetzt, bevor ein Test
die App-Module importiert.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import keyring
import keyring.backend
import pytest

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(tempfile.mkdtemp(prefix="ilias-sync-test-"))
os.environ["ILIAS_SYNC_HOME"] = str(HOME)
os.environ["ILIAS_SYNC_TOKEN"] = "test-token"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path[:0] = [str(ROOT / "core"), str(ROOT / "server")]


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if self.store.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError(username)


keyring.set_keyring(MemoryKeyring())


@pytest.fixture(autouse=True)
def clean_home():
    """Jeder Test beginnt mit leerem Datenordner."""
    for child in HOME.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    yield HOME


@pytest.fixture(autouse=True)
def no_spotlight(monkeypatch):
    """Goodnotes nicht per Spotlight (mdfind) suchen: gibt es nur auf macOS (CI läuft unter Linux) und hinge
    sonst vom Mac des Entwicklers ab. Tests, die Goodnotes brauchen, setzen find_app selbst."""
    import goodnotes

    monkeypatch.setattr(goodnotes, "find_app", lambda: None)


@pytest.fixture(autouse=True)
def no_claude_desktop(monkeypatch):
    """Nie die echte Konfiguration von Claude Desktop lesen oder schreiben."""
    import integrations

    monkeypatch.setattr(integrations, "CLAUDE_CONFIG", HOME / "Claude/claude_desktop_config.json")
    monkeypatch.setattr(integrations, "CLAUDE_APPS", ())
