"""Sprechender Study-Tutor: fragt Kursmaterial ab, bewertet Antworten, nennt Quellen.

Ablauf (liegt im Code, nicht im Modell):
1. prepare(): Text pro Seite in eine SQLite-Volltextsuche (FTS5), danach erzeugt das
   Gehirn pro Datei Fragen mit Musterlösung und Quelle. Schon verarbeitete Dateien
   (gleicher Inhalt) werden übersprungen.
2. next_question(): zufällig, falsch oder halb beantwortete Fragen bevorzugt.
3. grade(): das Gehirn vergleicht mit der Musterlösung → correct | partial | wrong.
4. follow_up(): Rückfrage, beantwortet nur aus den passendsten Seiten, mit Quellenangabe.

Das „Gehirn“ ist ein KI-Anbieter aus ai.py (Standard: Gemma lokal). Sprache (ElevenLabs)
steckt in voice.py; der Tutor selbst arbeitet nur mit Text.

Automatik: prepare_pending() bereitet im Hintergrund alle Kursdateien vor, die noch keine
Fragen haben (immer mit Gemma, damit keine Kosten entstehen). Dateien, aus denen keine Fragen
werden (z. B. gescannte Folien), landen in `skipped` und werden erst nach einer Änderung neu versucht.

Freies Gespräch (Push-to-Talk): converse() bekommt den Verlauf und den neuen Satz, sucht
passende Folienstellen und lässt das Gehirn antworten. Das Gehirn stellt eigene Fragen aus dem
Material, gibt Hinweise, erklärt und wechselt auf Wunsch den Kurs; der Code speichert neue
Fragen im Pool und Bewertungen in `results`.

Gesprächsmodus: Ein ElevenLabs Agent führt das Gespräch selbst. Er holt sich über das
Client-Tool get_next_question Frage und Musterlösung, bewertet selbst und meldet das Ergebnis
über record_result (→ record()). AGENT_PROMPT ist sein System-Prompt.
"""

import random
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import ai
import core

DB_FILE = core.APP_DIR / "tutor.sqlite3"
BRAINS = ("gemma", "claude", "openai", "gemini")
DEFAULT_BRAIN = "gemma"
AUTO_BRAIN = "gemma"  # automatische Vorbereitung immer lokal und kostenlos
EXTENSIONS = {".pdf", ".txt", ".md", ".pptx", ".docx"}
QUESTIONS_PER_FILE = 6
MAX_SOURCE_CHARS = 40_000  # so viel Material bekommt das Gehirn pro Datei für die Fragen

SYSTEM = (
    "Du bist ein geduldiger Lerntutor für Studierende der Universität Mannheim. Du sprichst Deutsch, "
    "kurz und freundlich, und stützt dich ausschließlich auf das Kursmaterial, das du bekommst. "
    "Steht etwas nicht im Material, sag das. Nenne Quellen als „Datei, S. n“."
)

VERDICTS = ("correct", "partial", "wrong")

# System-Prompt für den ElevenLabs Agent; {{course}} füllt ElevenLabs aus den Dynamic Variables
AGENT_PROMPT = (
    "Du bist ein geduldiger Lerntutor für Studierende der Universität Mannheim im Kurs {{course}}. "
    "Du sprichst Deutsch, freundlich und kurz, höchstens drei Sätze am Stück. Formeln liest du nicht "
    "Zeichen für Zeichen vor, sondern erklärst sie in Worten.\n\n"
    "Ablauf:\n"
    "1. Rufe das Tool get_next_question auf. Es liefert question, solution (Musterlösung) und source.\n"
    "2. Stelle die Frage. Verrate die Musterlösung nicht.\n"
    "3. Vergleiche die Antwort mit der Musterlösung: correct (inhaltlich richtig, Wortlaut egal), "
    "partial (teilweise richtig oder unvollständig) oder wrong.\n"
    "4. Gib 1–2 Sätze Feedback, bei partial oder wrong mit dem fehlenden Punkt.\n"
    "5. Rufe record_result mit answer (Antwort in Stichworten), verdict und feedback auf.\n"
    "6. Beantworte Rückfragen nur mit der Musterlösung und nenne die Quelle (source). "
    "Steht etwas nicht darin, sag das. Danach weiter mit Schritt 1.\n"
    "Liefert get_next_question einen Fehler, sag, dass erst Material vorbereitet werden muss, und beende das Gespräch."
)
AGENT_FIRST_MESSAGE = "Hallo! Ich frage dich heute zu {{course}} ab. Bereit für die erste Frage?"

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "page": {"type": "integer"},
                },
                "required": ["question", "answer", "page"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}
GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "partial", "wrong"]},
        "feedback": {"type": "string"},
    },
    "required": ["verdict", "feedback"],
    "additionalProperties": False,
}


class TutorError(Exception):
    pass


# --- Datenbank ----------------------------------------------------------------


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT NOT NULL, course TEXT NOT NULL,
                                  pages INTEGER NOT NULL, questions_ready INTEGER NOT NULL DEFAULT 0);
CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(path UNINDEXED, course UNINDEXED, page UNINDEXED, text,
                                                    tokenize = 'unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, path TEXT NOT NULL, course TEXT NOT NULL,
                                      question TEXT NOT NULL, answer TEXT NOT NULL, page INTEGER NOT NULL,
                                      brain TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS skipped (path TEXT PRIMARY KEY, hash TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES questions(id),
                                    answer TEXT NOT NULL, verdict TEXT NOT NULL, feedback TEXT NOT NULL,
                                    created REAL NOT NULL);
"""


def connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


# --- Material und Fragen ------------------------------------------------------


def index_file(db: sqlite3.Connection, path: Path, relative: str) -> bool:
    """Legt den Text der Datei seitenweise in die Volltextsuche. False, wenn unverändert schon da."""
    digest = ai.file_hash(path)
    known = db.execute("SELECT hash FROM files WHERE path = ?", (relative,)).fetchone()
    if known and known["hash"] == digest:
        return False
    try:
        pages = ai.extract_pages(path)
    except ai.AIError as error:  # Datei selbst unlesbar: kein KI-Problem, Datei überspringen
        raise TutorError(str(error)) from None
    if ai.is_scanned(pages, path):
        raise TutorError(f"{path.name} enthält kaum Text (gescannte Folien), der Tutor braucht Text")
    course = relative.split("/", 1)[0]
    with db:
        db.execute("DELETE FROM pages WHERE path = ?", (relative,))
        db.execute("DELETE FROM results WHERE question_id IN (SELECT id FROM questions WHERE path = ?)", (relative,))
        db.execute("DELETE FROM questions WHERE path = ?", (relative,))
        db.executemany("INSERT INTO pages (path, course, page, text) VALUES (?, ?, ?, ?)",
                       [(relative, course, n, text) for n, text in enumerate(pages, 1) if text.strip()])
        db.execute("INSERT OR REPLACE INTO files (path, hash, course, pages, questions_ready) VALUES (?, ?, ?, ?, 0)",
                   (relative, digest, course, len(pages)))
    return True


def generate_questions(db: sqlite3.Connection, relative: str, brain: str, model: str | None = None) -> int:
    rows = db.execute("SELECT page, text FROM pages WHERE path = ? ORDER BY CAST(page AS INTEGER)", (relative,))
    material = ""
    for row in rows:
        part = f"[Seite {row['page']}]\n{row['text'].strip()}\n\n"
        if len(material) + len(part) > MAX_SOURCE_CHARS:
            break
        material += part
    prompt = (f"Material aus „{Path(relative).name}“:\n\n{material}\n"
              f"Erstelle {QUESTIONS_PER_FILE} Prüfungsfragen zu den wichtigsten Inhalten. Pro Frage: "
              "die Frage, eine kurze Musterlösung (1–3 Sätze) und die Seitenzahl, auf der die Antwort steht. "
              "Keine Fragen zu Organisatorischem.")
    result = ai.complete(brain, SYSTEM, prompt, QUESTION_SCHEMA, model)
    questions = [q for q in result.get("questions", [])
                 if q.get("question", "").strip() and q.get("answer", "").strip()]
    if not questions:
        raise TutorError(f"Für {Path(relative).name} kamen keine brauchbaren Fragen zurück")
    _store_questions(db, relative, questions, brain)
    return len(questions)


def _store_questions(db: sqlite3.Connection, relative: str, questions: list[dict], brain: str) -> None:
    course = relative.split("/", 1)[0]
    # Kleine Modelle erfinden Seitenzahlen: nur Seiten zulassen, die es mit Text wirklich gibt
    pages = sorted(int(r[0]) for r in db.execute("SELECT page FROM pages WHERE path = ?", (relative,)))

    def real_page(page) -> int:
        page = int(page or 0) if str(page or "").isdigit() else 0
        return page if page in pages else min(pages, key=lambda p: abs(p - page))

    with db:
        db.executemany(
            "INSERT INTO questions (path, course, question, answer, page, brain, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(relative, course, q["question"].strip(), q["answer"].strip(), real_page(q.get("page")), brain,
              time.time()) for q in questions])
        db.execute("UPDATE files SET questions_ready = 1 WHERE path = ?", (relative,))


def add_fixed_questions(path: Path, relative: str, questions: list[dict]) -> int:
    """Feste Fragen (z. B. Demo-Daten) ohne KI-Aufruf übernehmen. Dateien, die schon Fragen haben,
    bleiben unverändert; gibt die Zahl der neu angelegten Fragen zurück."""
    with closing(connect()) as db:
        index_file(db, path, relative)
        if db.execute("SELECT questions_ready FROM files WHERE path = ?", (relative,)).fetchone()[0]:
            return 0
        _store_questions(db, relative, questions, "fixed")
    return len(questions)


def save_questions(path: Path, relative: str, questions: list[dict], brain: str, add: bool = False) -> dict:
    """Fertige Fragen von außen übernehmen (z. B. Claude Desktop über MCP), ohne eigenen KI-Aufruf.
    Löscht nie etwas: Hat die Datei schon Fragen, kommen neue nur mit add=True zum Pool dazu."""
    with closing(connect()) as db:
        index_file(db, path, relative)
        before = db.execute("SELECT COUNT(*) FROM questions WHERE path = ?", (relative,)).fetchone()[0]
        if before and not add:
            raise TutorError(f"{relative} hat schon {before} Tutor-Fragen. Zum Ergänzen add=true setzen.")
        _store_questions(db, relative, questions, brain)
        with db:
            db.execute("DELETE FROM skipped WHERE path = ?", (relative,))
    return {"path": relative, "questions": before + len(questions), "added": len(questions)}


def counts_by_path() -> dict[str, int]:
    """Zahl der Tutor-Fragen je Datei."""
    with closing(connect()) as db:
        return {r["path"]: r["n"] for r in db.execute("SELECT path, COUNT(*) AS n FROM questions GROUP BY path")}


def prepare(path: Path, relative: str, brain: str, model: str | None = None) -> dict:
    """Material indizieren und Fragen erzeugen; überspringt Dateien, die schon fertig sind."""
    with closing(connect()) as db:
        changed = index_file(db, path, relative)
        ready = db.execute("SELECT questions_ready FROM files WHERE path = ?", (relative,)).fetchone()[0]
        if not changed and ready:
            count = db.execute("SELECT COUNT(*) FROM questions WHERE path = ?", (relative,)).fetchone()[0]
            return {"path": relative, "questions": count, "skipped": True}
        return {"path": relative, "questions": generate_questions(db, relative, brain, model), "skipped": False}


# --- Automatische Vorbereitung -------------------------------------------------

# Fortschritt für die Oberfläche; wird nur vom Hintergrund-Thread geschrieben
progress = {"running": False, "current": "", "pending": 0, "done": 0, "error": ""}
_hashes: dict[str, tuple[float, int, str]] = {}  # relativer Pfad → (mtime, Größe, Hash), spart erneutes Hashen
# Dateien, für die Gemma kein gültiges JSON geliefert hat: relativer Pfad → (Hash, Modell). Bis die Datei
# sich ändert, ein anderes Modell läuft oder die App neu startet, nicht noch einmal automatisch versuchen
_unusable: dict[str, tuple[str, str]] = {}


def _hash(path: Path, relative: str) -> str:
    stat = path.stat()
    known = _hashes.get(relative)
    if known and known[:2] == (stat.st_mtime, stat.st_size):
        return known[2]
    digest = ai.file_hash(path)
    _hashes[relative] = (stat.st_mtime, stat.st_size, digest)
    return digest


def pending(files: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    """Dateien (Pfad, relativer Pfad), die noch keine Fragen haben oder sich geändert haben.
    Übersprungene Dateien zählen erst nach einer Änderung wieder."""
    with closing(connect()) as db:
        ready = {r["path"]: r["hash"] for r in db.execute("SELECT path, hash FROM files WHERE questions_ready = 1")}
        skipped = {r["path"]: r["hash"] for r in db.execute("SELECT path, hash FROM skipped")}
    todo = []
    for path, relative in files:
        if path.suffix.lower() not in EXTENSIONS or not path.is_file():
            continue
        digest = _hash(path, relative)
        if ready.get(relative) != digest and skipped.get(relative) != digest:
            todo.append((path, relative))
    return todo


def prepare_pending(files: list[tuple[Path, str]], stop=lambda: False) -> dict:
    """Bereitet alle offenen Dateien nacheinander mit Gemma vor. Bricht ab, wenn Gemma nicht
    antwortet (nächster Durchlauf versucht es erneut) oder stop() True liefert. Liefert Gemma für eine
    Datei kein gültiges JSON, geht es mit der nächsten weiter."""
    model = ai.gemma_model()
    todo = [(path, relative) for path, relative in pending(files)
            if _unusable.get(relative) != (_hash(path, relative), model)]
    progress.update(running=True, pending=len(todo), done=0, error="")
    made = 0
    try:
        for path, relative in todo:
            if stop():
                break
            progress["current"] = Path(relative).name
            try:
                made += prepare(path, relative, AUTO_BRAIN)["questions"]
            except TutorError as error:  # Datei taugt nicht (z. B. gescannt): bis zur nächsten Änderung überspringen
                with closing(connect()) as db, db:
                    db.execute("INSERT OR REPLACE INTO skipped (path, hash, reason) VALUES (?, ?, ?)",
                               (relative, _hash(path, relative), str(error)))
                core.log(f"Tutor: {relative} übersprungen ({error})")
            except ai.AIFormatError:  # Antwort unbrauchbar: nur diese Datei auslassen, nicht alles anhalten
                _unusable[relative] = (_hash(path, relative), model)
                core.log(f"Tutor: {relative} ausgelassen ({model} lieferte keine brauchbaren Fragen)")
            except ai.AIError as error:  # Gemma nicht erreichbar oder zu langsam: später erneut
                progress["error"] = str(error)
                core.log(f"Tutor: automatische Vorbereitung angehalten ({error})")
                break
            progress["done"] += 1
    finally:
        progress.update(running=False, current="")
    if made:
        core.log(f"Tutor: {made} neue Fragen automatisch erzeugt")
    return {"questions": made, "files": progress["done"], "pending": len(todo) - progress["done"]}


# --- Freies Gespräch ------------------------------------------------------------

CHAT_HISTORY_TURNS = 12  # so viele letzte Beiträge sieht das Gehirn
CHAT_MATERIAL_CHARS = 2500  # pro Folienstelle
CHAT_SYSTEM = SYSTEM + (
    " Du führst ein gesprochenes Lerngespräch: höchstens drei kurze Sätze pro Beitrag, keine Aufzählungen, "
    "Formeln in Worten statt Zeichen. Du stellst Fragen zum Material, auch eigene Anschlussfragen. Ist eine "
    "Antwort falsch oder unvollständig, gibst du zuerst einen Hinweis und lässt es noch einmal versuchen; erst "
    "beim zweiten Fehlversuch erklärst du die Lösung. Fragt die Person selbst etwas, beantwortest du es aus dem "
    "Material und nennst die Quelle. Stelle immer nur eine Frage auf einmal."
)
CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "say": {"type": "string"},
        "kind": {"type": "string", "enum": ["question", "hint", "feedback", "explanation", "chat"]},
        "verdict": {"type": "string", "enum": ["correct", "partial", "wrong", "none"]},
        "question": {"type": "string"},
        "solution": {"type": "string"},
        "ref": {"type": "string"},
        "course": {"type": "string"},
    },
    "required": ["say", "kind", "verdict", "question", "solution", "ref", "course"],
    "additionalProperties": False,
}


def _chat_material(db: sqlite3.Connection, text: str, course: str | None) -> list[sqlite3.Row]:
    """Passende Folienstellen; ohne Treffer (z. B. am Anfang) zufällige Seiten des Kurses."""
    hits = search(db, text, course, limit=4) if text.strip() else []
    if len(hits) < 2:
        hits += db.execute("SELECT path, page, text FROM pages WHERE (? IS NULL OR course = ?) ORDER BY random() "
                           "LIMIT 3", (course, course)).fetchall()
    unique: dict = {}
    for hit in hits:  # jede Seite nur einmal, Suchtreffer behalten ihren Platz vorn
        unique.setdefault((hit["path"], hit["page"]), hit)
    return list(unique.values())[:4]


def _chat_prompt(db, text, history, course, open_question, hits, pool) -> str:
    courses = [r[0] for r in db.execute("SELECT DISTINCT course FROM pages ORDER BY course")]
    turns = "\n".join(f"{'Tutor' if t.get('role') == 'tutor' else 'Studierende/r'}: {t.get('text', '').strip()}"
                      for t in history[-CHAT_HISTORY_TURNS:] if t.get("text", "").strip())
    material = "\n\n".join(f"[M{i}] {Path(h['path']).stem}, S. {h['page']}\n{h['text'][:CHAT_MATERIAL_CHARS]}"
                            for i, h in enumerate(hits, 1))
    questions = "\n".join(f"[P{q['id']}] {q['question']} → Musterlösung: {q['answer']}" for q in pool)
    current = (f"Offene Frage: {open_question['question']}\nMusterlösung: {open_question['answer']}"
               if open_question else "Gerade ist keine Frage offen.")
    return (
        f"Aktueller Kurs: {course or 'alle Kurse'}. Verfügbare Kurse: {', '.join(courses) or 'keine'}.\n"
        f"{current}\n\nBisheriges Gespräch:\n{turns or '(Beginn des Gesprächs)'}\n\n"
        f"Neuer Beitrag der Person: {text.strip() or '(noch nichts, begrüße kurz und stelle die erste Frage)'}\n\n"
        f"Material:\n{material or '(kein Material)'}\n\nFragen aus dem Fragenpool (darfst du nutzen):\n"
        f"{questions or '(keine)'}\n\n"
        "Antworte als JSON:\n"
        "- say: dein gesprochener Beitrag.\n"
        "- kind: question (du stellst eine neue Frage), hint (Hinweis zur offenen Frage), feedback (Bewertung "
        "plus ggf. nächste Frage), explanation (du beantwortest eine Frage der Person), chat (sonst).\n"
        "- verdict: correct/partial/wrong nur, wenn der Beitrag eine Antwort auf die offene Frage ist und du sie "
        "abschließend bewertest; bei einem Hinweis für einen zweiten Versuch oder sonst none.\n"
        "- question/solution: stellst du in say eine neue Frage, hier die Frage und ihre kurze Musterlösung, "
        "sonst leer.\n"
        "- ref: Quelle der neuen Frage oder Erklärung: M1, M2 … für Material, P<Nummer> für eine Pool-Frage, "
        "sonst leer.\n"
        "- course: nur wenn die Person ausdrücklich den Kurs wechseln will, der genaue Name aus der Liste, "
        "sonst leer."
    )


def _match_course(db: sqlite3.Connection, name: str) -> str | None:
    name = name.strip().casefold()
    if not name:
        return None
    courses = [r[0] for r in db.execute("SELECT DISTINCT course FROM pages")]
    return next((c for c in courses if c.casefold() == name), None) or next(
        (c for c in courses if name in c.casefold() or c.casefold() in name), None)


def converse(text: str, history: list[dict], course: str | None, open_question_id: int | None,
             brain: str, model: str | None = None) -> dict:
    """Ein Gesprächsschritt im freien Lerngespräch. history: [{role: tutor|user, text}], vom Browser
    mitgeschickt. Gibt zurück, was der Tutor sagt, ggf. die Bewertung und die neue offene Frage."""
    with closing(connect()) as db:
        open_question = None
        if open_question_id is not None:
            open_question = db.execute("SELECT * FROM questions WHERE id = ?", (open_question_id,)).fetchone()
        last_tutor = next((t.get("text", "") for t in reversed(history) if t.get("role") == "tutor"), "")
        hits = _chat_material(db, f"{text} {last_tutor}", course)
        pool = db.execute(
            """SELECT q.id, q.question, q.answer FROM questions q WHERE (? IS NULL OR q.course = ?)
               AND NOT EXISTS (SELECT 1 FROM results r WHERE r.question_id = q.id AND r.verdict = 'correct')
               AND (? IS NULL OR q.id != ?) ORDER BY random() LIMIT 3""",
            (course, course, open_question_id, open_question_id)).fetchall()
        prompt = _chat_prompt(db, text, history, course, open_question, hits, pool)
        result = ai.complete(brain, CHAT_SYSTEM, prompt, CHAT_SCHEMA, model)
        new_course = _match_course(db, result.get("course") or "")
        if new_course and new_course != course:  # Kurswechsel: mit dem Material des neuen Kurses antworten
            course, open_question = new_course, None
            hits = _chat_material(db, text, course)
            pool = []
            result = ai.complete(brain, CHAT_SYSTEM, _chat_prompt(db, text, history, course, None, hits, pool),
                                 CHAT_SCHEMA, model)

        say = (result.get("say") or "").strip() or "Magst du das noch einmal sagen?"
        verdict = result.get("verdict") if result.get("verdict") in VERDICTS else None
        ref = (result.get("ref") or "").strip().upper()
        answer = {"say": say, "kind": result.get("kind") or "chat", "verdict": None, "course": course,
                  "question_id": open_question["id"] if open_question else None, "source": None,
                  "sources": list(dict.fromkeys(f"{Path(h['path']).stem}, S. {h['page']}" for h in hits))}

    # Offene Frage: nach einer abschließenden Bewertung geschlossen, bei einer neuen Frage ersetzt
    if verdict and open_question is not None and text.strip():
        record(open_question["id"], text, verdict, say)
        answer.update(verdict=verdict, question_id=None)
    if answer["kind"] in ("question", "feedback"):
        new_id = _chat_question(result, ref, hits)
        if new_id is not None or answer["kind"] == "question":
            answer["question_id"] = new_id
    if answer["question_id"] is not None:
        with closing(connect()) as db:
            answer["source"] = _source(_question(db, answer["question_id"]))
    return answer


def _chat_question(result: dict, ref: str, hits: list) -> int | None:
    """Neue Frage aus dem Gespräch: Pool-Frage (P…) übernehmen oder eigene Frage (M…) im Pool speichern."""
    if ref.startswith("P") and ref[1:].isdigit():
        with closing(connect()) as db:
            row = db.execute("SELECT id FROM questions WHERE id = ?", (int(ref[1:]),)).fetchone()
        return row["id"] if row else None
    question, solution = (result.get("question") or "").strip(), (result.get("solution") or "").strip()
    if not question or not solution:
        return None
    hit = hits[int(ref[1:]) - 1] if ref.startswith("M") and ref[1:].isdigit() and 0 < int(ref[1:]) <= len(hits) \
        else (hits[0] if hits else None)
    if hit is None:
        return None
    with closing(connect()) as db, db:
        course = db.execute("SELECT course FROM files WHERE path = ?", (hit["path"],)).fetchone()
        cursor = db.execute(
            "INSERT INTO questions (path, course, question, answer, page, brain, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (hit["path"], course[0] if course else hit["path"].split("/", 1)[0], question, solution,
             int(hit["page"]), "chat", time.time()))
        return cursor.lastrowid


# --- Abfrage ------------------------------------------------------------------


def _source(row: sqlite3.Row) -> str:
    return f"{Path(row['path']).stem}, S. {row['page']}"


def next_question(course: str | None = None, exclude: int | None = None, with_solution: bool = False) -> dict | None:
    """Zufällige Frage; Fragen, deren letzte Antwort falsch oder halb richtig war, doppelt so oft,
    noch nie gestellte dreimal so oft wie richtig beantwortete. with_solution: Musterlösung
    mitliefern (für den Agent, der selbst bewertet)."""
    with closing(connect()) as db:
        rows = db.execute(
            """SELECT q.*, (SELECT verdict FROM results r WHERE r.question_id = q.id ORDER BY r.id DESC LIMIT 1) AS last
               FROM questions q WHERE (? IS NULL OR q.course = ?) AND (? IS NULL OR q.id != ?)""",
            (course, course, exclude, exclude)).fetchall()
    if not rows and exclude is not None:  # nur die ausgeschlossene Frage übrig: lieber wiederholen als nichts
        return next_question(course, None, with_solution)
    if not rows:
        return None
    weights = [{None: 3, "wrong": 2, "partial": 2, "correct": 1}[row["last"]] for row in rows]
    row = random.choices(rows, weights=weights)[0]
    question = {"id": row["id"], "question": row["question"], "course": row["course"], "source": _source(row),
                "last": row["last"]}
    if with_solution:
        question["solution"] = row["answer"]
    return question


def _question(db: sqlite3.Connection, question_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        raise TutorError("Frage nicht gefunden")
    return row


def grade(question_id: int, answer: str, brain: str, model: str | None = None) -> dict:
    if not answer.strip():
        raise TutorError("Keine Antwort erkannt, bitte noch einmal")
    with closing(connect()) as db:
        q = _question(db, question_id)
        prompt = (f"Frage: {q['question']}\nMusterlösung: {q['answer']}\nAntwort des Studierenden: {answer.strip()}\n\n"
                  "Bewerte die Antwort gegen die Musterlösung: correct (inhaltlich richtig, Wortlaut egal), "
                  "partial (teilweise richtig oder unvollständig) oder wrong. Feedback: 1–2 kurze Sätze, "
                  "bei partial/wrong mit dem fehlenden Punkt. Sprich die Person direkt an.")
        result = ai.complete(brain, SYSTEM, prompt, GRADE_SCHEMA, model)
    return record(question_id, answer, result.get("verdict"), result.get("feedback"))


def record(question_id: int, answer: str, verdict: str | None, feedback: str | None) -> dict:
    """Bewertung speichern, egal von wem (eigenes Gehirn oder ElevenLabs Agent).
    Ungültiges Urteil → partial, leeres Feedback → Standardtext."""
    verdict = verdict if verdict in VERDICTS else "partial"
    feedback = (feedback or "").strip() or "Danke, weiter geht’s."
    with closing(connect()) as db:
        q = _question(db, question_id)
        with db:
            db.execute("INSERT INTO results (question_id, answer, verdict, feedback, created) VALUES (?, ?, ?, ?, ?)",
                       (question_id, (answer or "").strip(), verdict, feedback, time.time()))
    return {"verdict": verdict, "feedback": feedback, "solution": q["answer"], "source": _source(q)}


def search(db: sqlite3.Connection, text: str, course: str | None = None, limit: int = 4) -> list[sqlite3.Row]:
    """Volltextsuche über das Material. Wörter werden einzeln gesucht (ODER), bestes Ergebnis zuerst."""
    words = [w for w in re.findall(r"\w{3,}", text.lower())][:12]
    if not words:
        return []
    query = " OR ".join(f'"{w}"' for w in words)
    return db.execute(
        "SELECT path, page, text FROM pages WHERE pages MATCH ? AND (? IS NULL OR course = ?) ORDER BY rank LIMIT ?",
        (query, course, course, limit)).fetchall()


def follow_up(question_id: int, text: str, brain: str, model: str | None = None) -> dict:
    """Rückfrage zur aktuellen Frage, beantwortet aus der Quellseite und den passendsten Treffern."""
    if not text.strip():
        raise TutorError("Keine Rückfrage erkannt")
    with closing(connect()) as db:
        q = _question(db, question_id)
        hits = list(db.execute("SELECT path, page, text FROM pages WHERE path = ? AND page = ?",
                               (q["path"], q["page"])).fetchall())
        hits += [h for h in search(db, f"{text} {q['question']}", q["course"])
                 if (h["path"], h["page"]) != (q["path"], q["page"])]
    context = "\n\n".join(f"[{Path(h['path']).stem}, S. {h['page']}]\n{h['text'][:4000]}" for h in hits[:4])
    prompt = (f"Aktuelle Prüfungsfrage: {q['question']}\nRückfrage: {text.strip()}\n\nMaterial:\n{context}\n\n"
              "Beantworte die Rückfrage in höchstens 3 Sätzen, ohne die Lösung der Prüfungsfrage direkt zu verraten, "
              "und nenne am Ende die Quelle.")
    sources = list(dict.fromkeys(f"{Path(h['path']).stem}, S. {h['page']}" for h in hits[:4]))
    return {"answer": ai.complete(brain, SYSTEM, prompt, None, model).strip(), "sources": sources}


def stats(course: str | None = None) -> dict:
    with closing(connect()) as db:
        files = db.execute("SELECT COUNT(*) FROM files WHERE questions_ready = 1 AND (? IS NULL OR course = ?)",
                           (course, course)).fetchone()[0]
        questions = db.execute("SELECT COUNT(*) FROM questions WHERE ? IS NULL OR course = ?",
                               (course, course)).fetchone()[0]
        verdicts = dict(db.execute(
            """SELECT r.verdict, COUNT(*) FROM results r JOIN questions q ON q.id = r.question_id
               WHERE ? IS NULL OR q.course = ? GROUP BY r.verdict""", (course, course)).fetchall())
        courses = [row[0] for row in db.execute("SELECT DISTINCT course FROM questions ORDER BY course")]
    return {"files": files, "questions": questions, "answered": sum(verdicts.values()),
            "correct": verdicts.get("correct", 0), "partial": verdicts.get("partial", 0),
            "wrong": verdicts.get("wrong", 0), "courses": courses}
