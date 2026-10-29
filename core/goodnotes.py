"""GoodNotes-Import (experimentell, optional).

GoodNotes hat keine Schnittstelle und keinen überwachten Import-Ordner. Dieses Modul
öffnet neue PDFs mit der GoodNotes-App auf dem Mac ("Öffnen mit"), GoodNotes
übernimmt sie in die Bibliothek und synchronisiert sie per iCloud aufs iPad.
Voraussetzungen: Goodnotes für macOS (braucht macOS 15.7 oder neuer) mit
aktivierter iCloud-Synchronisierung. Die Dateien landen unsortiert in GoodNotes.
"""

import subprocess
import tempfile
import time
from pathlib import Path

BUNDLE_ID = "com.goodnotesapp.x"
MAX_PER_RUN = 20  # nicht Dutzende Fenster auf einmal öffnen


class GoodNotesError(Exception):
    pass


def find_app() -> Path | None:
    for candidate in (Path("/Applications/Goodnotes.app"), Path("/Applications/GoodNotes.app")):
        if candidate.exists():
            return candidate
    found = subprocess.run(
        ["mdfind", f"kMDItemCFBundleIdentifier == '{BUNDLE_ID}'"], capture_output=True, text=True, check=False
    ).stdout.splitlines()
    return Path(found[0]) if found else None


def import_files(paths: list[Path]) -> list[Path]:
    """Öffnet PDFs im Hintergrund mit GoodNotes. Liefert die übergebenen Dateien."""
    app = find_app()
    if app is None:
        raise GoodNotesError("Goodnotes für Mac nicht gefunden")
    imported = []
    for path in [p for p in paths if p.suffix.lower() == ".pdf"][:MAX_PER_RUN]:
        result = subprocess.run(["open", "-g", "-a", str(app), str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            raise GoodNotesError(result.stderr.strip() or f"open fehlgeschlagen ({path.name})")
        imported.append(path)
        time.sleep(3)  # GoodNotes Zeit für den Import lassen
    return imported


def test_import() -> None:
    """Importiert eine einseitige Test-PDF, damit man das Verhalten vorher sieht."""
    with tempfile.TemporaryDirectory() as tmp:
        text, pdf = Path(tmp, "test.txt"), Path(tmp, "StudyHub Test.pdf")
        text.write_text("StudyHub: Test-Import in GoodNotes.\nDiese Seite kann gelöscht werden.\n", encoding="utf-8")
        with open(pdf, "wb") as out:
            subprocess.run(["cupsfilter", "-i", "text/plain", "-m", "application/pdf", str(text)], stdout=out,
                           stderr=subprocess.DEVNULL, check=True)
        import_files([pdf])
        time.sleep(5)  # GoodNotes liest die Datei, bevor der Ordner gelöscht wird
