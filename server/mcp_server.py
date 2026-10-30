"""Lokaler MCP-Server (stdio): Claude Desktop übernimmt die KI-Arbeit mit dem normalen Claude-Abo.

Claude Desktop startet dieses Skript selbst und spricht über stdin/stdout mit ihm. Claude liest
damit Kurse, Dateien und den StudyHub-Stand und speichert Lernthemen und Lernkarten in den
KI-Cache der jeweiligen Datei, dazu Prüfungsfragen für den Sprachtutor (tutor.sqlite3).
Die App zeigt sie danach wie selbst erzeugte Ergebnisse an.
Es gibt bewusst keine Werkzeuge zum Löschen, Senden oder für Einstellungen.

Start (Pfade siehe docs/mcp.md):
  .venv/bin/python server/mcp_server.py          echte Daten
  .venv/bin/python server/mcp_server.py --demo   Beispieldaten aus ./demo-data
"""

import html
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

ROOT = Path(__file__).resolve().parent.parent

# Datenordner festlegen, bevor core ihn beim Import liest (wie main.py --demo)
if __name__ == "__main__" and "--demo" in sys.argv[1:]:
    os.environ["ILIAS_SYNC_HOME"] = str(ROOT / "demo-data")
    # stdout gehört dem MCP-Protokoll: Ausgaben des Skripts nach stderr
    subprocess.run([sys.executable, str(ROOT / "scripts/demo_data.py")], check=True, stdout=sys.stderr)

from fastapi import HTTPException  # noqa: E402
from mcp.server.mcpserver import Image, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp_types import ToolAnnotations  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

sys.path[:0] = [str(ROOT / "core"), str(ROOT / "server")]
import ai  # noqa: E402
import app  # noqa: E402  (Hilfen wie in der API: mirror_path, file_info, StudyHub-Daten)
import core  # noqa: E402
import integrations  # noqa: E402
import tutor  # noqa: E402

PROVIDER = "claude-desktop"
MAX_FILES = 500
MAX_CHARS = 150_000  # pro read_file-Aufruf, danach mit start_page weiterlesen
MAX_ENTRIES = 200  # Lernplan-Einträge pro Kurs in studyhub_overview
MAX_SUMMARY = 30_000  # Zeichen einer Markdown-Zusammenfassung (save_summary)
MAX_VIEW_PAGES = 4  # Seitenbilder pro view_pages-Aufruf (Bilder belegen viel Kontext)
PAGE_EDGE = 1568  # längste Kante eines Seitenbilds in Pixeln; größere Bilder verkleinert Claude ohnehin

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
# Mit add=true kommen bei jedem Aufruf Fragen dazu, deshalb nicht idempotent
ADD = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

mcp = MCPServer(
    "StudyHub",
    instructions=(
        "Zugriff auf die ILIAS-Kursunterlagen der Uni Mannheim aus der App StudyHub. "
        "Ablauf: list_courses → list_files (Pfad suchen) → read_file (Text lesen) → save_thema, "
        "save_summary bzw. save_flashcards. Steht der Inhalt einer PDF nicht im Text (gescannte Folien, "
        "Grafiken, Kästen als Bild), die Seiten mit view_pages als Bilder ansehen. Für den Sprachtutor "
        "(auch den ElevenLabs Agent) Prüfungsfragen mit save_tutor_questions speichern; list_files zeigt je "
        "Datei tutor_fragen. Arbeite nur mit dem Inhalt des Dokuments, schreibe auf Deutsch (Fachbegriffe "
        "eines englischen Dokuments englisch lassen) und nenne Seitenzahlen. Gespeicherte Ergebnisse "
        "erscheinen sofort in StudyHub. Will die Person lernen oder Stoff verstehen, arbeite als Lerncoach "
        "(Prompt lerncoach): eine Frage auf einmal, erst Hinweis, dann Lösung."
    ),
)


# --- Hilfen -------------------------------------------------------------------


def _resolve(path: str) -> tuple[Path, str]:
    """Pfad relativ zum Spiegel → (Datei, Pfad wie in list_files). Nur echte Dateien im Spiegel."""
    try:
        file = app.mirror_path(path)
    except HTTPException:
        raise ToolError(f"Datei nicht gefunden: {path} (Pfade wie in list_files angeben)") from None
    return file, core.nfc(file.relative_to(core.MIRROR_DIR.resolve()).as_posix())


def _files() -> list[dict]:
    files = app.list_files()["files"]
    cached = app.cached_by_path()
    questions = tutor.counts_by_path()
    for f in files:  # app.file_info kennt das Lernthema und die Tutor-Fragen noch nicht
        f["ai"]["thema"] = bool((cached.get(f["path"]) or {}).get("thema"))
        f["tutor_fragen"] = questions.get(f["path"], 0)
        f["geaendert"] = time.strftime("%Y-%m-%d", time.localtime(f.pop("mtime")))
    return files


def _plain(text: str | None) -> str:
    """StudyHub-Texte sind HTML-maskiert; Claude bekommt sie als einfachen Text."""
    return html.unescape(text or "")


def _result(output, **extra) -> dict:
    return {"provider": PROVIDER, "model": "Claude (Abo, über Claude Desktop)", "input_mode": "MCP",
            "output": output, "created": time.time(), "seconds": 0, **extra}


def summary_from_thema(thema: dict) -> str:
    """Lernthema als Markdown-Zusammenfassung (siehe ai.thema_markdown)."""
    return ai.thema_markdown(thema)


def _store(path: str, task: str, output: dict, overwrite: bool) -> dict:
    file, relative = _resolve(path)
    entry = ai.load_entry(file)
    existing = entry.get(task)
    derived = task == "summary" and existing and existing.get("from_thema")  # aus dem Lernthema: darf weichen
    if existing and not derived and not overwrite:
        raise ToolError(f"Für {relative} gibt es schon ein Ergebnis ({task}). Zum Ersetzen overwrite=true setzen.")
    entry[task] = _result(output)
    answer = {"gespeichert": True, "pfad": relative, "aufgabe": task,
              "hinweis": "Erscheint in StudyHub, sobald die Seite neu lädt."}
    if task == "thema":
        # StudyHub zeigt als Zusammenfassung bisher nur das Markdown-Feld „summary“: daraus mitschreiben,
        # aber nie eine Zusammenfassung ersetzen, die nicht selbst aus einem Lernthema stammt
        summary = entry.get("summary")
        if not summary or summary.get("from_thema"):
            entry["summary"] = _result(summary_from_thema(output), from_thema=True)
            answer["zusammenfassung"] = "aus dem Lernthema mitgespeichert"
        else:
            answer["zusammenfassung"] = "vorhandene Zusammenfassung behalten"
    ai.save_entry(entry, relative)
    label = {"thema": "Lernthema", "summary": "Zusammenfassung", "flashcards": "Lernkarten"}[task]
    core.log(f"MCP: {label} für {relative} gespeichert")
    return answer


# --- Lesen --------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def list_courses() -> dict:
    """Alle Kurse mit Anzahl der Dateien, Lernthemen und Lernkarten-Sätze."""
    config = core.load_config()
    courses: dict[str, dict] = {}
    for f in _files():
        c = courses.setdefault(f["course"], {"kurs": f["course"], "dateien": 0, "lernthemen": 0, "lernkarten": 0})
        c["dateien"] += 1
        c["lernthemen"] += f["ai"]["thema"]
        c["lernkarten"] += f["ai"]["flashcards"]
    for settings in config.get("courses", {}).values():  # aktive Kurse ohne Dateien trotzdem zeigen
        name = settings["name"].split("/")[0]
        if settings.get("sync") and name not in courses:
            courses[name] = {"kurs": name, "dateien": 0, "lernthemen": 0, "lernkarten": 0}
    return {"kurse": sorted(courses.values(), key=lambda c: c["kurs"].casefold())}


@mcp.tool(annotations=READ_ONLY)
def list_files(
    course: Annotated[str | None, Field(description="Kursname wie in list_courses (optional)")] = None,
    query: Annotated[str | None, Field(description="Teil des Datei- oder Ordnernamens (optional)")] = None,
    limit: Annotated[int, Field(ge=1, le=MAX_FILES)] = 100,
) -> dict:
    """Dateien im Spiegel mit KI-Status (wie /api/files). Der Pfad dient als Kennung für die anderen Werkzeuge."""
    files = _files()
    if course:
        files = [f for f in files if f["course"].casefold() == course.strip().casefold()]
    if query:
        needle = core.nfc(query.strip()).casefold()
        files = [f for f in files if needle in f["path"].casefold()]
    return {"dateien": files[:limit], "gesamt": len(files), "gekuerzt": len(files) > limit}


@mcp.tool(annotations=READ_ONLY)
def read_file(
    path: Annotated[str, Field(description="Pfad wie in list_files, z. B. 'Statistik I/Vorlesung/07 Tests.pdf'")],
    start_page: Annotated[int, Field(ge=1, description="Erste Seite (zum Weiterlesen langer Dokumente)")] = 1,
) -> dict:
    """Text einer PDF- oder Textdatei mit Seitenmarken [Seite n]. Lange Dokumente kommen in Teilen."""
    file, relative = _resolve(path)
    try:
        pages = ai.extract_pages(file)
    except ai.AIError as error:
        raise ToolError(str(error)) from None
    if start_page > max(1, len(pages)):
        raise ToolError(f"Das Dokument hat nur {len(pages)} Seiten")
    parts, size, next_page = [], 0, None
    for number in range(start_page, len(pages) + 1):
        text = "\n".join(line.rstrip() for line in pages[number - 1].strip().splitlines())
        part = f"[Seite {number}]\n{text}" if text else ""
        if parts and size + len(part) > MAX_CHARS:
            next_page = number
            break
        parts.append(part[:MAX_CHARS])
        size += len(part)
    result = {"pfad": relative, "seiten": len(pages), "text": "\n\n".join(p for p in parts if p),
              "weiter_ab_seite": next_page}
    if ai.is_scanned(pages, file) and file.suffix.lower() == ".pdf":
        result["hinweis"] = ("Kaum Text gefunden (gescannte Folien oder Inhalte als Bild). Die Seiten mit "
                             "view_pages als Bilder ansehen.")
    return result


def render_pdf_pages(file: Path, start: int, count: int) -> tuple[int, list[bytes]]:
    """PDF-Seiten als JPEG, wie sie auf dem Bildschirm aussehen: auch Bilder, Grafiken und Text ohne
    Textebene. Nutzt Quartz (CoreGraphics) von macOS, das mit pywebview installiert ist.
    Liefert (Seitenzahl der PDF, Bilder ab Seite start)."""
    try:
        import Quartz
        from Foundation import NSURL, NSMutableData
    except ImportError:
        raise ToolError("Seiten als Bild gibt es nur in der Mac-App") from None
    document = Quartz.CGPDFDocumentCreateWithURL(NSURL.fileURLWithPath_(str(file)))
    if document is None:
        raise ToolError("PDF nicht lesbar")
    total = Quartz.CGPDFDocumentGetNumberOfPages(document)
    images = []
    for number in range(start, min(total, start + count - 1) + 1):
        page = Quartz.CGPDFDocumentGetPage(document, number)
        box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFCropBox)
        width, height = box.size.width, box.size.height
        if Quartz.CGPDFPageGetRotationAngle(page) % 180:  # Querformat durch /Rotate
            width, height = height, width
        scale = PAGE_EDGE / max(width, height)
        pixels = (round(width * scale), round(height * scale))
        context = Quartz.CGBitmapContextCreate(None, *pixels, 8, 0, Quartz.CGColorSpaceCreateDeviceRGB(),
                                               Quartz.kCGImageAlphaNoneSkipLast)
        Quartz.CGContextSetRGBFillColor(context, 1, 1, 1, 1)  # weißer Hintergrund statt transparent
        Quartz.CGContextFillRect(context, Quartz.CGRectMake(0, 0, *pixels))
        Quartz.CGContextScaleCTM(context, scale, scale)
        # Drehung und Seitenrand übernimmt Quartz; das Ziel ist so groß wie die Seite (Faktor 1)
        Quartz.CGContextConcatCTM(context, Quartz.CGPDFPageGetDrawingTransform(
            page, Quartz.kCGPDFCropBox, Quartz.CGRectMake(0, 0, width, height), 0, True))
        Quartz.CGContextDrawPDFPage(context, page)
        data = NSMutableData.data()
        destination = Quartz.CGImageDestinationCreateWithData(data, "public.jpeg", 1, None)
        Quartz.CGImageDestinationAddImage(destination, Quartz.CGBitmapContextCreateImage(context),
                                          {Quartz.kCGImageDestinationLossyCompressionQuality: 0.85})
        if not Quartz.CGImageDestinationFinalize(destination):
            raise ToolError(f"Seite {number} ließ sich nicht als Bild speichern")
        images.append(bytes(data))
    return total, images


@mcp.tool(annotations=READ_ONLY)
def view_pages(
    path: Annotated[str, Field(description="Pfad einer PDF wie in list_files")],
    start_page: Annotated[int, Field(ge=1, description="Erste Seite")] = 1,
    count: Annotated[int, Field(ge=1, le=MAX_VIEW_PAGES, description="Anzahl Seiten (höchstens 4)")] = 3,
) -> list[str | Image]:
    """Seiten einer PDF als Bilder, für Inhalte, die read_file nicht als Text liefert: gescannte Folien,
    Grafiken, Tabellen oder Merke-Kästen als Bild. Höchstens 4 Seiten pro Aufruf."""
    file, relative = _resolve(path)
    if file.suffix.lower() != ".pdf":
        raise ToolError("view_pages zeigt nur PDF-Dateien; andere Dateien mit read_file lesen")
    try:
        total, images = render_pdf_pages(file, start_page, count)
    except ToolError:
        raise
    except Exception as error:  # Quartz meldet Fehler uneinheitlich: lesbar weitergeben
        raise ToolError(f"Seiten nicht als Bild darstellbar ({type(error).__name__}: {error})") from None
    if not images:
        raise ToolError(f"Das Dokument hat nur {total} Seiten")
    end = start_page + len(images) - 1
    more = f" Weiter mit start_page={end + 1}." if end < total else ""
    return [f"{relative}: Seite {start_page}–{end} von {total}.{more}",
            *(Image(data=image, format="jpeg") for image in images)]


@mcp.tool(annotations=READ_ONLY)
def read_ai_results(path: Annotated[str, Field(description="Pfad wie in list_files")]) -> dict:
    """Bereits gespeicherte Ergebnisse einer Datei: Lernthema, Lernkarten, Zusammenfassung (Markdown)."""
    file, relative = _resolve(path)
    entry = ai.load_entry(file)

    def output(task: str):
        result = entry.get(task)
        return {"output": result["output"], "von": result.get("model"), "erstellt": result.get("created")} \
            if result else None

    return {"pfad": relative, "thema": output("thema"), "flashcards": output("flashcards"),
            "summary": output("summary")}


@mcp.tool(annotations=READ_ONLY)
def studyhub_overview(
    course: Annotated[str | None, Field(description="Nur diesen Kurs (optional)")] = None,
) -> dict:
    """StudyHub-Stand: Lernplan mit Status je Datei, vorhandene Lernthemen und Dateien ohne Lernthema."""
    data = app.studyhub_data()
    rows = {row["id"]: row for sem in data["daten"]["semester"] for row in sem["module"]}
    modules = []
    for module_id, detail in data["details"].items():
        row = rows.get(module_id, {})
        name = row.get("kurs", module_id)
        if course and name.casefold() != course.strip().casefold():
            continue
        plan = detail["lernplan"]
        entries = [e for k in plan["kapitel"] for e in k["eintraege"]] + \
                  [a for b in plan["bereiche"] for a in b["aufgaben"]]
        with_thema = {t["pfad"] for t in detail["themen"] if t["strukturiert"]}
        modules.append({
            "kurs": name, "fortschritt_prozent": row.get("fortschritt"), "basis": plan["basis"],
            "lernplan": [{"pfad": e["id"], "titel": _plain(e["titel"]), "status": e["status"],
                          "notiz": _plain(e["notiz"])} for e in entries[:MAX_ENTRIES]],
            "lernthemen": [{"titel": _plain(t["titel"]), "pfad": t["pfad"], "strukturiert": t["strukturiert"]}
                           for t in detail["themen"]],
            "lernkarten": detail["karten"]["gesamt"],
            "ohne_lernthema": [e["id"] for e in entries if e["id"] not in with_thema][:MAX_ENTRIES],
        })
    return {"kurse": modules, "letzter_abgleich": data["sync"]["letzter"]}


# --- Schreiben (nur KI-Cache der jeweiligen Datei) ----------------------------


class Formel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120, description="Name der Formel oder des Begriffs, z. B. 'Endwert'")
    text: str = Field(min_length=1, max_length=300, description="Nur die Formel, z. B. 'K_n = K_0 · q^n', "
                      "oder eine Kurzdefinition (höchstens 12 Wörter)")


class Karte(BaseModel):
    model_config = ConfigDict(extra="forbid")
    front: str = Field(min_length=1, max_length=500, description="Vorderseite: eine präzise Frage")
    back: str = Field(min_length=1, max_length=1500, description="Rückseite: kurze, vollständige Antwort (höchstens "
                      "3 Sätze)")


@mcp.tool(annotations=WRITE)
def save_thema(
    path: Annotated[str, Field(description="Pfad wie in list_files")],
    titel: Annotated[str, Field(min_length=1, max_length=120, description="Kurzer Thementitel (2–5 Wörter)")],
    kernidee: Annotated[str, Field(min_length=1, max_length=3000, description="3–4 Sätze, worum es geht")],
    einfacher: Annotated[str, Field(min_length=1, max_length=2000, description="Ganz einfach erklärt, mit "
                                    "Alltagsbeispiel, 2–3 Sätze")],
    formeln: Annotated[list[Formel], Field(max_length=5, description="Wichtigste Formeln (höchstens 5); ohne "
                                           "Formeln die wichtigsten Definitionen als Name + Kurzdefinition")],
    falle: Annotated[str, Field(min_length=1, max_length=1000, description="Typische Klausurfalle, 1–2 Sätze")],
    seite: Annotated[int, Field(ge=0, le=10000, description="Seite mit dem Wichtigsten (0 = unbekannt)")],
    overwrite: Annotated[bool, Field(description="Vorhandenes Lernthema ersetzen")] = False,
) -> dict:
    """Speichert ein Lernthema für eine Datei: die kompakte Lernkarte in StudyHub (Tab „Zusammenfassung“).
    Felder: titel (2–5 Wörter, nicht der Dateiname, ≤ 120 Zeichen), kernidee (3–4 Sätze, ≤ 3000),
    einfacher (2–3 Sätze mit Alltagsbeispiel, ≤ 2000), formeln (0–5 Einträge als Objekte {"name", "text"},
    text nur die Formel ≤ 300 Zeichen, ohne Formeln die wichtigsten Begriffe mit Kurzdefinition),
    falle (typische Klausurfalle, 1–2 Sätze, ≤ 1000), seite (Seite mit dem Wichtigsten, 0 = unbekannt).
    Beispiel für formeln: [{"name": "Endwert", "text": "K_n = K_0 · q^n"}].
    Ausführlichere Inhalte gehören in save_summary. Ohne vorhandene eigene Zusammenfassung wird aus dem Lernthema
    eine erzeugt; eine mit save_summary gespeicherte bleibt unverändert."""
    output = {"titel": titel.strip(), "kernidee": kernidee.strip(), "einfacher": einfacher.strip(),
              "formeln": [f.model_dump() for f in formeln], "falle": falle.strip(), "seite": seite}
    return _store(path, "thema", output, overwrite)


@mcp.tool(annotations=WRITE)
def save_summary(
    path: Annotated[str, Field(description="Pfad wie in list_files")],
    markdown: Annotated[str, Field(min_length=1, max_length=MAX_SUMMARY, description="Zusammenfassung in Markdown")],
    overwrite: Annotated[bool, Field(description="Vorhandene eigene Zusammenfassung ersetzen")] = False,
) -> dict:
    """Speichert eine Lernzusammenfassung in Markdown für eine Datei (wie die Zusammenfassung der App).
    Aufbau mit diesen Überschriften, die StudyHub auswertet: „## Worum es geht“ (2–3 Sätze), „## Kernaussagen“
    (Stichpunkte), „## Wichtige Begriffe“ (je Zeile „- **Begriff**: Erklärung“, landet auch im Glossar),
    „## Prüfungsrelevant“ (Stichpunkte). Weitere Abschnitte (z. B. Beispiele, Rechenwege) sind erlaubt: Sie
    erscheinen bei Telegram und auf dem reMarkable (Weitergeben im Lernthema). StudyHub zeigt die
    Zusammenfassung, solange es für die Datei kein Lernthema gibt. Höchstens 30.000 Zeichen."""
    return _store(path, "summary", markdown.strip(), overwrite)


@mcp.tool(annotations=WRITE)
def save_flashcards(
    path: Annotated[str, Field(description="Pfad wie in list_files")],
    cards: Annotated[list[Karte], Field(min_length=1, max_length=40, description="12 bis 20 Karten zu den "
                                        "prüfungsrelevanten Inhalten, nichts Organisatorisches")],
    overwrite: Annotated[bool, Field(description="Vorhandene Lernkarten ersetzen")] = False,
) -> dict:
    """Speichert Lernkarten für eine Datei (StudyHub-Karteikarten mit Wiederholungsplan).
    cards: 1–40 Objekte {"front", "back"}, empfohlen 12–20; front = präzise Frage (≤ 500 Zeichen),
    back = kurze, vollständige Antwort (≤ 1500 Zeichen, höchstens 3 Sätze). Nichts Organisatorisches.
    Beispiel: [{"front": "Was ist ein Mindestpreis?", "back": "Ein staatlich festgelegter Preis, der nicht
    unterschritten werden darf; liegt er über dem Gleichgewichtspreis, entsteht ein Angebotsüberschuss."}]"""
    return _store(path, "flashcards", {"cards": [c.model_dump() for c in cards]}, overwrite)


class TutorFrage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500, description="Prüfungsfrage, die man mündlich beantworten kann")
    answer: str = Field(min_length=1, max_length=1500, description="Kurze Musterlösung, 1–3 Sätze")
    page: int = Field(ge=1, le=10000, description="Seite, auf der die Antwort steht")


@mcp.tool(annotations=ADD)
def save_tutor_questions(
    path: Annotated[str, Field(description="Pfad wie in list_files (PDF- oder Textdatei)")],
    questions: Annotated[list[TutorFrage], Field(min_length=1, max_length=20, description=(
        f"{tutor.QUESTIONS_PER_FILE} Prüfungsfragen zu den wichtigsten Inhalten, nichts Organisatorisches"))],
    add: Annotated[bool, Field(description="Zu vorhandenen Tutor-Fragen dazunehmen (sonst Fehler)")] = False,
) -> dict:
    """Speichert Prüfungsfragen mit Musterlösung für den Sprachtutor (Abfragen und ElevenLabs Agent).
    questions: 1–20 Objekte {"question", "answer", "page"}; question mündlich beantwortbar (≤ 500 Zeichen),
    answer 1–3 Sätze (≤ 1500), page = Seite mit der Antwort (ab 1)."""
    file, relative = _resolve(path)
    if file.suffix.lower() not in tutor.EXTENSIONS:
        raise ToolError(f"Der Tutor kann nur {', '.join(sorted(tutor.EXTENSIONS))}-Dateien abfragen")
    try:
        result = tutor.save_questions(file, relative, [q.model_dump() for q in questions], PROVIDER, add)
    except tutor.TutorError as error:
        raise ToolError(str(error)) from None
    core.log(f"MCP: {result['added']} Tutor-Fragen für {relative} gespeichert")
    return {"gespeichert": True, "pfad": relative, "neu": result["added"], "fragen_gesamt": result["questions"],
            "hinweis": "Der Sprachtutor fragt sie ab, sobald StudyHub neu lädt."}


# --- Prompts ------------------------------------------------------------------


@mcp.prompt(name="lerncoach", title="Lerncoach",
            description="Claude coacht dich mit deinen ILIAS-Unterlagen (wie der Claude-Knopf in StudyHub)")
def lerncoach(kurs: Annotated[str | None, Field(description="Kursname wie in list_courses (optional)")] = None) -> str:
    return integrations.coach_prompt(kurs.strip() if kurs and kurs.strip() else None)


if __name__ == "__main__":
    mcp.run("stdio")
