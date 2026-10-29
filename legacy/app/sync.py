"""Ein Abgleich: ILIAS -> lokaler Spiegel -> Zielordner, danach die Zusatzfunktionen.

launchd startet ihn mit --scheduled (dann gilt die Nachtruhe 23–6 Uhr);
"ilias-sync jetzt" startet ihn sofort.
"""

import argparse
import fcntl
import html
import json
import os
import shutil
import subprocess
import traceback
from datetime import datetime
from pathlib import Path, PurePosixPath

import core
import goodnotes
import notion_todo
from core import APP_DIR, MIRROR_DIR, PFERD_LOG, log, nfc
from notify import clear_once_a_day, notify, notify_once_a_day

LOCK_FILE = APP_DIR / ".lock"
QUIET_HOURS = (23, 6)
ALERT_AFTER_FAILURES = 2  # bei 30-Minuten-Takt etwa eine Stunde


class CrawlFailed(Exception):
    def __init__(self, message: str, login: bool):
        super().__init__(message)
        self.login = login


# --- ILIAS --------------------------------------------------------------------


def write_pferd_config(config: dict) -> Path:
    path = APP_DIR / "pferd.cfg"
    lines = [
        "# Wird bei jedem Abgleich neu geschrieben, Änderungen gehen verloren.",
        "[DEFAULT]",
        f"working_dir = {APP_DIR}",
        "status = no",
        "report = yes",
        "",
        "[crawl:ilias]",
        "type = ilias-web",
        f"base_url = {core.ILIAS_URL}",
        "login_type = shibboleth",
        "auth = auth:ilias",
        f"target = {core.COURSES_URL}",
        f"output_dir = {MIRROR_DIR.name}",
        "redownload = never-smart",
        "on_conflict = no-delete",
        "links = internet-shortcut",
        "videos = no",
        "forums = no",
        "tasks = 1",
        "http_timeout = 60",
        # Der Ordner "Dateien", den fast jeder Kurs hat, ist eine Ebene zu viel
        "transform =",
        '    "([^/]+)/Dateien" -re-> "{g1}"',
        '    "([^/]+)/Dateien/(.+)" -re-> "{g1}/{g2}"',
        "",
        "[auth:ilias]",
        "type = keyring",
        f"username = {config['uni_id']}",
        f"keyring_name = {core.KEYCHAIN_SERVICE}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_pferd(config: dict, list_only: bool = False) -> dict:
    """Startet PFERD. Liefert {"added", "changed", "entries", "new"} oder wirft CrawlFailed.

    Mit list_only meldet PFERD nur die Kurse (Login-Prüfung, Kursauswahl).
    """
    discovered = APP_DIR / "kurse-gefunden.json"
    discovered.unlink(missing_ok=True)
    selection = APP_DIR / "kursauswahl.json"
    core.save_json(selection, {
        "courses": config["courses"],
        "include_new": config["include_new_courses"],
        "list_only": list_only,
        "discovered": str(discovered),
    })
    command = [core.PYTHON, core.CODE_DIR / "pferd_runner.py", "--config", write_pferd_config(config)]
    PFERD_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(PFERD_LOG, "w", encoding="utf-8") as out:
        try:
            result = subprocess.run(
                command, cwd=APP_DIR, env={**os.environ, "ILIAS_SYNC_SELECTION": str(selection)},
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, timeout=45 * 60,
                start_new_session=True,  # ohne Terminal kann PFERD nicht nach einem Passwort fragen
            )
        except subprocess.TimeoutExpired:
            raise CrawlFailed("Abbruch nach 45 Minuten", login=False) from None

    # PFERD endet auch bei einem gescheiterten Crawl mit Exit 0: ein abgelehnter Login steht
    # nur als Zeile "Error …" in der Ausgabe, fehlendes Netz nur als Warnung. Sicheres
    # Zeichen für Erfolg ist, dass die Kursübersicht gelesen wurde.
    output = PFERD_LOG.read_text(encoding="utf-8", errors="replace")
    errors = [line for line in output.splitlines() if line.startswith("Error")]
    if result.returncode != 0 or errors or not discovered.exists():
        network = "ClientConnector" in output or "I/O Operation" in output
        message = " | ".join(errors) or ("keine Verbindung zu ILIAS" if network else "Kursübersicht nicht gelesen")
        raise CrawlFailed(message[:300], login=not network)

    report_file = MIRROR_DIR / ".report"
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() and not list_only else {}
    found = json.loads(discovered.read_text(encoding="utf-8"))
    return {
        "added": {nfc(path) for path in report.get("added", [])},
        "changed": {nfc(path) for path in report.get("changed", [])},
        "entries": found["entries"],
        "new": found["new"],
    }


# --- Zielordner ---------------------------------------------------------------


def publish(config: dict, state: dict) -> list[tuple[str, bool]]:
    """Kopiert neue und auf ILIAS geänderte Dateien in den Zielordner, nur in diese Richtung.

    Im Zielordner wird nie etwas überschrieben oder gelöscht: Eine auf ILIAS geänderte
    Datei kommt als zusätzliche Kopie "… (aktualisiert TT.MM.)" dazu, damit Notizen in der
    alten Fassung erhalten bleiben. Was du dort löschst, wird nicht erneut kopiert; eine
    gleichnamige Datei, die schon dort liegt (z. B. selbst heruntergeladen), bleibt stehen.
    Liefert (relativer Pfad, aktualisiert?) je kopierter Datei.
    """
    target_root = Path(config["target_dir"])
    copied = []
    for source in sorted(MIRROR_DIR.rglob("*")):
        relative = source.relative_to(MIRROR_DIR)
        if not source.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        key, mtime = nfc(relative.as_posix()), source.stat().st_mtime
        known = state["published"].get(key)
        if known is not None and abs(known - mtime) < 2:
            continue
        target = target_root / relative
        if known is None and target.exists():
            state["published"][key] = mtime  # liegt schon im Zielordner
            continue
        if known is not None:
            target = target.with_name(f"{target.stem} (aktualisiert {datetime.now():%d.%m.}){target.suffix}")
            if target.exists():
                target = target.with_name(f"{target.stem} {datetime.now():%H.%M}{target.suffix}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError as error:
            log(f"Zielordner: {relative} nicht kopiert: {error}")
            continue
        state["published"][key] = mtime
        copied.append((key, known is not None))
    return copied


def report_news(copied: list[tuple[str, bool]], first_run: bool, imported: list[str]) -> None:
    if not copied:
        return
    if first_run:
        notify("ILIAS-Sync: alle Dateien geladen", f"{len(copied)} Dateien aus deinen Kursen im Zielordner.", icon="✅")
        return
    lines, course = [], None
    for path, updated in sorted(copied):
        head, _, rest = path.partition("/")
        if head != course:
            course = head
            lines.append(f"\n<b>{html.escape(head)}</b>")
        notes = ", ".join(filter(None, ["aktualisiert" if updated else "", "→ GoodNotes" if path in imported else ""]))
        lines.append(f"• {html.escape(rest or head)}" + (f" <i>({notes})</i>" if notes else ""))
    names = [PurePosixPath(path).stem for path, _ in sorted(copied)]
    preview = ", ".join(names[:3]) + (f" und {len(names) - 3} weitere" if len(names) > 3 else "")
    count = len(copied)
    notify(f"Neu auf ILIAS: {count} Datei{'en' if count > 1 else ''}", preview, "\n".join(lines).strip(), icon="📚")


# --- Ablauf -------------------------------------------------------------------


def run(scheduled: bool = False) -> None:
    now = datetime.now().hour
    if scheduled and (now >= QUIET_HOURS[0] or now < QUIET_HOURS[1]):
        return
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Ein Abgleich läuft bereits.")
        return
    core.trim_log()
    config = core.load_config()
    if not config["uni_id"] or not config["target_dir"]:
        log("Noch nicht eingerichtet: im Terminal „ilias-sync einrichten“ ausführen.")
        return
    state = core.load_state()
    try:
        _run(config, state)
    except Exception as error:  # nichts darf den Hintergrund-Job stumm abbrechen lassen
        log("Unerwarteter Fehler:\n" + traceback.format_exc())
        notify_once_a_day("absturz", "ILIAS-Sync: unerwarteter Fehler", f"{type(error).__name__}: {error}")
    finally:
        core.save_state(state)


def _run(config: dict, state: dict) -> None:
    try:
        result = run_pferd(config)
    except CrawlFailed as failure:
        state["crawl_failures"] += 1
        log(f"ILIAS: {failure}")
        if failure.login:
            notify_once_a_day("login", "ILIAS-Anmeldung fehlgeschlagen",
                              "Passwort geändert? Im Terminal „ilias-sync zugang“ ausführen.")
        elif state["crawl_failures"] == ALERT_AFTER_FAILURES:
            notify("ILIAS nicht erreichbar", "Der Abruf schlägt seit etwa einer Stunde fehl.", icon="⚠️")
        return
    if state["crawl_failures"] >= ALERT_AFTER_FAILURES:
        notify("ILIAS wieder erreichbar", "Der Abruf funktioniert wieder.", icon="✅")
    state["crawl_failures"] = 0
    clear_once_a_day("login")
    log(f"ILIAS: abgeglichen, {len(result['added'])} neu, {len(result['changed'])} geändert")

    if result["new"]:
        config["courses"].update(result["new"])
        core.save_config(config)
        lines = [f"{settings['name']}" + ("" if settings["sync"] else " (nicht synchronisiert)")
                 for settings in result["new"].values()]
        notify("Neuer Kurs auf ILIAS", ", ".join(lines) + ". Anpassen mit „ilias-sync kurse“.", icon="🆕")

    first_run = not state["published"]
    copied = publish(config, state)
    core.save_state(state)
    if copied:
        log(f"Zielordner: {len(copied)} Dateien kopiert")

    imported: list[str] = []
    if config["goodnotes"] and copied and not first_run:
        try:
            paths = [MIRROR_DIR / path for path, _ in copied]
            imported = [nfc(p.relative_to(MIRROR_DIR).as_posix()) for p in goodnotes.import_files(paths)]
            if imported:
                log(f"GoodNotes: {len(imported)} Dateien übergeben")
        except (goodnotes.GoodNotesError, OSError) as error:
            log(f"GoodNotes: {error}")
            notify_once_a_day("goodnotes", "GoodNotes-Import fehlgeschlagen", str(error))
    report_news(copied, first_run, imported)

    if config["notion"]:
        try:
            added = notion_todo.add_entries(config, state, result["changed"])
            if added:
                log(f"Notion: {added} Einträge angelegt")
            state["notion_failures"] = 0
        except notion_todo.NotionError as error:
            state["notion_failures"] += 1
            log(f"Notion: {error}")
            if state["notion_failures"] == ALERT_AFTER_FAILURES + 1:
                notify("Notion-Liste wird nicht aktualisiert", str(error), icon="⚠️")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduled", action="store_true")
    run(scheduled=parser.parse_args().scheduled)
