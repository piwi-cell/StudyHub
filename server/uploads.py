"""Eigene Dateien in einen Kurs hochladen (zusätzlich zu dem, was von ILIAS kommt).

Hochgeladene Dateien landen im Spiegel unter <Kurs>/Eigene Dateien/. Dort behandelt die App sie
wie ILIAS-Dateien: StudyHub zeigt sie, KI und Tutor arbeiten damit, und der nächste Abgleich
kopiert sie in den Zielordner. PFERD läuft mit on_conflict = no-delete und löscht sie nicht.
"""

import re
from pathlib import Path

import core

FOLDER = "Eigene Dateien"
SUMMARY_FOLDER = "Eigene Zusammenfassungen"  # StudyHub zeigt sie im Tab „Zusammenfassung“
MAX_TEXT = 200_000  # Zeichen für eine in StudyHub geschriebene Zusammenfassung
MAX_BYTES = 100_000_000
# Nur Unterlagen: „Öffnen“ startet Dateien mit der Standard-App, ausführbare Typen sind daher tabu
ALLOWED = {
    ".pdf", ".txt", ".md", ".csv", ".tex", ".rtf",
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".odp", ".ods",
    ".pages", ".key", ".numbers", ".png", ".jpg", ".jpeg", ".gif", ".heic", ".zip",
}


class UploadError(Exception):
    pass


def course_folders(config: dict) -> set[str]:
    """Kursordner, in die hochgeladen werden darf: konfigurierte Kurse und vorhandene Ordner im Spiegel."""
    names = {s["name"].split("/")[0] for s in config.get("courses", {}).values()}
    if core.MIRROR_DIR.exists():
        names |= {p.name for p in core.MIRROR_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")}
    return {core.nfc(n) for n in names}


def clean_name(filename: str) -> str:
    name = core.nfc(Path(filename.replace("\\", "/")).name).strip()
    name = re.sub(r"[\x00-\x1f:/]", "-", name)
    if not name or name.startswith("."):
        raise UploadError("Ungültiger Dateiname")
    if Path(name).suffix.lower() not in ALLOWED:
        raise UploadError(f"{name}: Dateityp wird nicht unterstützt (erlaubt: PDF, Office, Text, Bilder, ZIP)")
    stem, suffix = Path(name).stem[:150], Path(name).suffix.lower()
    return f"{stem}{suffix}"


def target_path(config: dict, course: str, filename: str, folder_name: str = FOLDER) -> Path:
    """Freier Zielpfad im Spiegel; vorhandene Dateien werden nie überschrieben („Name (2).pdf“)."""
    course = core.nfc(course)
    if course not in course_folders(config):
        raise UploadError(f"Unbekannter Kurs: {course}")
    if folder_name not in (FOLDER, SUMMARY_FOLDER):
        raise UploadError("Ungültiger Ordner")
    name = clean_name(filename)
    folder = (core.MIRROR_DIR / course / folder_name).resolve()
    if core.MIRROR_DIR.resolve() not in folder.parents:
        raise UploadError("Ungültiger Kurs")
    path, n = folder / name, 2
    while path.exists():
        path, n = folder / f"{Path(name).stem} ({n}){Path(name).suffix}", n + 1
    return path


def save(config: dict, course: str, filename: str, chunks, folder_name: str = FOLDER) -> str:
    """Speichert die Datei (chunks: iterierbare Bytes-Blöcke). Liefert den relativen Pfad im Spiegel."""
    path = target_path(config, course, filename, folder_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp, size = path.with_name(f".{path.name}.upload"), 0
    try:
        with open(tmp, "wb") as out:
            for chunk in chunks:
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UploadError(f"{path.name}: größer als 100 MB")
                out.write(chunk)
        if size == 0:
            raise UploadError(f"{path.name}: Datei ist leer")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    relative = core.nfc(path.relative_to(core.MIRROR_DIR.resolve()).as_posix())
    core.log(f"Upload: {relative} ({size // 1000} KB)")
    return relative


def save_summary_text(config: dict, course: str, title: str, text: str) -> str:
    """In StudyHub geschriebene Zusammenfassung als Markdown-Datei unter „Eigene Zusammenfassungen“."""
    title = re.sub(r"\s+", " ", title).strip()[:120]
    if not title:
        raise UploadError("Bitte einen Titel angeben")
    if not text.strip():
        raise UploadError("Die Zusammenfassung ist leer")
    if len(text) > MAX_TEXT:
        raise UploadError("Die Zusammenfassung ist zu lang (höchstens 200.000 Zeichen)")
    return save(config, course, f"{title}.md", [text.encode("utf-8")], SUMMARY_FOLDER)
