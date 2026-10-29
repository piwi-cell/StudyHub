"""Notion-To-do-Liste für neue ILIAS-Dokumente (optional).

Legt in einer eigenen Notion-Datenbank "ILIAS-Dokumente" für jedes neue Dokument einen
offenen Eintrag an: je Fach ein Tab, gruppiert nach Art (Vorlesung, Übung, …),
sortiert nach dem Upload-Datum auf ILIAS. Aus Notion wird nie etwas zurückgelesen;
Abhaken dort ändert nichts an ILIAS oder am Zielordner.
Zugang: eine interne Notion-Verbindung (nur für eine freigegebene Seite), Token im
Schlüsselbund.
"""

import getpass
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path, PurePosixPath

import keyring
from keyring.errors import PasswordDeleteError

from core import KEYCHAIN_SERVICE, MIRROR_DIR, log, nfc, save_config

NOTION_VERSION = "2026-03-11"
DATABASE_TITLE = "ILIAS-Dokumente"
SKIP_SUFFIXES = {".url"}  # ILIAS-Links sind keine Dokumente
# Art nach dem ersten Ordner unter dem Fach; die erste passende Zeile gilt
ARTS = [
    ("Klausur", ("klausur", "exam"), "red"),
    ("Tutorium", ("tutor",), "orange"),
    ("Übung", ("übung", "uebung", "exercise", "aufgabe"), "green"),
    ("Vorlesung", ("vorlesung", "lecture", "folien", "skript"), "blue"),
]
OTHER_ART = ("Sonstiges", "gray")


class NotionError(Exception):
    pass


def _api(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    token = token or keyring.get_password(KEYCHAIN_SERVICE, "Notion")
    if not token:
        raise NotionError("Kein Notion-Token hinterlegt")
    request = urllib.request.Request(
        f"https://api.notion.com/v1/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"},
    )
    # Fehlermeldungen nie mit Request-Details weiterreichen: sie enthalten den Token
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 or error.code >= 500:
                time.sleep(float(error.headers.get("Retry-After") or 2**attempt))
                continue
            try:
                message = json.load(error).get("message", "")
            except ValueError:
                message = ""
            raise NotionError(f"HTTP {error.code}: {message}") from None
        except (urllib.error.URLError, OSError) as error:
            raise NotionError(str(getattr(error, "reason", error))) from None
    raise NotionError("Notion ist dauerhaft überlastet (HTTP 429/5xx)")


# --- Dokumente ----------------------------------------------------------------


def documents() -> dict[str, Path]:
    """Alle Dokumente im Spiegel (relativer Pfad -> Datei), ohne Links und versteckte Dateien."""
    found = {}
    for path in MIRROR_DIR.rglob("*"):
        relative = path.relative_to(MIRROR_DIR)
        if len(relative.parts) < 2 or any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_file() and path.suffix and path.suffix.lower() not in SKIP_SUFFIXES:
            found[nfc(relative.as_posix())] = path
    return found


def art_of(relative: str) -> str:
    parts = PurePosixPath(relative).parts
    folder = parts[1].casefold() if len(parts) > 2 else ""
    for name, keywords, _ in ARTS:
        if any(keyword in folder for keyword in keywords):
            return name
    return OTHER_ART[0]


def select_name(name: str) -> str:
    return name.replace(",", " ")[:100]  # Notion erlaubt keine Kommas in Auswahloptionen


def _properties(relative: str, path: Path, updated: bool) -> dict:
    parts = PurePosixPath(relative).parts
    title = path.stem if path.suffix.lower() == ".pdf" else path.name
    if updated:
        title += f" (aktualisiert {datetime.now():%d.%m.})"
    uploaded = datetime.fromtimestamp(path.stat().st_mtime).astimezone()  # PFERD setzt das ILIAS-Datum
    return {
        "Name": {"title": [{"text": {"content": title[:2000]}}]},
        "Fach": {"select": {"name": select_name(parts[0])}},
        "Art": {"select": {"name": art_of(relative)}},
        "Hochgeladen": {"date": {"start": uploaded.isoformat(timespec="minutes")}},
        "Ordner": {"rich_text": [{"text": {"content": "/".join(parts[1:-1])[:2000]}}]},
    }


# --- Datenbank und Ansichten --------------------------------------------------


def _create_database(page_id: str, token: str) -> dict:
    art_options = [{"name": name, "color": color} for name, _, color in ARTS]
    art_options.append({"name": OTHER_ART[0], "color": OTHER_ART[1]})
    database = _api(
        "POST",
        "databases",
        {
            "parent": {"type": "page_id", "page_id": page_id},
            "title": [{"text": {"content": DATABASE_TITLE}}],
            "initial_data_source": {
                "properties": {
                    "Name": {"title": {}},
                    "Erledigt": {"checkbox": {}},
                    "Fach": {"select": {"options": []}},
                    "Art": {"select": {"options": art_options}},
                    "Hochgeladen": {"date": {}},
                    "Ordner": {"rich_text": {}},
                }
            },
        },
        token=token,
    )
    if not database.get("data_sources"):
        database = _api("GET", f"databases/{database['id']}", token=token)
    return {"database_id": database["id"], "data_source_id": database["data_sources"][0]["id"],
            "url": database.get("url", ""), "course_views": {}}


def _ensure_views(notion: dict, courses: set[str]) -> bool:
    """Tab "Offen" und je Fach ein Tab. True, wenn etwas angelegt wurde."""
    missing = courses - set(notion["course_views"])
    if notion.get("open_view") and not missing:
        return False  # alles eingerichtet, keine Anfrage nötig
    data_source = _api("GET", f"data_sources/{notion['data_source_id']}")
    ids = {name: prop["id"] for name, prop in data_source["properties"].items()}
    by_date = [{"property": "Hochgeladen", "direction": "ascending"}]
    if not notion.get("open_view"):
        default = _api("GET", f"views?database_id={notion['database_id']}")["results"][0]
        _api("PATCH", f"views/{default['id']}", {
            "name": "Offen",
            "filter": {"property": "Erledigt", "checkbox": {"equals": False}},
            "sorts": by_date,
            "configuration": {"type": "table", "group_by": {
                "type": "select", "property_id": ids["Fach"], "sort": {"type": "manual"}}},
        })
        notion["open_view"] = default["id"]
    for course in sorted(missing):
        view = _api("POST", "views", {
            "database_id": notion["database_id"],
            "data_source_id": notion["data_source_id"],
            "name": course,
            "type": "table",
            "filter": {"property": "Fach", "select": {"equals": course}},
            "sorts": by_date,
            "configuration": {"type": "table", "group_by": {
                "type": "select", "property_id": ids["Art"], "sort": {"type": "manual"}, "hide_empty_groups": True}},
        })
        notion["course_views"][course] = view["id"]
        log(f"Notion: Tab „{course}“ angelegt")
    return True


# --- Abläufe ------------------------------------------------------------------


def add_entries(config: dict, state: dict, changed: set[str]) -> int:
    """Trägt neue Dokumente und auf ILIAS geänderte (changed) ein. Liefert die Anzahl."""
    notion = config["notion"]
    docs = documents()
    try:
        if _ensure_views(notion, {select_name(PurePosixPath(rel).parts[0]) for rel in docs}):
            save_config(config)
    except NotionError as error:
        log(f"Notion-Tabs: {error} (Einträge werden trotzdem angelegt)")
    added = 0
    for relative, path in sorted(docs.items(), key=lambda item: item[1].stat().st_mtime):
        known = state["notion_files"].get(relative)
        updated = known is not None and relative in changed and abs(known - path.stat().st_mtime) > 1
        if known is not None and not updated:
            continue
        _api("POST", "pages", {
            "parent": {"type": "data_source_id", "data_source_id": notion["data_source_id"]},
            "properties": _properties(relative, path, updated),
        })
        state["notion_files"][relative] = path.stat().st_mtime
        added += 1
        time.sleep(0.35)  # Notion erlaubt etwa drei Anfragen pro Sekunde
    return added


def setup(config: dict) -> bool:
    """Interaktiv: Verbindung und Datenbank einrichten. True, wenn eingerichtet."""
    print("  1. Öffne notion.so › Einstellungen › Verbindungen (Entwicklertools) › „Neue Verbindung“.")
    print("     Name z. B. „ILIAS-Sync“, Authentifizierung „Zugriffstoken“, erstellen, Token kopieren.")
    print("     (Kein „Persönliches Zugriffstoken“: das hätte Zugriff auf dein ganzes Notion.)")
    subprocess.run(["open", "https://www.notion.so/profile/integrations"], check=False)
    token = getpass.getpass("     Token einfügen (bleibt unsichtbar): ").strip()
    try:
        bot = _api("GET", "users/me", token=token)
        print(f"     Verbindung gefunden: {bot.get('name', '?')}")
        print("  2. Lege in Notion eine Seite an (z. B. „Uni“) und gib sie der Verbindung frei:")
        print("     auf der Seite ••• › Verbindungen › deine Verbindung, oder in der Verbindung unter „Zugriff“.")
        while True:
            input("     Danach Enter drücken … ")
            pages = _api("POST", "search", {"filter": {"property": "object", "value": "page"}}, token=token)["results"]
            pages = [p for p in pages if p.get("parent", {}).get("type") != "data_source_id"]
            if pages:
                break
            print("     Noch keine Seite freigegeben.")
        titles = []
        for page in pages:
            title_prop = next((p for p in page["properties"].values() if p["type"] == "title"), None)
            titles.append("".join(t["plain_text"] for t in title_prop["title"]) if title_prop else "(ohne Titel)")
        choice = 0
        if len(pages) > 1:
            for number, title in enumerate(titles, 1):
                print(f"       {number}. {title}")
            choice = int(input("     Unter welcher Seite? Nummer: ")) - 1
        notion = _create_database(pages[choice]["id"], token)
    except (NotionError, ValueError, IndexError) as error:
        print(f"     Notion: {error}")
        return False
    keyring.set_password(KEYCHAIN_SERVICE, "Notion", token)
    config["notion"] = notion
    save_config(config)
    print(f"     Liste „{DATABASE_TITLE}“ unter „{titles[choice]}“ angelegt. Einträge folgen beim nächsten Abgleich.")
    return True


def remove(config: dict, state: dict) -> None:
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, "Notion")
    except PasswordDeleteError:
        pass
    config["notion"] = {}
    state["notion_files"] = {}
