"""Kurse aus "Meine Kurse und Gruppen": kurze Ordnernamen vorschlagen.

Wird vom Einrichtungsassistenten und von pferd_runner.py (für neu auftauchende
Kurse während eines Abgleichs) gleich verwendet, damit die Namen übereinstimmen.
"""

import re

# Kein Lehrinhalt, standardmäßig nicht synchronisiert
EXCLUDED_BY_DEFAULT = re.compile(r"^License Information", re.IGNORECASE)


def short_name(title: str) -> str:
    """"ACC 300 Introduction to Financial Accounting [V] (WT 2026)" -> "Introduction to Financial Accounting"."""
    name = re.sub(r"\s*\[[^\]]*\]", "", title)  # [V], [1. PG]
    name = re.sub(r"\s*\((?:HWS|FSS|HS|FS|WS|SS|WT|ST)\s*\d{2,4}\)", "", name)  # (HWS 2026)
    name = re.sub(r"^[A-Z]{2,5} ?\d{3}[A-Z]?\s+", "", name)  # ACC 300, MAN 301, CC 302
    return name.strip(" -–:,") or title


def is_group(url: str) -> bool:
    return "/grp/" in url or "grp_" in url


def safe_folder_name(name: str) -> str:
    """Eigene Namen dürfen keinen Schrägstrich enthalten (würde einen Unterordner anlegen)."""
    return re.sub(r"\s+", " ", name.replace("/", "-")).strip() or "Kurs"


def suggest(entries: list[dict], known: dict[str, dict]) -> dict[str, dict]:
    """Einstellungen für bisher unbekannte Kurse und Gruppen.

    entries: [{"title": ..., "url": ...}] von der ILIAS-Übersicht.
    known: bereits bekannte Kurse (ILIAS-Titel -> Einstellungen), deren Namen belegt sind.
    Übungsgruppen zu einem Kurs landen als Unterordner "<Kurs>/Übungsgruppe".
    """
    taken = {settings["name"] for settings in known.values()}
    new: dict[str, dict] = {}
    for entry in sorted(entries, key=lambda e: is_group(e["url"])):  # erst Kurse, dann Gruppen
        title, url = entry["title"], entry["url"]
        if title in known or title in new:
            continue
        name = short_name(title)
        if is_group(url):
            parent = next(
                (
                    settings["name"]
                    for other, settings in {**known, **new}.items()
                    if not settings.get("group") and short_name(other) == name
                ),
                None,
            )
            if parent:
                name = f"{parent}/Übungsgruppe"
        candidate, number = name, 2
        while candidate in taken:
            candidate, number = f"{name} ({number})", number + 1
        taken.add(candidate)
        new[title] = {
            "name": candidate,
            "sync": not EXCLUDED_BY_DEFAULT.search(title),
            "url": url,
            "group": is_group(url),
        }
    return new
