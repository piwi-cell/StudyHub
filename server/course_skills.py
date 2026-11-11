"""Kurs-Skills mit KI: Formelsammlung, Mindmap, Glossar und Übungsaufgaben über alle Dokumente eines Kurses.

Grundlage sind die Markdown-Fassungen der Kursdokumente (markdown_docs.py), nicht die PDFs. Standard ist das
Claude-Abo (Claude Code headless); jeder Anbieter mit JSON-Ausgabe aus ai.complete() geht ebenso.
Ergebnisse liegen pro Kursordner in `KI/kurs-skills.json` und erscheinen in StudyHub im jeweiligen Tab.
"""

import time
from pathlib import Path

import ai
import core
import markdown_docs

STORE = core.APP_DIR / "KI" / "kurs-skills.json"
MAX_CHARS = 600_000  # ca. 150k Tokens Kursmaterial pro Anfrage; längere Kurse werden gleichmäßig gekürzt

SYSTEM = (
    "Du bist ein Lernassistent für Studierende der Universität Mannheim. Du bekommst alle Unterlagen eines "
    "Kurses als Markdown (<dokument pfad=…>, Seiten als „## Seite n“). Arbeite nur mit diesem Material; erfinde "
    "nichts. Antworte auf Deutsch, Fachbegriffe aus englischen Unterlagen bleiben englisch. Gib bei jedem Punkt "
    "die Quelle als „Dateiname, S. n“ an."
)


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or list(properties),
            "additionalProperties": False}


_S = {"type": "string"}
SKILLS = {
    "formelsammlung": (
        "Erstelle eine vollständige Formelsammlung des Kurses, nach Themen gruppiert. Pro Formel: Name, die Formel "
        "in einfacher Textschreibweise (z. B. „K_n = K_0 · q^n“), kurz was die Symbole bedeuten und wann man sie "
        "benutzt, Quelle. Keine Formel erfinden; gibt es keine Formeln, die wichtigsten Definitionen.",
        _obj({"gruppen": {"type": "array", "items": _obj({
            "thema": _S, "formeln": {"type": "array", "items": _obj(
                {"name": _S, "formel": _S, "erklaerung": _S, "quelle": _S})}})}}),
    ),
    "mindmap": (
        "Erstelle eine Mindmap des Kurses: in der Mitte der Kurs, darum 4 bis 9 Hauptthemen in sinnvoller "
        "Reihenfolge, je 2 bis 7 Unterpunkte (Stichworte, höchstens 8 Wörter) und die Quelle des Hauptthemas.",
        _obj({"zentrum": _S, "aeste": {"type": "array", "items": _obj(
            {"titel": _S, "unterpunkte": {"type": "array", "items": _S}, "quelle": _S})}}),
    ),
    "glossar": (
        "Erstelle ein Glossar der prüfungsrelevanten Fachbegriffe des Kurses (20 bis 60 Begriffe), alphabetisch. "
        "Pro Begriff eine verständliche Erklärung in 1 bis 2 Sätzen und die Quelle.",
        _obj({"begriffe": {"type": "array", "items": _obj({"begriff": _S, "erklaerung": _S, "quelle": _S})}}),
    ),
    "uebungsaufgaben": (
        "Erstelle 8 bis 12 Übungsaufgaben im Stil der Übungsblätter und Klausuren dieses Kurses, von leicht nach "
        "schwer. Pro Aufgabe: Titel, Aufgabentext (mit konkreten Zahlen, wenn passend), vollständiger Lösungsweg, "
        "Schwierigkeit (leicht, mittel oder schwer) und die Quelle, auf der die Aufgabe beruht.",
        _obj({"aufgaben": {"type": "array", "items": _obj({
            "titel": _S, "aufgabe": _S, "loesung": _S,
            "schwierigkeit": {"type": "string", "enum": ["leicht", "mittel", "schwer"]}, "quelle": _S})}}),
    ),
}


def load() -> dict:
    return core.load_json(STORE, {})


def results(course: str) -> dict:
    return load().get(core.nfc(course), {})


def create(course: str, skill: str, files: list[tuple[Path, str]], provider: str, model: str | None = None) -> dict:
    """Erstellt einen Skill für einen Kurs aus den Markdown-Fassungen aller Kursdokumente und speichert ihn."""
    if skill not in SKILLS:
        raise ai.AIError(f"Unbekannter Skill {skill}")
    material, sources = markdown_docs.course_markdown(course, files, MAX_CHARS)
    if not material:
        raise ai.AIError("Noch keine lesbaren Dokumente in diesem Kurs (gescannte PDFs erst einmal mit Claude "
                         "zusammenfassen, dann gibt es ihre Markdown-Fassung)")
    instruction, schema = SKILLS[skill]
    prompt = f"<kurs name=\"{course}\">\n{material}\n</kurs>\n\n{instruction}"
    started = time.monotonic()
    output = ai.complete(provider, SYSTEM, prompt, schema, model)
    result = {"output": output, "provider": provider, "model": model or "", "quellen": sources,
              "created": time.time(), "seconds": round(time.monotonic() - started, 1)}
    data = load()
    data.setdefault(core.nfc(course), {})[skill] = result
    STORE.parent.mkdir(parents=True, exist_ok=True)
    core.save_json(STORE, data)
    core.log(f"KI: {skill} für {course} erstellt ({len(sources)} Dokumente, {provider})")
    return result


def rename_folder(old: str, new: str) -> None:
    data = load()
    if core.nfc(old) in data:
        data[core.nfc(new)] = data.pop(core.nfc(old))
        core.save_json(STORE, data)
