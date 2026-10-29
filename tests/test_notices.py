"""Lizenz und Hinweise zur Drittsoftware bleiben vollständig, wenn sich uv.lock ändert."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_every_locked_package_is_listed_in_third_party_notices():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    project = normalize(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"])
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    listed = {normalize(word) for word in re.findall(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", notices)}
    missing = sorted(normalize(p["name"]) for p in lock["package"] if normalize(p["name"]) not in listed | {project})
    assert not missing, f"In THIRD_PARTY_NOTICES.md nachtragen (mit Lizenz): {missing}"


def test_license_and_vendored_license_exist():
    assert "Alle Rechte vorbehalten" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    for vendor in (ROOT / "ui/vendor").iterdir():
        assert (vendor / "LICENSE").exists(), f"{vendor.name}: Lizenztext fehlt"
        assert vendor.name.rsplit("-", 1)[0] in (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
