"""Markdown-Fassung jedes Kursdokuments (ILIAS und eigene Dateien) für Claude und andere KI-Werkzeuge.

Statt bei jeder Anfrage die PDF zu öffnen, arbeitet die KI mit einer schlanken Textfassung:
eine Datei pro Dokument unter `<Datenordner>/Markdown/<Kurs>/<Ordner>/<Datei>.md`, gleiche Struktur wie
der Spiegel, Seiten als „## Seite n“. Das Original (PDF) bleibt für dich unverändert im Spiegel.

- Mit Text (PDF, PowerPoint, Word, Text): ohne KI aus dem Dokument gelesen, im Hintergrund für alle Dateien.
- Gescannte PDFs (kaum Text): Claude liest die Seiten einmal als Bild und schreibt das Markdown
  (nur auf Anforderung, damit kein Abo-Kontingent unbemerkt verbraucht wird).
Neu erstellt wird nur, wenn sich der Inhalt der Datei geändert hat (Hash im Kopf der .md-Datei).
"""

import re
from pathlib import Path

import ai
import claude_cli
import core

MD_DIR = core.APP_DIR / "Markdown"
EXTENSIONS = {".pdf", ".txt", ".md", ".pptx", ".docx"}
HEADER = re.compile(r"^<!-- studyhub quelle=\"(?P<quelle>[^\"]*)\" hash=(?P<hash>\w+) art=(?P<art>\w+) -->\n")
SCAN_SYSTEM = (
    "Du überträgst gescannte Vorlesungsunterlagen in Markdown. Gib nur den Inhalt wieder, nichts erfinden. "
    "Formeln in einfacher Textschreibweise, Tabellen als Markdown-Tabellen, Grafiken kurz in [eckigen Klammern] "
    "beschreiben. Jede Seite beginnt mit „## Seite n“."
)
SCAN_TURNS = 40  # Claude liest große PDFs in Abschnitten (mehrere Read-Aufrufe)


def md_path(relative: str) -> Path:
    return MD_DIR / f"{relative}.md"


def _header(relative: str, digest: str, art: str) -> str:
    return f'<!-- studyhub quelle="{relative.replace(chr(34), "")}" hash={digest} art={art} -->\n'


def read_header(file: Path) -> dict | None:
    try:
        with open(file, encoding="utf-8") as handle:
            match = HEADER.match(handle.readline())
    except OSError:
        return None
    return match.groupdict() if match else None


def from_pages(title: str, pages: list[str]) -> str:
    """Seitenweiser Text → Markdown mit „## Seite n“ (leere Seiten fallen weg)."""
    parts = [f"# {title}"]
    for number, text in enumerate(pages, 1):
        text = "\n".join(line.rstrip() for line in text.strip().splitlines())  # PDF-Zeilen ohne Füllzeichen
        if text := re.sub(r"\n{3,}", "\n\n", text):
            parts.append(f"## Seite {number}\n\n{text}")
    return "\n\n".join(parts) + "\n"


def status(path: Path, relative: str, digest: str | None = None) -> str:
    """aktuell | veraltet | fehlt"""
    head = read_header(md_path(relative))
    if not head:
        return "fehlt"
    return "aktuell" if head["hash"] == (digest or ai.file_hash(path)) else "veraltet"


def ensure(path: Path, relative: str, use_claude: bool = False, model: str | None = None) -> tuple[str, str]:
    """Markdown der Datei anlegen oder auffrischen. Liefert (Markdown ohne Kopfzeile, art).
    art: text | claude | gescannt (gescannt = kaum Text und Claude nicht genutzt)."""
    if path.suffix.lower() not in EXTENSIONS:
        raise ai.AIError(f"Für {path.suffix or 'diese Datei'} gibt es keine Markdown-Fassung")
    digest = ai.file_hash(path)
    target = md_path(relative)
    head = read_header(target)
    if head and head["hash"] == digest and (head["art"] != "gescannt" or not use_claude):
        return _body(target), head["art"]
    pages = ai.extract_pages(path)
    if ai.is_scanned(pages, path) and path.suffix.lower() == ".pdf":
        if use_claude:
            text, art = _scan_with_claude(path, model or ai.DEFAULT_CLAUDE_MODEL), "claude"
        else:
            text, art = from_pages(path.stem, pages), "gescannt"
    else:
        text, art = from_pages(path.stem, pages), "text"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_header(relative, digest, art) + text, encoding="utf-8")
    return text, art


def _body(file: Path) -> str:
    text = file.read_text(encoding="utf-8")
    return text.split("\n", 1)[1] if text.startswith("<!-- studyhub") else text


def _scan_with_claude(path: Path, model: str) -> str:
    prompt = (f"Lies die PDF-Datei „{path}“ vollständig mit dem Werkzeug Read (große Dateien in Abschnitten "
              f"über den Parameter pages) und gib den gesamten Inhalt als Markdown aus. Beginne mit „# {path.stem}“.")
    try:
        result = claude_cli.run(prompt, SCAN_SYSTEM, model, read_dirs=[path.parent], max_turns=SCAN_TURNS)
    except claude_cli.CLIError as error:
        raise ai.AIError(str(error)) from None
    return str(result["output"]).strip() + "\n"


def ensure_all(files: list[tuple[Path, str]], stop=lambda: False) -> int:
    """Hintergrund: Markdown für alle Dateien mit Text (ohne KI). Liefert die Zahl neu erstellter Fassungen."""
    made = 0
    for path, relative in files:
        if stop():
            break
        if path.suffix.lower() not in EXTENSIONS or not path.is_file():
            continue
        head = read_header(md_path(relative))
        try:
            if head and head["hash"] == ai.file_hash(path):
                continue
            ensure(path, relative)
            made += 1
        except ai.AIError as error:
            core.log(f"Markdown: {relative} übersprungen ({error})")
    return made


def remove_orphans(known: set[str]) -> int:
    """Markdown-Fassungen löschen, deren Quelle es im Spiegel nicht mehr gibt (nur eigene .md-Dateien)."""
    removed = 0
    for file in MD_DIR.rglob("*.md") if MD_DIR.exists() else []:
        head = read_header(file)
        if head and head["quelle"] not in known:
            file.unlink()
            removed += 1
    return removed


def rename_folder(old: str, new: str) -> None:
    """Kursordner umbenannt: Markdown-Ordner mitziehen."""
    source, target = MD_DIR / old, MD_DIR / new
    if source.is_dir() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        for file in target.rglob("*.md"):
            head = read_header(file)
            if head and (moved := core.moved_path(head["quelle"], old, new)):
                text = _body(file)
                file.write_text(_header(moved, head["hash"], head["art"]) + text, encoding="utf-8")


def course_markdown(course: str, files: list[tuple[Path, str]], limit: int) -> tuple[str, list[str]]:
    """Alle Markdown-Fassungen eines Kurses hintereinander, höchstens limit Zeichen (gleichmäßig gekürzt).
    Liefert (Text, verwendete Pfade)."""
    texts = []
    for path, relative in files:
        if relative.split("/", 1)[0] != course or path.suffix.lower() not in EXTENSIONS:
            continue
        try:
            text, art = ensure(path, relative)
        except ai.AIError:
            continue
        if art != "gescannt":
            texts.append((relative, text))
    if not texts:
        return "", []
    share = max(2000, limit // len(texts))
    parts = []
    for relative, text in texts:
        if len(text) > share:
            text = text[:share] + "\n\n[… gekürzt]\n"
        parts.append(f"<dokument pfad=\"{relative}\">\n{text}</dokument>")
    return "\n\n".join(parts)[:limit], [r for r, _ in texts]
