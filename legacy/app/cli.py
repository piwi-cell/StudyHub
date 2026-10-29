"""ILIAS-Sync: holt die Dateien deiner ILIAS-Kurse (Uni Mannheim) automatisch auf den Mac.

  ilias-sync                  Übersicht und Menü
  ilias-sync einrichten       Einrichtung Schritt für Schritt
  ilias-sync jetzt            sofort abgleichen
  ilias-sync kurse            Kurse an-/abwählen und umbenennen
  ilias-sync ordner           Zielordner ändern
  ilias-sync module           GoodNotes, Notion, Telegram ein-/ausschalten
  ilias-sync zugang           Uni-ID oder Passwort ändern
  ilias-sync stop / start     automatischen Abgleich anhalten / fortsetzen
  ilias-sync log              letzte Einträge im Protokoll
  ilias-sync deinstallieren   alles entfernen (deine Dateien bleiben)
"""

import fcntl
import getpass
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import keyring
from keyring.errors import PasswordDeleteError

import core
import courses
import goodnotes
import notion_todo
import schedule
import sync
import telegram_bot
from core import APP_DIR, KEYCHAIN_SERVICE, LOG_FILE, MIRROR_DIR, PFERD_LOG

ICLOUD = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
COMMAND_LINK = Path.home() / ".local/bin/ilias-sync"
ZPROFILE = Path.home() / ".zprofile"
PATH_BLOCK = ("# >>> ILIAS-Sync >>>", "# <<< ILIAS-Sync <<<")

# --- Darstellung --------------------------------------------------------------

COLOR = sys.stdout.isatty()


def _style(code: str):
    return lambda text: f"\033[{code}m{text}\033[0m" if COLOR else str(text)


bold, dim, green, red, yellow = _style("1"), _style("2"), _style("32"), _style("31"), _style("33")


def header() -> None:
    print()
    print(bold("  ILIAS-Sync · Uni Mannheim"))
    print(dim("  Neue Dateien aus deinen ILIAS-Kursen automatisch auf deinem Mac"))


def step(number: int, total: int, title: str) -> None:
    print(f"\n{bold(f'  Schritt {number} von {total}')} · {title}")


def ok(text: str) -> None:
    print(f"  {green('✓')} {text}")


def fail(text: str) -> None:
    print(f"  {red('✗')} {text}")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"  {prompt}{suffix}: ").strip() or default


def yes(prompt: str, default: bool = True) -> bool:
    answer = input(f"  {prompt} {'[J/n]' if default else '[j/N]'} ").strip().lower()
    return default if not answer else answer.startswith(("j", "y"))


def choose(options: list[str]) -> int:
    for number, option in enumerate(options, 1):
        print(f"    {bold(number)}  {option}")
    while True:
        answer = input("  Auswahl: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        fail(f"Bitte eine Nummer von 1 bis {len(options)} eingeben.")


def as_path(text: str) -> Path | None:
    """Eingetippter, eingefügter oder aus dem Finder gezogener Pfad (mit \\-Leerzeichen oder Anführungszeichen)."""
    text = text.strip().strip("'\"").replace("\\ ", " ")
    return Path(text).expanduser() if text.startswith(("/", "~")) else None


def pretty_path(path: str) -> str:
    text = str(path)
    if text.startswith(str(ICLOUD)):
        return "iCloud Drive" + text[len(str(ICLOUD)):]
    return text.replace(str(Path.home()), "~", 1)


@contextmanager
def no_sync_running():
    """Während Kurse umbenannt oder Ordner geändert werden, darf kein Abgleich laufen."""
    with open(sync.LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("Gerade läuft ein Abgleich. Bitte in ein paar Minuten noch einmal versuchen.")
            sys.exit(1)
        yield


# --- Bausteine ----------------------------------------------------------------


def ask_credentials(config: dict) -> dict | None:
    """Fragt Uni-ID und Passwort, prüft die Anmeldung und liefert die gefundenen Kurse."""
    for _ in range(3):
        uni_id = ask("Uni-ID (z. B. mmuster)", config["uni_id"])
        password = getpass.getpass("  Passwort (bleibt unsichtbar): ")
        if not uni_id or not password:
            continue
        previous = config["uni_id"]
        config["uni_id"] = uni_id
        keyring.set_password(KEYCHAIN_SERVICE, uni_id, password)
        (APP_DIR / "cookies.txt").unlink(missing_ok=True)
        print(dim("  Anmeldung bei ILIAS wird geprüft (ca. 20 Sekunden) …"))
        try:
            result = sync.run_pferd(config, list_only=True)
        except sync.CrawlFailed as failure:
            fail("Keine Verbindung zu ILIAS. Internet prüfen." if not failure.login
                 else "Anmeldung fehlgeschlagen. Uni-ID oder Passwort falsch?")
            _forget_password(uni_id)
            config["uni_id"] = previous
            continue
        if previous and previous != uni_id:
            _forget_password(previous)
        ok(f"Angemeldet · {len(result['entries'])} Kurse und Gruppen gefunden")
        return result
    fail("Drei Versuche fehlgeschlagen. Details: " + pretty_path(PFERD_LOG))
    return None


def _forget_password(uni_id: str) -> None:
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, uni_id)
    except PasswordDeleteError:
        pass


def rename_course(config: dict, state: dict, title: str, new_name: str) -> bool:
    """Benennt den Ordner eines Kurses um, auch schon geladene Dateien (Spiegel und Zielordner)."""
    old = config["courses"][title]["name"]
    new = courses.safe_folder_name(new_name)
    if new == old:
        return True
    if any(s["name"] == new for t, s in config["courses"].items() if t != title):
        fail(f"„{new}“ ist schon vergeben.")
        return False
    for base in (MIRROR_DIR, Path(config["target_dir"])) if config["target_dir"] else (MIRROR_DIR,):
        if (base / old).exists() and not (base / new).exists():
            (base / old).rename(base / new)
    for settings in config["courses"].values():  # zugehörige Übungsgruppen ziehen mit
        if settings["name"] == old or settings["name"].startswith(old + "/"):
            settings["name"] = new + settings["name"][len(old):]
    for key in ("published", "notion_files"):
        state[key] = {
            (new + path[len(old):] if path == old or path.startswith(old + "/") else path): value
            for path, value in state[key].items()
        }
    return True


def edit_courses(config: dict, state: dict) -> None:
    # nach Ordnername sortiert, damit Übungsgruppen direkt unter ihrem Kurs stehen
    items = sorted(config["courses"].items(), key=lambda item: item[1]["name"].casefold())
    columns = shutil.get_terminal_size((100, 24)).columns
    name_width = min(46, max(len(s["name"]) for _, s in items)) if items else 20
    title_width = max(0, columns - name_width - 12)
    while True:
        print()
        for number, (title, settings) in enumerate(items, 1):
            mark = green("✓") if settings["sync"] else dim("·")
            name = f"{settings['name']:<{name_width}.{name_width}}"
            print(f"   {number:>2}  {mark}  {name if settings['sync'] else dim(name)}  {dim(title[:title_width])}")
        print(dim("\n  Nummer = an/aus  ·  u Nummer = Ordner umbenennen  ·  Enter = fertig"))
        answer = input("  > ").strip().lower()
        if not answer:
            break
        rename = answer.startswith("u")
        number = answer.lstrip("u ").strip()
        if not number.isdigit() or not 1 <= int(number) <= len(items):
            fail(f"Bitte eine Nummer von 1 bis {len(items)} eingeben, „u“ und eine Nummer, oder nur Enter.")
            continue
        title, settings = items[int(number) - 1]
        if rename:
            new_name = input(f"  Neuer Ordnername für „{settings['name']}“: ").strip()
            if new_name:
                rename_course(config, state, title, new_name)
        else:
            settings["sync"] = not settings["sync"]
    config["include_new_courses"] = yes(
        "Neue Kurse (z. B. im nächsten Semester) automatisch übernehmen?", config["include_new_courses"]
    )
    print(dim("  Abgewählte Kurse werden nicht mehr geladen; schon geladene Dateien bleiben."))


def choose_target(config: dict, state: dict) -> None:
    options, paths = [], []
    if ICLOUD.exists():
        options.append("iCloud Drive › ILIAS " + dim("(auch auf iPad und iPhone, gut für GoodNotes)"))
        paths.append(ICLOUD / "ILIAS")
    options += ["Dokumente › ILIAS", "Anderen Ordner im Finder auswählen …", "Pfad eintippen"]
    paths += [Path.home() / "Documents/ILIAS", "finder", "typed"]
    for number, option in enumerate(options, 1):
        print(f"    {bold(number)}  {option}")
    print(dim("  Nummer eingeben, oder direkt einen Pfad einfügen bzw. einen Ordner aus dem Finder hierher ziehen."))
    while True:
        answer = input("  Auswahl: ").strip()
        target = as_path(answer)
        if target is None and answer.isdigit() and 1 <= int(answer) <= len(options):
            target = paths[int(answer) - 1]
            if target == "finder":
                script = 'POSIX path of (choose folder with prompt "Zielordner für deine ILIAS-Dateien")'
                picked = subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()
                target = Path(picked) if picked else None
            elif target == "typed":
                target = as_path(input("  Pfad (z. B. ~/Desktop/ILIAS): "))
        if target is None:
            fail(f"Bitte eine Nummer von 1 bis {len(options)} eingeben oder einen Pfad, der mit / oder ~ beginnt.")
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            break
        except OSError as error:
            fail(f"Ordner lässt sich nicht anlegen ({error.strerror}). Bitte einen anderen wählen.")
    if str(target) != config["target_dir"]:
        config["target_dir"] = str(target)
        state["published"] = {}  # in den neuen Ordner alles einmal kopieren
    ok(f"Zielordner: {pretty_path(target)}")
    print(dim("  Darin entsteht je Kurs ein Unterordner. Was du dort löschst, wird nicht erneut kopiert."))


def modules(config: dict, state: dict) -> None:
    print(f"\n  {bold('GoodNotes')} " + dim("(experimentell)"))
    if goodnotes.find_app() is None:
        print("  Goodnotes für Mac nicht gefunden (braucht macOS 15.7 oder neuer).")
        print(dim("  Tipp: Zielordner in iCloud Drive wählen, dann sind die Dateien auf dem iPad und"))
        print(dim("  lassen sich in GoodNotes über „Importieren“ › iCloud Drive übernehmen."))
        config["goodnotes"] = False
    else:
        print("  Neue PDFs werden mit Goodnotes auf dem Mac geöffnet und über iCloud aufs iPad")
        print("  synchronisiert. Sie landen unsortiert in GoodNotes; der Bestand wird nicht importiert.")
        config["goodnotes"] = yes("GoodNotes-Import einschalten?", config["goodnotes"])
        if config["goodnotes"] and yes("Jetzt mit einer Test-Seite ausprobieren?"):
            try:
                goodnotes.test_import()
                config["goodnotes"] = yes("Ist „ILIAS-Sync Test“ in GoodNotes erschienen?")
            except (goodnotes.GoodNotesError, OSError, subprocess.CalledProcessError) as error:
                fail(f"Test fehlgeschlagen: {error}")
                config["goodnotes"] = False
        ok("GoodNotes-Import " + ("an" if config["goodnotes"] else "aus"))

    print(f"\n  {bold('Notion')} " + dim("(To-do-Liste: je Fach ein Tab, abhaken nach dem Bearbeiten)"))
    if config["notion"]:
        if yes("Notion-Liste ist eingerichtet. Ausschalten?", False):
            notion_todo.remove(config, state)
    elif yes("Notion-To-do-Liste einrichten?", False):
        notion_todo.setup(config)
    ok("Notion-Liste " + ("an" if config["notion"] else "aus"))

    print(f"\n  {bold('Telegram')} " + dim("(Nachricht bei neuen Dateien und bei Problemen, über einen eigenen Bot)"))
    if config["telegram"]:
        if yes("Telegram ist eingerichtet. Ausschalten?", False):
            telegram_bot.remove()
            config["telegram"] = False
    elif yes("Telegram-Benachrichtigungen einrichten?", False):
        config["telegram"] = telegram_bot.setup()
    ok("Telegram " + ("an" if config["telegram"] else "aus"))


def last_sync_line() -> str:
    if not LOG_FILE.exists():
        return "noch keiner"
    lines = [line for line in LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines() if "  ILIAS: " in line]
    return lines[-1][:16] + " · " + lines[-1][18:].replace("ILIAS: ", "") if lines else "noch keiner"


# --- Befehle ------------------------------------------------------------------


def cmd_setup() -> None:
    header()
    print("\n  Die Einrichtung dauert etwa fünf Minuten. Dein Passwort landet nur im")
    print("  macOS-Schlüsselbund und geht ausschließlich an den Login-Server der Uni.")
    config, state = core.load_config(), core.load_state()

    step(1, 4, "ILIAS-Anmeldung")
    result = ask_credentials(config)
    if result is None:
        sys.exit(1)
    config["courses"].update(result["new"])
    core.save_config(config)

    step(2, 4, "Deine Kurse " + dim("(aus ILIAS erkannt, Ordnernamen änderbar)"))
    edit_courses(config, state)
    core.save_config(config)

    step(3, 4, "Zielordner")
    choose_target(config, state)
    core.save_config(config)
    core.save_state(state)

    step(4, 4, "Zusatzfunktionen " + dim("(alle optional)"))
    modules(config, state)
    print(f"\n  {bold('Zeitplan')}")
    print("  Wie oft soll ILIAS geprüft werden? (jeweils zwischen 6 und 23 Uhr)")
    config["interval_minutes"] = [30, 60][choose(["alle 30 Minuten " + dim("(empfohlen)"), "stündlich"])]
    core.save_config(config)
    core.save_state(state)

    print(f"\n  {bold('Erster Abgleich')} " + dim("(lädt alle Dateien, je nach Kursen einige Minuten)"))
    sync.run()
    schedule.start(config["interval_minutes"])
    print()
    ok(f"Fertig. ILIAS wird ab jetzt {'alle 30 Minuten' if config['interval_minutes'] == 30 else 'stündlich'} geprüft.")
    print(yellow("  Falls macOS gleich fragt, ob „python3.13“ auf einen Ordner zugreifen darf:"))
    print(yellow("  „Erlauben“ wählen, sonst kann der automatische Abgleich nicht speichern."))
    print(f"\n  Übersicht und Einstellungen jederzeit mit {bold('ilias-sync')} im Terminal.")


def cmd_status() -> None:
    config = core.load_config()
    header()
    if not config["uni_id"]:
        print(f"\n  Noch nicht eingerichtet: {bold('ilias-sync einrichten')}")
        return
    active = schedule.is_active()
    selected = sum(1 for s in config["courses"].values() if s["sync"])
    interval = "alle 30 Min." if config["interval_minutes"] == 30 else "stündlich"
    print()
    print(f"  Automatischer Abgleich  {green('an') if active else red('aus')}" + dim(f"  ({interval}, 6–23 Uhr)"))
    print(f"  Letzter Abgleich        {last_sync_line()}")
    print(f"  Uni-ID                  {config['uni_id']}")
    print(f"  Zielordner              {pretty_path(config['target_dir'])}")
    print(f"  Kurse                   {selected} von {len(config['courses'])} synchronisiert")
    flags = [("GoodNotes", config["goodnotes"]), ("Notion", bool(config["notion"])), ("Telegram", config["telegram"])]
    print("  Zusatzfunktionen        " + " · ".join(f"{name} {'an' if on else 'aus'}" for name, on in flags))


def cmd_now() -> None:
    print(dim("  Abgleich läuft …"))
    sync.run()


def cmd_courses() -> None:
    config, state = core.load_config(), core.load_state()
    with no_sync_running():
        if yes("Kursliste vorher in ILIAS aktualisieren?", True):
            try:
                config["courses"].update(sync.run_pferd(config, list_only=True)["new"])
            except sync.CrawlFailed as failure:
                fail(f"ILIAS nicht erreichbar ({failure}); bekannte Kurse werden angezeigt.")
        edit_courses(config, state)
        core.save_config(config)
        core.save_state(state)
    ok("Gespeichert. Gilt ab dem nächsten Abgleich.")


def cmd_folder() -> None:
    config, state = core.load_config(), core.load_state()
    with no_sync_running():
        choose_target(config, state)
        core.save_config(config)
        core.save_state(state)
    print(dim("  Beim nächsten Abgleich werden alle Dateien in den neuen Ordner kopiert."))


def cmd_modules() -> None:
    config, state = core.load_config(), core.load_state()
    modules(config, state)
    core.save_config(config)
    core.save_state(state)


def cmd_access() -> None:
    config = core.load_config()
    with no_sync_running():
        if ask_credentials(config) is not None:
            core.save_config(config)


def cmd_start() -> None:
    config = core.load_config()
    schedule.start(config["interval_minutes"])
    ok("Automatischer Abgleich an. Ein erster Abgleich läuft gerade im Hintergrund.")


def cmd_stop() -> None:
    schedule.stop()
    ok("Automatischer Abgleich angehalten. Er bleibt aus, bis du „ilias-sync start“ ausführst.")


def cmd_log() -> None:
    if LOG_FILE.exists():
        print("\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]))


def cmd_uninstall() -> None:
    config = core.load_config()
    print("  Entfernt ILIAS-Sync mit allen Einstellungen und gespeicherten Zugangsdaten.")
    if config["target_dir"]:
        print(f"  Deine Dateien in {pretty_path(config['target_dir'])} bleiben erhalten.")
    if ask("Zum Bestätigen „ja“ eingeben") != "ja":
        print("  Abgebrochen.")
        return
    schedule.remove()
    for account in filter(None, [config["uni_id"], "Notion", "Telegram-Token", "Telegram-Chat"]):
        _forget_password(account)
    COMMAND_LINK.unlink(missing_ok=True)
    if ZPROFILE.exists():
        lines, skipping = [], False
        for line in ZPROFILE.read_text(encoding="utf-8").splitlines():
            skipping = (skipping or line == PATH_BLOCK[0]) and line != PATH_BLOCK[1]
            if not skipping and line != PATH_BLOCK[1]:
                lines.append(line)
        ZPROFILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for log_file in (LOG_FILE, PFERD_LOG):
        log_file.unlink(missing_ok=True)
    shutil.rmtree(APP_DIR, ignore_errors=True)
    ok("ILIAS-Sync ist entfernt.")
    if config["notion"]:
        print("  Noch von Hand: in Notion unter Verbindungen die Verbindung „ILIAS-Sync“ löschen.")
    if config["telegram"]:
        print("  Noch von Hand: in Telegram bei @BotFather mit /deletebot den Bot löschen.")


def cmd_menu() -> None:
    cmd_status()
    if not core.load_config()["uni_id"]:
        return
    actions = [
        ("Jetzt abgleichen", cmd_now),
        ("Kurse auswählen oder umbenennen", cmd_courses),
        ("Zielordner ändern", cmd_folder),
        ("Zusatzfunktionen (GoodNotes, Notion, Telegram)", cmd_modules),
        ("Automatischen Abgleich " + ("anhalten" if schedule.is_active() else "fortsetzen"),
         cmd_stop if schedule.is_active() else cmd_start),
        ("Protokoll anzeigen", cmd_log),
        ("Uni-ID oder Passwort ändern", cmd_access),
        ("Deinstallieren", cmd_uninstall),
        ("Beenden", lambda: None),
    ]
    print()
    actions[choose([label for label, _ in actions])][1]()


COMMANDS = {
    "einrichten": cmd_setup, "status": cmd_status, "jetzt": cmd_now, "kurse": cmd_courses,
    "ordner": cmd_folder, "module": cmd_modules, "zugang": cmd_access, "start": cmd_start,
    "stop": cmd_stop, "log": cmd_log, "deinstallieren": cmd_uninstall,
}


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in ("hilfe", "help", "-h", "--help"):
        print(__doc__)
        return
    if command and command not in COMMANDS:
        print(f"  Unbekannter Befehl „{command}“.\n{__doc__}")
        sys.exit(1)
    try:
        COMMANDS.get(command, cmd_menu)()
    except (KeyboardInterrupt, EOFError):
        print("\n  Abgebrochen.")


if __name__ == "__main__":
    main()
