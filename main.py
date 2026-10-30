"""Startet ILIAS-Sync als Mac-App: lokale API im Hintergrund, Oberfläche in einem nativen Fenster.

  python main.py             App öffnen (StudyHub)
  python main.py --demo      mit Beispieldaten (eigener Datenordner, kein ILIAS-Abruf)
  python main.py --browser   nur Server starten und im Browser öffnen (zum Entwickeln)
"""

import argparse
import fcntl
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_core():
    """core importieren wie server/app.py: core legt beim Import fest, mit welchem Python PFERD und die
    Hintergrund-Jobs laufen (ILIAS_SYNC_PYTHON). Ohne Vorgabe wäre das das venv der Terminal-Version
    (<Datenordner>/venv), das es meist nicht gibt: Abgleich und Jobs schlügen fehl."""
    os.environ.setdefault("ILIAS_SYNC_APP", "1")
    os.environ.setdefault("ILIAS_SYNC_PYTHON", sys.executable)
    sys.path.insert(0, str(ROOT / "core"))
    import core  # liest auch ILIAS_SYNC_HOME (Demo) beim Import

    return core


def instance_lock(app_dir: Path):
    """Pro Datenordner läuft die App nur einmal: Zwei Instanzen würden sich beim Telegram-Bot gegenseitig
    abweisen (HTTP 409) und Bibliotheken und Tutor doppelt bearbeiten. None, wenn sie schon läuft;
    sonst die gesperrte Datei (offen halten, solange die App läuft; macOS gibt sie beim Beenden frei)."""
    app_dir.mkdir(parents=True, exist_ok=True)
    lock = open(app_dir / ".app.lock", "a")  # nicht "w": würde Port und PID der laufenden App löschen
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


class ShowListener:
    """Die laufende App hört auf 127.0.0.1 an einem freien Port, den sie in die Sperrdatei schreibt (mit ihrer
    Prozess-ID). Öffnet man die App ein zweites Mal, meldet sich diese dort und die laufende holt ihr Fenster
    nach vorn (on_show), statt dass nur ein Hinweis erscheint. Ohne Token: Mehr als das Fenster zeigen geht nicht."""

    def __init__(self, lock):
        self.on_show = None  # setzt main(), sobald das Fenster existiert
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        lock.truncate(0)
        lock.write(f"{self.sock.getsockname()[1]} {os.getpid()}\n")
        lock.flush()
        threading.Thread(target=self._serve, daemon=True, name="show-listener").start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                if self.on_show:
                    try:
                        self.on_show()
                    except Exception as exc:  # ein Fehler hier darf die App nicht beenden
                        print(f"Fenster nach vorn holen fehlgeschlagen: {exc}", file=sys.stderr)
                conn.sendall(b"ok\n")


def bring_to_front(app_dir: Path) -> bool:
    """Zweiter Start: die laufende App bitten, ihr Fenster zu zeigen. False, wenn sie nicht erreichbar ist
    (z. B. gerade erst gestartet oder ältere Version ohne ShowListener)."""
    try:
        port, pid = (int(part) for part in (app_dir / ".app.lock").read_text().split())
    except (OSError, ValueError):
        return False
    yield_activation(pid)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as conn:
            return conn.recv(16).startswith(b"ok")
    except OSError:
        return False


def yield_activation(pid: int) -> None:
    """Seit macOS 14 darf eine App im Hintergrund sich nicht selbst nach vorn holen; die gerade gestartete
    (aktive) zweite App gibt die Aktivierung deshalb an die laufende ab."""
    try:
        from AppKit import NSApplication, NSApplicationActivateAllWindows, NSRunningApplication
    except ImportError:
        return
    running = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if running is None:
        return
    me = NSApplication.sharedApplication()
    if hasattr(me, "yieldActivationToApplication_"):  # macOS 14+
        me.yieldActivationToApplication_(running)
    running.activateWithOptions_(NSApplicationActivateAllWindows)


def activate_self() -> None:
    try:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper
    except ImportError:
        return
    app = NSApplication.sharedApplication()
    if hasattr(app, "activate"):  # macOS 14+: kooperativ, wirkt nach yield_activation der zweiten App
        AppHelper.callAfter(app.activate)
    else:
        AppHelper.callAfter(app.activateIgnoringOtherApps_, True)


def already_running() -> None:
    message = ("StudyHub ist schon geöffnet, z. B. aus „Programme“ oder aus dem Projektordner. "
               "Bitte das offene Fenster nutzen oder es zuerst beenden (⌘Q).")
    print(message, file=sys.stderr)
    import subprocess
    try:  # Hinweis auch beim Start per Doppelklick sichtbar (ohne Terminal)
        subprocess.run(["osascript", "-e", f'display alert "StudyHub" message "{message}"'], check=False)
    except OSError:
        pass


def mac_app_identity() -> None:
    """Name und Symbol in Dock und Menüleiste: sonst zeigt macOS „Python“ mit Python-Symbol."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
    except ImportError:
        return
    info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
    if info is not None:
        info["CFBundleName"] = "StudyHub"
    icon = ROOT / "assets/icon-512.png"
    if icon.exists():
        NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(icon)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    if args.demo:
        os.environ["ILIAS_SYNC_HOME"] = str(ROOT / "demo-data")
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts/demo_data.py")], check=True)
    os.environ.setdefault("ILIAS_SYNC_TOKEN", secrets.token_urlsafe(24))
    token = os.environ["ILIAS_SYNC_TOKEN"]

    core = load_core()
    lock = instance_lock(core.APP_DIR)
    if lock is None:
        if not bring_to_front(core.APP_DIR):
            already_running()
        return
    listener = ShowListener(lock)

    import uvicorn

    sys.path.insert(0, str(ROOT / "server"))
    from app import app

    port = args.port or free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    # Ohne Einrichtung führt StudyHub selbst zum Uni-Login (#/einrichtung)
    start = "/ui/studyhub/index.html"
    if args.browser:
        url = f"http://127.0.0.1:{port}{start}?t={token}"
        print(f"StudyHub läuft: {url}")
        webbrowser.open(url)
        listener.on_show = lambda: webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    mac_app_identity()
    import webview

    class Bridge:
        def pick_folder(self):
            result = window.create_file_dialog(webview.FileDialog.FOLDER)
            return result[0] if result else None

        def pick_files(self):
            # Nativer Dialog statt <input type="file">: im App-Fenster (WebKit) zuverlässiger
            result = window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
            return list(result) if result else []

    title = "StudyHub · Demo" if args.demo else "StudyHub"  # Demo sofort erkennbar
    window = webview.create_window(
        title, f"http://127.0.0.1:{port}{start}?t={token}&v=1", js_api=Bridge(),
        width=1240, height=800, min_size=(980, 620), vibrancy=True, text_select=True,
    )

    def show_window():
        window.restore()  # aus dem Dock zurück, falls minimiert
        window.show()
        activate_self()

    listener.on_show = show_window
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
