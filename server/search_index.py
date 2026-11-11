"""Volltextsuche über die Kursunterlagen (Suche oben in StudyHub).

Der Text jeder Datei liegt seitenweise in einer SQLite-Volltextsuche (FTS5). index_all() nimmt im
Hintergrund neue oder geänderte Dateien auf; unlesbare oder gescannte Dateien werden bis zur
nächsten Änderung übersprungen. Früher Teil des Sprachtutors (Branch archiv/sprachtutor).
"""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import ai
import core

DB_FILE = core.APP_DIR / "suchindex.sqlite3"
EXTENSIONS = {".pdf", ".txt", ".md", ".pptx", ".docx"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT NOT NULL, course TEXT NOT NULL,
                                  pages INTEGER NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(path UNINDEXED, course UNINDEXED, page UNINDEXED, text,
                                                    tokenize = 'unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS skipped (path TEXT PRIMARY KEY, hash TEXT NOT NULL, reason TEXT NOT NULL);
"""


class Unreadable(Exception):
    pass


def connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _hash(path: Path, relative: str) -> str:
    """Inhalt der Datei, vor dem teuren Lesen über Größe und Änderungszeit abgekürzt."""
    stat = path.stat()
    return f"{relative}:{stat.st_size}:{stat.st_mtime_ns}"


def index_file(db: sqlite3.Connection, path: Path, relative: str, digest: str) -> None:
    """Legt den Text der Datei seitenweise in die Volltextsuche."""
    try:
        pages = ai.extract_pages(path)
    except ai.AIError as error:
        raise Unreadable(str(error)) from None
    if ai.is_scanned(pages, path):
        raise Unreadable(f"{path.name} enthält kaum Text (gescannte Folien)")
    course = relative.split("/", 1)[0]
    with db:
        db.execute("DELETE FROM pages WHERE path = ?", (relative,))
        db.execute("DELETE FROM skipped WHERE path = ?", (relative,))
        db.executemany("INSERT INTO pages (path, course, page, text) VALUES (?, ?, ?, ?)",
                       [(relative, course, n, text) for n, text in enumerate(pages, 1) if text.strip()])
        db.execute("INSERT OR REPLACE INTO files (path, hash, course, pages) VALUES (?, ?, ?, ?)",
                   (relative, digest, course, len(pages)))


def index_all(files: list[tuple[Path, str]], stop=lambda: False) -> int:
    """Text aller Dateien in die Volltextsuche. Liefert die Zahl neu aufgenommener Dateien."""
    with closing(connect()) as db:
        known = {r["path"]: r["hash"] for r in db.execute("SELECT path, hash FROM files")}
        skipped = {r["path"]: r["hash"] for r in db.execute("SELECT path, hash FROM skipped")}
        added = 0
        for path, relative in files:
            if stop():
                break
            if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                continue
            digest = _hash(path, relative)
            if digest in (known.get(relative), skipped.get(relative)):
                continue
            try:
                index_file(db, path, relative, digest)
                added += 1
            except Unreadable as error:
                with db:
                    db.execute("INSERT OR REPLACE INTO skipped (path, hash, reason) VALUES (?, ?, ?)",
                               (relative, digest, str(error)))
    return added


def search_material(text: str, limit: int = 20) -> list[dict]:
    """Seiten, die alle Wörter (auch als Wortanfang) enthalten, beste zuerst.
    Im Ausschnitt markieren \x02 und \x03 die Treffer."""
    words = re.findall(r"\w{2,}", text.lower())[:8]
    if not words:
        return []
    query = " ".join(f'"{w}"*' for w in words)
    with closing(connect()) as db:
        rows = db.execute("SELECT path, page, snippet(pages, 3, char(2), char(3), ' … ', 14) AS snippet FROM pages "
                          "WHERE pages MATCH ? ORDER BY rank LIMIT ?", (query, limit)).fetchall()
    return [dict(r) for r in rows]


def index_count() -> int:
    """Dateien, die die Suche schon kennt: aufgenommen oder als unlesbar bzw. gescannt übersprungen."""
    with closing(connect()) as db:
        return db.execute("SELECT (SELECT COUNT(*) FROM files) + (SELECT COUNT(*) FROM skipped "
                          "WHERE path NOT IN (SELECT path FROM files))").fetchone()[0]


def rename_folder(old: str, new: str) -> None:
    """Kursordner umbenannt: Einträge ziehen mit (alles hängt am Pfad)."""
    with closing(connect()) as db, db:
        for table in ("files", "pages", "skipped"):
            for (path,) in db.execute(f"SELECT DISTINCT path FROM {table}").fetchall():
                if moved := core.moved_path(path, old, new):
                    if table == "skipped":
                        db.execute("UPDATE skipped SET path = ? WHERE path = ?", (moved, path))
                    else:
                        db.execute(f"UPDATE {table} SET path = ?, course = ? WHERE path = ?",
                                   (moved, moved.split("/", 1)[0], path))
