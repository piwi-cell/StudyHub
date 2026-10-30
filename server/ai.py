"""KI-Lernfunktionen: Zusammenfassung, Lernkarten und Fragen zu einem ILIAS-Dokument.

Drei Anbieter hinter einer Schnittstelle:
- Claude (Anthropic-API): bekommt den extrahierten Text oder, bei gescannten Folien ohne
  Text, die PDF selbst. Das Dokument steht vorn im Prompt und ist gecacht, sodass
  Zusammenfassung, Lernkarten und Fragen zum selben Dokument nur einmal voll kosten.
- ChatGPT (OpenAI Responses API): gleiches Vorgehen; OpenAI cacht den Prompt-Anfang
  automatisch. Antworten werden bei OpenAI nicht gespeichert (store=false).
- Gemini (Gemini API, Google AI Studio): gleiches Vorgehen wie Claude, gescannte PDFs gehen als PDF
  mit; der Anfang gleicher Anfragen wird von Google automatisch gecacht.
- Gemma (lokal über Ollama): kostenlos und offline, nur Text. Lange Dokumente werden in
  Abschnitten zusammengefasst; für Fragen gehen nur die passendsten Abschnitte mit.
  Ohne Ollama, aber mit Google-AI-API-Key (Google AI Studio) läuft Gemma über die Gemini API,
  gleiches Vorgehen.

Jedes Ergebnis wird pro Dateiinhalt (SHA-256) gespeichert und nie zweimal erzeugt.
"""

import base64
import hashlib
import json
import os
import re
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import httpx2 as httpx  # kommt mit dem Anthropic-SDK, gleiche API wie httpx
import keyring

import core

CACHE_DIR = core.APP_DIR / "KI"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
# Größtes installierte Gemma-Modell gewinnt; ILIAS_SYNC_GEMMA erzwingt eines
GEMMA_PREFERENCE = ("gemma3:12b", "gemma3:4b", "gemma3:1b", "gemma3:270m")
GEMMA_DEFAULT = "gemma3:4b"
GEMMA_CONTEXT = 32768  # Tokens; bei 16 GB RAM für das 4B-Modell unkritisch
GEMMA_CHUNK_CHARS = 60_000  # ca. 15k Tokens pro Abschnitt, lässt Platz für die Antwort
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GOOGLE_KEY_ACCOUNT = "Google-AI-API-Key"
GEMMA_API_MODELS = {  # Gemma-Modelle der Gemini API laut ai.google.dev/gemma/docs/core/gemma_on_gemini_api
    "gemma-4-26b-a4b-it": "Gemma 4 26B A4B (schnell)",
    "gemma-4-31b-it": "Gemma 4 31B (beste Qualität)",
}
DEFAULT_GEMMA_API_MODEL = "gemma-4-26b-a4b-it"
GEMINI_TRIES = 3  # Versuche bei vorübergehenden Fehlern der Gemini API
# Gemini-Modelle der Gemini API (Modellübersicht ai.google.dev/gemini-api/docs/models, Stand 27.10.2026);
# Gemini 4 Argon gibt es nur mit Abrechnung, nicht im kostenlosen Kontingent
GEMINI_MODELS = {
    "gemini-4-argon": "Gemini 4 Argon (beste Qualität, nur mit Abrechnung)",
    "gemini-3.8-flash": "Gemini 3.8 Flash (ausgewogen)",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite (am günstigsten)",
}
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
MAX_GEMINI_PDF_BYTES = 20_000_000  # PDF direkt in der Anfrage: kleinste dokumentierte Grenze
GEMINI_DOC_TOKENS = 32000  # Ausgabe inklusive Denkschritten; Gemini 4 Argon erlaubt ohne Streaming 32K
KEY_ACCOUNT = "Anthropic-API-Key"
CLAUDE_MODELS = {
    "claude-opus-5-5": "Claude Opus 5.5 (beste Qualität)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 (ausgewogen)",
    "claude-haiku-5-5": "Claude Haiku 5.5 (am günstigsten)",
}
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
OPENAI_URL = "https://api.openai.com/v1/responses"
OPENAI_KEY_ACCOUNT = "OpenAI-API-Key"
OPENAI_MODELS = {
    "gpt-6-astra": "GPT-6 Astra (beste Qualität)",
    "gpt-6.1-sol": "GPT-6.1 Sol (ausgewogen)",
    "gpt-6-luna": "GPT-6 Luna (am günstigsten)",
}
DEFAULT_OPENAI_MODEL = "gpt-6.1-sol"
MAX_OPENAI_FILE_BYTES = 50_000_000
MIN_CHARS_PER_PAGE = 200  # darunter gilt eine PDF als gescannt: Claude bekommt die PDF selbst
MIN_CHARS_PER_SLIDE = 20  # PowerPoint/Word: der Text ist alles, was es gibt; Folien sind oft knapp
MAX_XML_BYTES = 50_000_000  # pro Teil einer PPTX/DOCX (Schutz vor gepackten Riesendateien)
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tex", ".py", ".java", ".r"}
OFFICE_SUFFIXES = {".pptx", ".docx"}
MAX_PDF_BYTES = 30_000_000
# Listenpreise in US-Dollar pro 1 Mio. Tokens (Stand 27.10.2026) für die Kostenschätzung:
# (gültig bis einschließlich Tag oder None, Eingabe, Ausgabe, Cache lesen, Cache schreiben).
# Claude: platform.claude.com (Cache schreiben = 1,25 × Eingabe); OpenAI: developers.openai.com/api/docs/pricing;
# Gemini: Einführungspreise laut Preisübersichten, danach doppelt (bei Google nicht selbst geprüft).
PRICES = {
    "claude-opus-5-5": [(None, 4.00, 20.00, 0.20, 5.00)],
    "claude-sonnet-5-5": [(None, 2.00, 10.00, 0.20, 2.50)],
    "claude-haiku-5-5": [(None, 0.10, 0.50, 0.01, 0.125)],  # bis 100.000 Tokens Eingabe, darüber das 5-Fache
    "claude-opus-5": [(None, 5.00, 25.00, 0.50, 6.25)],  # serverseitige Ausweichmodelle von Opus und Sonnet
    "claude-opus-4-8": [(None, 5.00, 25.00, 0.50, 6.25)],
    "gpt-6-astra": [(None, 10.00, 50.00, 1.00, 0)],
    "gpt-6.1-sol": [(None, 2.00, 10.00, 0.10, 0)],
    "gpt-6-luna": [(None, 0.10, 0.50, 0.01, 0)],
    "gemini-4-argon": [("2026-11-30", 2.00, 10.00, 0.10, 0), (None, 4.00, 20.00, 0.20, 0)],
    "gemini-3.8-flash": [("2026-12-31", 0.75, 3.75, 0.075, 0), (None, 1.50, 7.50, 0.15, 0)],
    "gemini-3.5-flash-lite": [(None, 0.30, 2.50, 0.03, 0)],
}
HAIKU_LONG_PROMPT = 100_000

SYSTEM = (
    "Du bist ein Lernassistent für Studierende der Universität Mannheim. Du bekommst ein "
    "Dokument aus einem ILIAS-Kurs (Vorlesungsfolien, Übungsblatt, Skript). Arbeite nur mit "
    "dem Inhalt dieses Dokuments; wenn etwas nicht darin steht, sag das. Antworte auf "
    "Deutsch, außer das Dokument ist englisch: dann Fachbegriffe englisch lassen und "
    "deutsch erklären. Nenne Seitenzahlen als (S. 3), wenn sie bekannt sind."
)
TASKS = {
    "summary": (
        "Erstelle eine Lernzusammenfassung in Markdown mit diesen Abschnitten:\n"
        "## Worum es geht (2–3 Sätze)\n## Kernaussagen (Stichpunkte)\n"
        "## Wichtige Begriffe (Begriff: Erklärung)\n## Prüfungsrelevant (was man können muss)\n"
        "Kompakt, aber ohne wichtige Formeln oder Definitionen wegzulassen."
    ),
    "flashcards": (
        "Erstelle 12 bis 20 Lernkarten zu den prüfungsrelevanten Inhalten. Vorderseite: "
        "eine präzise Frage. Rückseite: kurze, vollständige Antwort (max. 3 Sätze). "
        "Keine Fragen zu Organisatorischem (Termine, Räume, Klausuranmeldung)."
    ),
    "qa": "Beantworte diese Frage zum Dokument knapp und genau:\n\n{question}",
    "thema": (
        "Bereite das Dokument als Lernthema auf (für die StudyHub-Zusammenfassung):\n"
        "- titel: kurzer Thementitel (2–5 Wörter), nicht der Dateiname\n"
        "- kernidee: 3–4 Sätze, worum es geht und was man verstehen muss\n"
        "- einfacher: dieselbe Idee ganz einfach erklärt, mit Alltagsbeispiel, 2–3 Sätze\n"
        "- formeln: die wichtigsten Formeln (höchstens 5) als Name + nur die Formel in einfacher "
        "Textschreibweise (höchstens 60 Zeichen, keine Erklärsätze), z. B. „K_n = K_0 · q^n“; gibt es keine "
        "Formeln, die wichtigsten Definitionen als Name + Kurzdefinition (höchstens 12 Wörter)\n"
        "- falle: die typische Klausurfalle in 1–2 Sätzen\n"
        "- seite: Seite, auf der das Wichtigste steht"
    ),
}
FLASHCARD_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
                "required": ["front", "back"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}


THEMA_SCHEMA = {
    "type": "object",
    "properties": {
        "titel": {"type": "string"},
        "kernidee": {"type": "string"},
        "einfacher": {"type": "string"},
        "formeln": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "text": {"type": "string"}},
                "required": ["name", "text"],
                "additionalProperties": False,
            },
        },
        "falle": {"type": "string"},
        "seite": {"type": "integer"},
    },
    "required": ["titel", "kernidee", "einfacher", "formeln", "falle", "seite"],
    "additionalProperties": False,
}
# Aufgaben mit fester JSON-Antwort
TASK_SCHEMAS = {"flashcards": FLASHCARD_SCHEMA, "thema": THEMA_SCHEMA}


class AIError(Exception):
    pass


class AIFormatError(AIError):
    """Die KI hat geantwortet, aber kein gültiges JSON geliefert: betrifft nur diese eine Anfrage."""


# --- Zugang -------------------------------------------------------------------


def api_key() -> str | None:
    return keyring.get_password(core.KEYCHAIN_SERVICE, KEY_ACCOUNT) or os.environ.get("ANTHROPIC_API_KEY")


def has_profile() -> bool:
    """Angemeldet per „ant auth login“? Das SDK liest dieses Profil ohne API-Key selbst."""
    return any((Path.home() / ".config/anthropic/configs").glob("*.json"))


def claude_ready() -> bool:
    return bool(api_key()) or has_profile()


def set_api_key(key: str) -> None:
    if key:
        keyring.set_password(core.KEYCHAIN_SERVICE, KEY_ACCOUNT, key.strip())
    else:
        try:
            keyring.delete_password(core.KEYCHAIN_SERVICE, KEY_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass


def openai_key() -> str | None:
    return keyring.get_password(core.KEYCHAIN_SERVICE, OPENAI_KEY_ACCOUNT) or os.environ.get("OPENAI_API_KEY")


def set_openai_key(key: str) -> None:
    if key:
        keyring.set_password(core.KEYCHAIN_SERVICE, OPENAI_KEY_ACCOUNT, key.strip())
    else:
        try:
            keyring.delete_password(core.KEYCHAIN_SERVICE, OPENAI_KEY_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass


def google_key() -> str | None:
    return keyring.get_password(core.KEYCHAIN_SERVICE, GOOGLE_KEY_ACCOUNT) or os.environ.get("GEMINI_API_KEY")


def set_google_key(key: str) -> None:
    if key:
        keyring.set_password(core.KEYCHAIN_SERVICE, GOOGLE_KEY_ACCOUNT, key.strip())
    else:
        try:
            keyring.delete_password(core.KEYCHAIN_SERVICE, GOOGLE_KEY_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass


def ollama_models() -> list[str] | None:
    """Installierte Ollama-Modelle, oder None, wenn Ollama nicht läuft."""
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return [model["name"] for model in response.json().get("models", [])]


def gemma_model(models: list[str] | None = None) -> str:
    if forced := os.environ.get("ILIAS_SYNC_GEMMA"):
        return forced
    models = ollama_models() if models is None else models
    for name in GEMMA_PREFERENCE:
        if name in (models or []):
            return name
    return next((m for m in models or [] if m.startswith("gemma")), GEMMA_DEFAULT)


def gemma_small(model: str) -> bool:
    """Sehr kleine Modelle (270M, 1B) liefern an echten Kursdateien oft kein brauchbares JSON."""
    return model.endswith(("270m", "1b"))


def gemma_api_model() -> str:
    model = core.load_config().get("gemma_api_model")
    return model if model in GEMMA_API_MODELS else DEFAULT_GEMMA_API_MODEL


def gemma_backend(models: list[str] | None = None) -> str | None:
    """Wo Gemma läuft: "ollama" (lokal, bevorzugt), "api" (Gemini API mit Key) oder None."""
    models = ollama_models() if models is None else models
    if models is not None and gemma_model(models) in models:
        return "ollama"
    return "api" if google_key() else None


def providers() -> dict:
    models = ollama_models()
    model = gemma_model(models)
    local = models is not None and model in models
    api = bool(google_key())
    return {
        "claude": {"ready": claude_ready(), "models": CLAUDE_MODELS},
        "openai": {"ready": bool(openai_key()), "models": OPENAI_MODELS},
        "gemini": {"ready": api, "models": GEMINI_MODELS},
        "gemma": {
            "ready": local or api,
            "local": local,  # nur lokal läuft die automatische Vorbereitung (kein Kontingent)
            "small": local and gemma_small(model),  # zu klein für die automatische Vorbereitung
            "api": api,
            "ollama": models is not None,
            "model": model if local or not api else gemma_api_model(),
            "models": GEMMA_API_MODELS,
        },
    }


# --- Dokument -----------------------------------------------------------------


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:24]


def extract_pages(path: Path) -> list[str]:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        try:
            return [page.extract_text() or "" for page in PdfReader(path).pages]
        except Exception as error:  # beschädigte oder verschlüsselte PDFs
            raise AIError(f"PDF nicht lesbar: {error}") from None
    if path.suffix.lower() in TEXT_SUFFIXES:
        return [path.read_text(encoding="utf-8", errors="replace")]
    if path.suffix.lower() in OFFICE_SUFFIXES:
        try:
            return _pptx_pages(path) if path.suffix.lower() == ".pptx" else _docx_pages(path)
        except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as error:
            raise AIError(f"{path.name} nicht lesbar: {error}") from None
    raise AIError(f"Dateityp {path.suffix or '(ohne Endung)'} wird noch nicht unterstützt "
                  "(PDF, PowerPoint, Word und Text)")


def _xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    if archive.getinfo(name).file_size > MAX_XML_BYTES:
        raise AIError(f"{name} ist zu groß")
    return ElementTree.fromstring(archive.read(name))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _pptx_pages(path: Path) -> list[str]:
    """Eine „Seite“ pro Folie, in Folienreihenfolge; Absätze als Zeilen."""
    with zipfile.ZipFile(path) as archive:
        slides = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()))
        pages = []
        for name in slides:
            lines = ["".join(t.text or "" for t in p.iter() if _local(t.tag) == "t")
                     for p in _xml(archive, name).iter() if _local(p.tag) == "p"]
            pages.append("\n".join(line for line in lines if line.strip()))
    return pages


def _docx_pages(path: Path) -> list[str]:
    """Word kennt keine festen Seiten: getrennt wird an den Seitenumbrüchen, die Word beim letzten
    Speichern vermerkt hat (lastRenderedPageBreak) und an manuellen Seitenumbrüchen."""
    with zipfile.ZipFile(path) as archive:
        body = _xml(archive, "word/document.xml")
    pages, lines = [], []
    for paragraph in (e for e in body.iter() if _local(e.tag) == "p"):
        text = ""
        for element in paragraph.iter():
            tag = _local(element.tag)
            if tag == "t":
                text += element.text or ""
            elif tag == "tab":
                text += "\t"
            elif tag == "lastRenderedPageBreak" or (tag == "br" and any(
                    _local(k) == "type" and v == "page" for k, v in element.attrib.items())):
                if lines or text.strip():
                    pages.append("\n".join(lines + [text]).strip())
                lines, text = [], ""
        lines.append(text)
    pages.append("\n".join(lines).strip())
    return [p for p in pages if p] or [""]


def page_text(pages: list[str]) -> str:
    return "\n\n".join(f"[Seite {number}]\n{text.strip()}" for number, text in enumerate(pages, 1) if text.strip())


def is_scanned(pages: list[str], path: Path | None = None) -> bool:
    """Kaum Text: bei PDFs gescannte Folien. PowerPoint/Word-Folien sind oft knapp, dort gilt eine
    niedrigere Schwelle."""
    office = path is not None and path.suffix.lower() in OFFICE_SUFFIXES
    minimum = MIN_CHARS_PER_SLIDE if office else MIN_CHARS_PER_PAGE
    return sum(len(text.strip()) for text in pages) < minimum * max(1, len(pages))


# --- Cache --------------------------------------------------------------------


def _cache_file(digest: str) -> Path:
    return CACHE_DIR / f"{digest}.json"


def load_entry(path: Path, digest: str | None = None) -> dict:
    digest = digest or file_hash(path)
    file = _cache_file(digest)
    if file.exists():
        return json.loads(file.read_text(encoding="utf-8"))
    return {"hash": digest, "summary": None, "flashcards": None, "thema": None, "qa": []}


def save_entry(entry: dict, relative: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry["path"] = relative
    core.save_json(_cache_file(entry["hash"]), entry)


def thema_markdown(thema: dict) -> str:
    """Lernthema als Markdown-Zusammenfassung (Claude Desktop speichert sie mit; Teilen an Telegram/reMarkable)."""
    points = [f"- Einfach erklärt: {thema['einfacher']}"] if thema.get("einfacher") else []
    if thema.get("seite"):
        points.append(f"- Das Wichtigste steht auf S. {thema['seite']}.")
    lines = ["## Worum es geht", thema.get("kernidee", ""), ""]
    lines += ["## Kernaussagen", *points, ""] if points else []
    if thema.get("formeln"):
        lines += ["## Wichtige Begriffe", *[f"- **{f['name']}**: {f['text']}" for f in thema["formeln"]], ""]
    if thema.get("falle"):
        lines += ["## Prüfungsrelevant", f"- Typische Klausurfalle: {thema['falle']}"]
    return "\n".join(lines).strip()


def rename_folder(old: str, new: str) -> int:
    """Kursordner umbenannt: gespeicherte Pfade der Ergebnisse mitziehen (StudyHub findet sie über den Pfad)."""
    moved = 0
    for file in CACHE_DIR.glob("*.json") if CACHE_DIR.exists() else []:
        entry = json.loads(file.read_text(encoding="utf-8"))
        if path := core.moved_path(entry.get("path", ""), old, new):
            entry["path"] = path
            core.save_json(file, entry)
            moved += 1
    return moved


def all_entries() -> list[dict]:
    if not CACHE_DIR.exists():
        return []
    entries = [json.loads(file.read_text(encoding="utf-8")) for file in CACHE_DIR.glob("*.json")]
    return sorted(entries, key=lambda e: max([0] + [r["created"] for r in _results(e)]), reverse=True)


def _results(entry: dict) -> list[dict]:
    return [r for r in [entry.get("summary"), entry.get("flashcards"), entry.get("thema"), *entry.get("qa", [])] if r]


def cost(result: dict) -> float | None:
    """Geschätzte Kosten eines Ergebnisses in US-Dollar nach dem Listenpreis am Erstellungstag.
    0 für Gemma (lokal oder kostenloses Kontingent), None ohne bekannten Preis (z. B. Claude Desktop)."""
    if result.get("provider") == "gemma":
        return 0.0
    model = str(result.get("model") or "")
    key = next((k for k in sorted(PRICES, key=len, reverse=True) if model.startswith(k)), None)
    if key is None or "tokens_in" not in result:
        return None
    day = time.strftime("%Y-%m-%d", time.localtime(result.get("created") or time.time()))
    _, rate_in, rate_out, rate_read, rate_write = next(r for r in PRICES[key] if r[0] is None or day <= r[0])
    tokens = [result.get(k) or 0 for k in ("tokens_in", "tokens_out", "cache_read", "cache_write")]
    factor = 5 if key == "claude-haiku-5-5" and tokens[0] + tokens[2] + tokens[3] > HAIKU_LONG_PROMPT else 1
    return factor * sum(t * r for t, r in zip(tokens, (rate_in, rate_out, rate_read, rate_write), strict=True)) / 1e6


def usage(month: str | None = None) -> dict:
    """Gespeicherte KI-Ergebnisse eines Monats (JJJJ-MM, Standard: aktueller) mit geschätzten Kosten.
    Ersetzte Ergebnisse und Gespräche im Sprachtutor sind nicht enthalten."""
    month = month or time.strftime("%Y-%m")
    total, counted, unpriced, by_provider = 0.0, 0, 0, {}
    for entry in all_entries():
        for result in _results(entry):
            if time.strftime("%Y-%m", time.localtime(result.get("created") or 0)) != month:
                continue
            counted += 1
            value = result["cost_usd"] if "cost_usd" in result else cost(result)
            provider = result.get("provider", "?")
            if value is None:
                unpriced += 1
                continue
            total += value
            by_provider[provider] = by_provider.get(provider, 0.0) + value
    return {"monat": month, "ergebnisse": counted, "kosten_usd": round(total, 4), "ohne_preis": unpriced,
            "nach_anbieter": {k: round(v, 4) for k, v in sorted(by_provider.items())}}


# --- Claude -------------------------------------------------------------------


def _claude_send(params: dict):
    """Schickt eine Anfrage an Claude; übersetzt Fehler und Ablehnungen in AIError."""
    import anthropic

    key = api_key()
    if not key and not has_profile():
        raise AIError("Kein Anthropic-API-Key hinterlegt (Einstellungen › KI)")
    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    try:
        if params["model"] == "claude-haiku-5-5":  # für Haiku gibt es keine serverseitige Ausweichlösung
            response = client.messages.create(**params)
        else:
            response = client.beta.messages.create(
                **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            )
    except anthropic.AuthenticationError:
        raise AIError("Anthropic-API-Key ungültig") from None
    except anthropic.RateLimitError:
        raise AIError("Anthropic-Limit erreicht, bitte gleich noch einmal versuchen") from None
    except anthropic.BadRequestError as error:
        raise AIError(f"Anfrage abgelehnt: {error.message}") from None
    except anthropic.APIStatusError as error:
        raise AIError(f"Anthropic-Fehler {error.status_code}") from None
    except anthropic.APIConnectionError:
        raise AIError("Keine Verbindung zur Anthropic-API") from None
    if response.stop_reason == "refusal":
        raise AIError("Claude hat die Anfrage abgelehnt")
    return response


def _claude(pages: list[str], path: Path, task: str, instruction: str, model: str) -> tuple[str | dict, dict]:
    if is_scanned(pages) and path.suffix.lower() == ".pdf":
        if path.stat().st_size > MAX_PDF_BYTES:
            raise AIError("Gescannte PDF ist größer als 30 MB, bitte aufteilen")
        document = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(path.read_bytes()).decode()},
            "title": path.name,
        }
        mode = "PDF (gescannt, als Bild gelesen)"
    else:
        document = {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": page_text(pages)},
            "title": path.name,
        }
        mode = "Text"
    # Dokument zuerst und gecacht: Zusammenfassung, Karten und Fragen teilen sich diesen Prefix
    document["cache_control"] = {"type": "ephemeral"}
    params = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": [document, {"type": "text", "text": instruction}]}],
        "output_config": {"effort": "medium"},
    }
    if task in TASK_SCHEMAS:
        params["output_config"]["format"] = {"type": "json_schema", "schema": TASK_SCHEMAS[task]}

    response = _claude_send(params)
    text = "".join(block.text for block in response.content if block.type == "text")
    usage = response.usage
    meta = {
        "provider": "claude", "model": response.model, "input_mode": mode,
        "tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens,
        "cache_read": usage.cache_read_input_tokens or 0, "cache_write": usage.cache_creation_input_tokens or 0,
    }
    if response.stop_reason == "max_tokens":
        if task in TASK_SCHEMAS:
            raise AIError("Antwort am Längenlimit abgeschnitten, Ergebnis unvollständig")
        meta["note"] = "Antwort wurde am Längenlimit abgeschnitten"
    return (_parse_json(text, "Claude") if task in TASK_SCHEMAS else text), meta


def _parse_json(text: str, name: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:
        raise AIFormatError(f"{name} hat kein gültiges JSON geliefert, bitte noch einmal versuchen") from None


# --- ChatGPT (OpenAI) ---------------------------------------------------------


def _openai_send(body: dict) -> tuple[dict, str]:
    """Schickt eine Anfrage an die Responses API. Liefert (Antwort-JSON, Ausgabetext)."""
    key = openai_key()
    if not key:
        raise AIError("Kein OpenAI-API-Key hinterlegt (Einstellungen › KI)")
    try:
        response = httpx.post(OPENAI_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=300)
    except httpx.TimeoutException:
        raise AIError("ChatGPT hat nach 5 Minuten nicht geantwortet") from None
    except httpx.HTTPError:
        raise AIError("Keine Verbindung zur OpenAI-API") from None
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        raise AIError({401: "OpenAI-API-Key ungültig",
                       429: "OpenAI-Limit oder Guthaben erreicht"}.get(response.status_code)
                      or f"OpenAI-Fehler {response.status_code}: {detail[:200]}") from None

    result = response.json()
    if result.get("status") == "failed":
        raise AIError(f"OpenAI-Fehler: {(result.get('error') or {}).get('message', 'unbekannt')}")
    parts = [part for item in result.get("output", []) if item.get("type") == "message"
             for part in item.get("content", [])]
    if any(part.get("type") == "refusal" for part in parts):
        raise AIError("ChatGPT hat die Anfrage abgelehnt")
    return result, "".join(part.get("text", "") for part in parts if part.get("type") == "output_text")


def _openai(pages: list[str], path: Path, task: str, instruction: str, model: str) -> tuple[str | dict, dict]:
    if is_scanned(pages) and path.suffix.lower() == ".pdf":
        if path.stat().st_size > MAX_OPENAI_FILE_BYTES:
            raise AIError("Gescannte PDF ist größer als 50 MB, bitte aufteilen")
        data = base64.standard_b64encode(path.read_bytes()).decode()
        document = {"type": "input_file", "filename": path.name, "file_data": f"data:application/pdf;base64,{data}"}
        mode = "PDF (gescannt, als Bild gelesen)"
    else:
        document = {"type": "input_text", "text": f"Dokument „{path.name}“:\n\n{page_text(pages)}"}
        mode = "Text"
    # Dokument zuerst, Aufgabe zuletzt: OpenAI cacht den gleichbleibenden Anfang automatisch
    body = {
        "model": model,
        "instructions": SYSTEM,
        "input": [{"role": "user", "content": [document, {"type": "input_text", "text": instruction}]}],
        "max_output_tokens": 16000,
        "store": False,  # Vorlesungsinhalte nicht bei OpenAI ablegen
    }
    if task in TASK_SCHEMAS:
        body["text"] = {"format": {"type": "json_schema", "name": task, "strict": True,
                                   "schema": TASK_SCHEMAS[task]}}
    result, text = _openai_send(body)
    usage = result.get("usage") or {}
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    meta = {
        "provider": "openai", "model": result.get("model", model), "input_mode": mode,
        "tokens_in": usage.get("input_tokens", 0) - cached, "tokens_out": usage.get("output_tokens", 0),
        "cache_read": cached, "cache_write": 0,
    }
    if result.get("status") == "incomplete":
        if task in TASK_SCHEMAS:
            raise AIError("Antwort am Längenlimit abgeschnitten, Ergebnis unvollständig")
        meta["note"] = "Antwort wurde am Längenlimit abgeschnitten"
    return (_parse_json(text, "ChatGPT") if task in TASK_SCHEMAS else text), meta


# --- Gemini (Gemini API) ------------------------------------------------------


def _gemini_body(system: str, parts: list[dict], schema: dict | None, max_tokens: int) -> dict:
    """Anfrage an ein Gemini-Modell. Mit Schema antwortet Gemini im JSON-Modus; das Schema steht im
    Prompt, die Antwort wird danach geprüft (_gemini_json)."""
    config = {"maxOutputTokens": max_tokens}
    if schema:
        parts = [*parts, {"text": _schema_prompt(schema).strip()}]
        config["responseMimeType"] = "application/json"
    return {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}], "generationConfig": config}


def _gemini_json(text: str, schema: dict) -> dict:
    try:
        result = json.loads(_json_text(text))
    except ValueError:
        raise AIFormatError("Gemini hat kein gültiges JSON geliefert, bitte noch einmal versuchen") from None
    if not isinstance(result, dict) or not all(key in result for key in schema.get("required", [])):
        raise AIFormatError("Gemini hat unvollständiges JSON geliefert, bitte noch einmal versuchen")
    return result


def _gemini_doc(pages: list[str], path: Path, task: str, instruction: str, model: str) -> tuple[str | dict, dict]:
    if is_scanned(pages) and path.suffix.lower() == ".pdf":
        if path.stat().st_size > MAX_GEMINI_PDF_BYTES:
            raise AIError("Gescannte PDF ist größer als 20 MB, bitte aufteilen")
        document = {"inlineData": {"mimeType": "application/pdf",
                                   "data": base64.standard_b64encode(path.read_bytes()).decode()}}
        mode = "PDF (gescannt, als Bild gelesen)"
    else:
        document = {"text": f"Dokument „{path.name}“:\n\n{page_text(pages)}"}
        mode = "Text"
    # Dokument zuerst, Aufgabe zuletzt: gleiche Anfänge cacht die Gemini API automatisch
    schema = TASK_SCHEMAS.get(task)
    data = _gemini_post(model, _gemini_body(SYSTEM, [document, {"text": instruction}], schema, GEMINI_DOC_TOKENS),
                        "Gemini")
    usage = data.get("usageMetadata") or {}
    cached = usage.get("cachedContentTokenCount", 0)
    meta = {
        "provider": "gemini", "model": data.get("modelVersion") or model, "input_mode": mode,
        "tokens_in": usage.get("promptTokenCount", 0) - cached,
        "tokens_out": usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
        "cache_read": cached, "cache_write": 0,
    }
    text = _gemini_text(data)
    if data["candidates"][0].get("finishReason") == "MAX_TOKENS":
        if schema:
            raise AIError("Antwort am Längenlimit abgeschnitten, Ergebnis unvollständig")
        meta["note"] = "Antwort wurde am Längenlimit abgeschnitten"
    return (_gemini_json(text, schema) if schema else text), meta


# --- Gemma (Ollama) -----------------------------------------------------------


def _ollama(system: str, prompt: str, schema: dict | None, max_tokens: int) -> str:
    body = {
        "model": gemma_model(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_ctx": GEMMA_CONTEXT, "temperature": 0.3, "num_predict": max_tokens},
    }
    if schema:
        body["format"] = schema
    try:
        response = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=600)
        response.raise_for_status()
    except httpx.ConnectError:
        raise AIError("Gemma nicht bereit: die Ollama-App starten (ollama.com/download) oder "
                      "Google-AI-API-Key in den Einstellungen eintragen") from None
    except httpx.HTTPStatusError as error:
        raise AIError(f"Ollama-Fehler: {error.response.text[:200]}") from None
    except httpx.TimeoutException:
        raise AIError("Gemma hat nach 10 Minuten nicht geantwortet") from None
    return response.json()["message"]["content"]


def _json_text(text: str) -> str:
    """JSON aus einer Modellantwort lösen, auch wenn es in ```json … ``` oder in Text steht."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def _gemini_post(model: str, body: dict, label: str) -> dict:
    """Eine Anfrage an generateContent der Gemini API (Gemma und Gemini). Wiederholt vorübergehende
    Fehler, übersetzt Fehler in AIError und liefert die Antwort mit mindestens einem Kandidaten."""
    for attempt in range(GEMINI_TRIES):
        try:
            response = httpx.post(GEMINI_URL.format(model=model), json=body, timeout=600,
                                  headers={"x-goog-api-key": google_key() or ""})
        except httpx.TimeoutException:
            raise AIError(f"{label} hat nach 10 Minuten nicht geantwortet") from None
        except httpx.HTTPError:
            raise AIError("Keine Verbindung zur Gemini API") from None
        # Google liefert ab und zu 500 oder eine leere Antwort; ein neuer Versuch klappt meist
        empty = response.status_code == 200 and not response.json().get("candidates") \
            and not (response.json().get("promptFeedback") or {}).get("blockReason")
        if (response.status_code in (500, 503) or empty) and attempt < GEMINI_TRIES - 1:
            time.sleep(2 * (attempt + 1))
            continue
        break
    if response.status_code >= 400:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text
        if response.status_code in (401, 403) or "API_KEY_INVALID" in response.text or "API key" in message:
            raise AIError("Google-AI-API-Key ungültig (Einstellungen › KI)")
        if response.status_code == 429:
            raise AIError("Gemini-Kontingent erschöpft, bitte später noch einmal versuchen")
        if response.status_code == 404:
            raise AIError(f"Modell {model} gibt es bei der Gemini API nicht")
        raise AIError(f"Gemini-API-Fehler: {message[:200]}")
    data = response.json()
    if not data.get("candidates"):
        reason = (data.get("promptFeedback") or {}).get("blockReason", "ohne Grund")
        raise AIError(f"Die Gemini API hat keine Antwort geliefert ({reason})")
    return data


def _gemini_text(data: dict) -> str:
    parts = (data["candidates"][0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))  # Denkschritte weglassen


def _schema_prompt(schema: dict) -> str:
    return ("\n\nAntworte nur mit einem JSON-Objekt nach diesem JSON-Schema, ohne weiteren Text:\n"
            + json.dumps(schema, ensure_ascii=False))


def _gemini(system: str, prompt: str, schema: dict | None, max_tokens: int) -> str:
    """Gemma über die Gemini API (Google AI Studio). Ohne verlässliche Schema-Vorgabe für Gemma
    steht das Schema im Prompt; das JSON wird aus der Antwort gelöst und vom Aufrufer geprüft."""
    if schema:
        prompt += _schema_prompt(schema)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens},
    }
    text = _gemini_text(_gemini_post(gemma_api_model(), body, "Gemma (Gemini API)"))
    return _json_text(text) if schema else text


def _gemma_send(system: str, prompt: str, schema: dict | None = None, max_tokens: int = 4000,
                backend: str | None = None) -> str:
    """Eine Anfrage an Gemma, lokal über Ollama oder über die Gemini API."""
    if (backend or gemma_backend()) == "api":
        return _gemini(system, prompt, schema, max_tokens)
    return _ollama(system, prompt, schema, max_tokens)


def _chunks(pages: list[str]) -> list[str]:
    chunks, current = [], ""
    for number, text in enumerate(pages, 1):
        part = f"[Seite {number}]\n{text.strip()}\n\n" if text.strip() else ""
        if current and len(current) + len(part) > GEMMA_CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current += part
    return [c for c in chunks + [current] if c.strip()]


def _relevant(chunks_: list[str], question: str, limit: int) -> str:
    """Wählt per Wortüberschneidung die Abschnitte, die am besten zur Frage passen."""
    words = {w for w in re.findall(r"\w{4,}", question.lower())}
    paragraphs = [p for chunk in chunks_ for p in chunk.split("\n\n") if p.strip()]
    scored = sorted(paragraphs, key=lambda p: -sum(p.lower().count(w) for w in words))
    picked, size = [], 0
    for paragraph in scored:
        if size + len(paragraph) > limit:
            continue  # zu groß für den Rest des Budgets, kleinere passende Abschnitte noch prüfen
        picked.append(paragraph)
        size += len(paragraph)
    return "\n\n".join(sorted(picked, key=paragraphs.index))


def _gemma(pages: list[str], path: Path, task: str, instruction: str, question: str) -> tuple[str | dict, dict]:
    if is_scanned(pages, path):
        raise AIError("Dokument enthält kaum Text (gescannte Folien). Gemma liest nur Text, bitte Claude nutzen.")
    parts = _chunks(pages)
    backend = gemma_backend()
    model = gemma_api_model() if backend == "api" else gemma_model()
    meta = {"provider": "gemma", "model": model, "input_mode": "Text (Gemini API)" if backend == "api" else "Text",
            "sections": len(parts)}
    small = backend != "api" and gemma_small(model)

    def send(prompt: str, schema: dict | None = None) -> str:
        return _gemma_send(SYSTEM, prompt, schema, backend=backend)

    warning = "Kleines lokales Modell: Inhalte unbedingt prüfen" if small else ""
    if task == "qa":
        text = _relevant(parts, question, GEMMA_CHUNK_CHARS)
        if len(parts) > 1:
            meta["note"] = "Gemma hat nur die zur Frage passendsten Abschnitte gelesen"
    elif len(parts) == 1:
        text = parts[0]
    else:
        # Map-Reduce: erst jeden Abschnitt verdichten, dann daraus das Ergebnis bauen
        notes = [send(f"Dokumentabschnitt:\n\n{part}\n\nFasse die Lerninhalte dieses Abschnitts in "
                         "Stichpunkten zusammen, mit Seitenzahlen, Definitionen und Formeln.") for part in parts]
        text = "\n\n".join(notes)
        meta["note"] = f"Langes Dokument: in {len(parts)} Abschnitten verarbeitet"
    if warning:
        meta["note"] = "; ".join(filter(None, [meta.get("note"), warning]))
    prompt = f"Dokument:\n\n{text}\n\n{instruction}"
    if task in TASK_SCHEMAS:
        try:
            return json.loads(send(prompt, TASK_SCHEMAS[task])), meta
        except ValueError:
            raise AIFormatError("Gemma hat kein gültiges JSON geliefert, bitte noch einmal versuchen") from None
    return send(prompt), meta


# --- Kurze Anfragen (Tutor) ---------------------------------------------------


def complete(provider: str, system: str, prompt: str, schema: dict | None = None, model: str | None = None):
    """Eine einzelne Anfrage ohne Dokument-Cache. Mit schema kommt ein dict zurück, sonst Text."""
    if provider == "gemma":
        # Ausgabe begrenzen: kleine Modelle laufen bei JSON-Vorgabe sonst endlos weiter
        text = _gemma_send(system, prompt, schema, max_tokens=2000)
    elif provider == "claude":
        params = {"model": model or DEFAULT_CLAUDE_MODEL, "max_tokens": 4000, "system": system,
                  "messages": [{"role": "user", "content": prompt}], "output_config": {"effort": "low"}}
        if schema:
            params["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        response = _claude_send(params)
        text = "".join(block.text for block in response.content if block.type == "text")
    elif provider == "openai":
        body = {"model": model or DEFAULT_OPENAI_MODEL, "instructions": system, "store": False,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "max_output_tokens": 4000}
        if schema:
            body["text"] = {"format": {"type": "json_schema", "name": "result", "strict": True, "schema": schema}}
        _, text = _openai_send(body)
    elif provider == "gemini":
        # Großzügig: bei Gemini zählen die Denkschritte zur Ausgabe
        body = _gemini_body(system, [{"text": prompt}], schema, 8000)
        text = _gemini_text(_gemini_post(model or DEFAULT_GEMINI_MODEL, body, "Gemini"))
        return _gemini_json(text, schema) if schema else text
    else:
        raise AIError(f"Unbekannter Anbieter {provider}")
    if not schema:
        return text
    try:
        return json.loads(text)
    except ValueError:
        raise AIFormatError("Die KI hat kein gültiges JSON geliefert, bitte noch einmal versuchen") from None


# --- Einstieg -----------------------------------------------------------------


def run(path: Path, relative: str, task: str, provider: str, model: str | None = None,
        question: str = "", force: bool = False) -> dict:
    """Führt eine Lernfunktion aus und liefert das (ggf. gespeicherte) Ergebnis."""
    if task not in TASKS:
        raise AIError(f"Unbekannte Aufgabe {task}")
    if task == "qa" and not question.strip():
        raise AIError("Bitte eine Frage eingeben")
    entry = load_entry(path)
    if task != "qa" and entry.get(task) and not force:
        return {**entry[task], "cached": True}
    if task == "qa" and not force:
        for answer in entry["qa"]:
            if answer["question"].strip().lower() == question.strip().lower() and answer["provider"] == provider:
                return {**answer, "cached": True}

    pages = extract_pages(path)
    instruction = TASKS[task].format(question=question.strip())
    started = time.monotonic()
    if provider == "claude":
        output, meta = _claude(pages, path, task, instruction, model or DEFAULT_CLAUDE_MODEL)
    elif provider == "openai":
        output, meta = _openai(pages, path, task, instruction, model or DEFAULT_OPENAI_MODEL)
    elif provider == "gemini":
        output, meta = _gemini_doc(pages, path, task, instruction, model or DEFAULT_GEMINI_MODEL)
    elif provider == "gemma":
        output, meta = _gemma(pages, path, task, instruction, question)
    else:
        raise AIError(f"Unbekannter Anbieter {provider}")
    result = {**meta, "output": output, "created": time.time(), "seconds": round(time.monotonic() - started, 1)}
    result["cost_usd"] = cost(result)  # Preis am Erstellungstag festhalten
    # Frisch laden: Während der KI-Anfrage kann z. B. Claude Desktop (MCP) ein anderes Ergebnis gespeichert haben
    entry = load_entry(path, entry["hash"])
    if task == "qa":
        result["question"] = question.strip()
        entry.setdefault("qa", []).append(result)
    else:
        entry[task] = result
    save_entry(entry, relative)
    return {**result, "cached": False}
