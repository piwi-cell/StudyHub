"""Lokale API der Mac-App. Sie ruft nur Funktionen des bestehenden ILIAS-Sync-Kerns auf.

Erreichbar nur über 127.0.0.1 und nur mit dem Sitzungs-Token, den die App beim Start
erzeugt: Andere Webseiten im Browser können die API so nicht ansprechen.
"""

import os
import re
import secrets
import subprocess
import sys
import threading
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
os.environ.setdefault("ILIAS_SYNC_APP", "1")
os.environ.setdefault("ILIAS_SYNC_PYTHON", sys.executable)

import fcntl  # noqa: E402

import keyring  # noqa: E402
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import ai  # noqa: E402
import cards  # noqa: E402
import cli  # noqa: E402
import core  # noqa: E402
import courses  # noqa: E402
import goodnotes  # noqa: E402
import integrations  # noqa: E402
import libraries  # noqa: E402
import schedule  # noqa: E402
import studyhub  # noqa: E402
import sync  # noqa: E402
import telegram_bot  # noqa: E402
import tutor  # noqa: E402
import uploads  # noqa: E402
import voice  # noqa: E402
from core import APP_DIR, KEYCHAIN_SERVICE, MIRROR_DIR  # noqa: E402

TOKEN = os.environ.get("ILIAS_SYNC_TOKEN") or secrets.token_urlsafe(24)
DEMO = bool(os.environ.get("ILIAS_SYNC_HOME"))
UI_DIR = ROOT / "ui"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

APP_DIR.mkdir(parents=True, exist_ok=True)
_sync_thread: threading.Thread | None = None
_sync_error: str | None = None
_tutor_wake = threading.Event()  # weckt die automatische Tutor-Vorbereitung (z. B. nach einem Abgleich)
_stopping = threading.Event()
TUTOR_AUTO_INTERVAL = 600  # Sekunden zwischen zwei Durchläufen der Tutor-Vorbereitung


def tutor_auto_worker() -> None:
    """Bereitet im Hintergrund neue Kursdateien für den Study-Tutor vor (Gemma, kostenlos)."""
    _tutor_wake.wait(5)  # App erst in Ruhe starten lassen
    while not _stopping.is_set():
        _tutor_wake.clear()
        try:
            gemma = ai.providers()["gemma"]
            if not core.load_config().get("tutor_auto", True):
                tutor.progress["error"] = ""
            elif not gemma["local"]:
                # Über die Gemini API nicht automatisch: das würde das kostenlose Kontingent aufbrauchen
                tutor.progress["error"] = "Automatische Vorbereitung nur mit Gemma lokal (Ollama)"
            elif gemma["small"]:
                # 270M und 1B scheitern an echten Kursdateien am JSON: lieber gar nicht als endlos abbrechen
                tutor.progress["error"] = (f"{gemma['model']} ist für automatische Fragen zu klein: im Terminal "
                                           "„ollama pull gemma3:4b“ ausführen")
            elif not sync_running():
                files = [(p, core.nfc(p.relative_to(MIRROR_DIR).as_posix())) for p in mirror_files()]
                tutor.prepare_pending(files, stop=_stopping.is_set)
        except Exception as error:  # der Hintergrund-Thread darf die App nie mitreißen
            core.log(f"Tutor: automatische Vorbereitung fehlgeschlagen ({error})")
        _tutor_wake.wait(TUTOR_AUTO_INTERVAL)


def library_worker() -> None:
    """Misst die Auslastung der Bibliotheken, solange die App läuft (außer der launchd-Job misst schon)."""
    _stopping.wait(10)
    try:
        libraries.background_refresh()
    except Exception as error:  # der Hintergrund-Thread darf die App nie mitreißen
        core.log(f"Bibliotheken: Hintergrund-Job nicht aktualisiert ({error})")
    last_error = ""
    while not _stopping.is_set():
        try:
            if not libraries.background_active():
                libraries.sample()
            last_error = ""
        except libraries.LibraryError as error:
            if str(error) != last_error:  # nicht alle zehn Minuten dieselbe Meldung
                core.log(f"Bibliotheken: {error}")
            last_error = str(error)
        except Exception as error:  # der Hintergrund-Thread darf die App nie mitreißen
            core.log(f"Bibliotheken: Messung fehlgeschlagen ({error})")
        _stopping.wait(libraries.INTERVAL)


def schedule_refresh() -> None:
    """Abgleich-Job der App auf diese Installation umstellen (nach einem Update oder Umzug)."""
    try:
        if schedule.refresh(core.load_config()["interval_minutes"]):
            core.log(f"Abgleich: Hintergrund-Job nutzt jetzt {ROOT}")
    except Exception as error:  # der Hintergrund-Thread darf die App nie mitreißen
        core.log(f"Abgleich: Hintergrund-Job nicht aktualisiert ({error})")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _stopping.clear()
    threading.Thread(target=tutor_auto_worker, daemon=True, name="tutor-auto").start()
    if not DEMO:  # Demo-Modus und Tests rufen die Seite der UB und Telegram nie ab
        threading.Thread(target=schedule_refresh, daemon=True, name="abgleich-job").start()
        threading.Thread(target=library_worker, daemon=True, name="bibliotheken").start()
        threading.Thread(target=integrations.run_telegram_bot, args=(_stopping, {"bib": libraries.answer_bib}),
                         daemon=True, name="telegram-bot").start()
    yield
    _stopping.set()
    _tutor_wake.set()


app = FastAPI(title="StudyHub", lifespan=lifespan)


def check_token(request: Request, t: str | None = Query(None)) -> None:
    if not secrets.compare_digest(request.headers.get("x-app-token") or t or "", TOKEN):
        raise HTTPException(403, "Ungültiger Sitzungs-Token")


api = Depends(check_token)


# --- Hilfen -------------------------------------------------------------------


def sync_running() -> bool:
    if _sync_thread and _sync_thread.is_alive():
        return True
    if not sync.LOCK_FILE.exists():
        return False
    with open(sync.LOCK_FILE, "a") as lock:  # läuft ein Abgleich aus dem Hintergrund-Job?
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def mirror_path(relative: str) -> Path:
    path = (MIRROR_DIR / relative).resolve()
    if MIRROR_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    return path


def mirror_files(hidden: bool = False) -> list[Path]:
    """Dateien im Spiegel. In StudyHub ausgeblendete Dateien fehlen (überall in der App: Dokumente,
    Lernplan, Tutor, MCP); hidden=True liefert nur diese."""
    if not MIRROR_DIR.exists():
        return []
    skip = studyhub.hidden_files()
    return [p for p in MIRROR_DIR.rglob("*")
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(MIRROR_DIR).parts)
            and (core.nfc(p.relative_to(MIRROR_DIR).as_posix()) in skip) == hidden]


def file_info(path: Path, cached: dict[str, dict]) -> dict:
    relative = core.nfc(path.relative_to(MIRROR_DIR).as_posix())
    stat = path.stat()
    entry = cached.get(relative, {})
    return {
        "path": relative,
        "name": path.name,
        "course": relative.split("/", 1)[0],
        "folder": "/".join(relative.split("/")[1:-1]),
        "ext": path.suffix.lower().lstrip("."),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "ai": {"summary": bool(entry.get("summary")), "flashcards": bool(entry.get("flashcards")),
               "qa": len(entry.get("qa", []))},
    }


def provider_model(config: dict, provider: str) -> str | None:
    """In den Einstellungen gewähltes Modell eines Anbieters (Gemma wählt sein Modell selbst)."""
    return {"claude": config.get("claude_model"), "openai": config.get("openai_model"),
            "gemini": config.get("gemini_model")}.get(provider)


def cached_by_path() -> dict[str, dict]:
    return {e["path"]: e for e in ai.all_entries() if "path" in e}


def log_tail(lines: int = 60) -> list[str]:
    if not core.LOG_FILE.exists():
        return []
    return core.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]


# --- Seiten -------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (UI_DIR / "index.html").read_text(encoding="utf-8")


class UIFiles(StaticFiles):
    """Oberfläche immer beim Server nachfragen (ETag): Ohne Angabe cachen Browser Skripte heuristisch und
    zeigen nach einem Update sonst die alte Fassung."""

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/ui", UIFiles(directory=UI_DIR), name="ui")


# --- Status -------------------------------------------------------------------


@app.get("/api/status", dependencies=[api])
def status() -> dict:
    config, state = core.load_config(), core.load_state()
    files = mirror_files()
    cached = cached_by_path()
    recent = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    running = sync_running()
    return {
        "demo": DEMO,
        "configured": bool(config["uni_id"] and config["target_dir"]),
        "uni_id": config["uni_id"],
        "target_dir": config["target_dir"],
        "interval": config["interval_minutes"],
        "schedule_active": schedule.is_active() if not DEMO else False,
        "last_sync": cli.last_sync_line(),
        "running": running,
        "progress": sync.read_progress() if running else None,  # {"text": "3 von 8 Kursen fertig · 1:20", …}
        "sync_error": _sync_error,
        "crawl_failures": state["crawl_failures"],
        "courses_total": len(config["courses"]),
        "courses_synced": sum(1 for s in config["courses"].values() if s["sync"]),
        "files": len(files),
        "ai_results": sum(1 for e in cached.values() for r in ai._results(e)),
        "recent": [file_info(p, cached) for p in recent],
        "modules": {"telegram": config["telegram"], "goodnotes": config["goodnotes"], "notion": bool(config["notion"])},
        "log": log_tail(12),
    }


@app.post("/api/sync", dependencies=[api])
def start_sync() -> dict:
    global _sync_thread, _sync_error
    if sync_running():
        return {"started": False, "message": "Ein Abgleich läuft bereits"}
    if DEMO:
        return {"started": False, "message": "Demo-Modus: kein Abruf von ILIAS"}

    def worker():
        global _sync_error
        _sync_error = None
        try:
            sync.run()
        except Exception as error:  # sync.run fängt selbst fast alles ab
            _sync_error = str(error)
        _tutor_wake.set()  # neue Dateien gleich für den Tutor vorbereiten

    _sync_thread = threading.Thread(target=worker, daemon=True)
    _sync_thread.start()
    return {"started": True}


@app.get("/api/log", dependencies=[api])
def log() -> dict:
    return {"lines": log_tail(200)}


# --- Kurse --------------------------------------------------------------------


@app.get("/api/courses", dependencies=[api])
def list_courses() -> dict:
    config = core.load_config()
    counts: dict[str, int] = {}
    for path in mirror_files():
        top = path.relative_to(MIRROR_DIR).parts[0]
        counts[top] = counts.get(top, 0) + 1
    items = [{"title": t, **s, "files": counts.get(s["name"].split("/")[0], 0) if not s.get("group") else None}
             for t, s in config["courses"].items()]
    return {"courses": sorted(items, key=lambda c: c["name"].casefold()),
            "include_new": config["include_new_courses"]}


class CourseUpdate(BaseModel):
    title: str
    sync: bool | None = None
    name: str | None = None


@app.patch("/api/courses", dependencies=[api])
def update_course(update: CourseUpdate) -> dict:
    if sync_running():
        raise HTTPException(409, "Gerade läuft ein Abgleich, bitte gleich noch einmal versuchen")
    config, state = core.load_config(), core.load_state()
    if update.title not in config["courses"]:
        raise HTTPException(404, "Kurs nicht gefunden")
    if update.sync is not None:
        config["courses"][update.title]["sync"] = update.sync
    old = config["courses"][update.title]["name"]
    if update.name:
        if not cli.rename_course(config, state, update.title, update.name):
            raise HTTPException(409, f"„{courses.safe_folder_name(update.name)}“ ist schon vergeben")
    core.save_config(config)
    core.save_state(state)
    if (new := config["courses"][update.title]["name"]) != old:
        rename_app_data(old, new)
    return {"ok": True}


def rename_app_data(old: str, new: str) -> None:
    """Kursordner umbenannt: KI-Ergebnisse, Lernplan, Karten und Tutor hängen am Pfad und ziehen mit."""
    ai.rename_folder(old, new)
    studyhub.rename_folder(old, new)
    cards.rename_folder(old, new, cached_by_path())
    tutor.rename_folder(old, new)
    core.log(f"Kurs umbenannt: {old} → {new} (Lernstand und KI-Ergebnisse übernommen)")


class IncludeNew(BaseModel):
    include_new: bool


@app.post("/api/courses/include-new", dependencies=[api])
def include_new(body: IncludeNew) -> dict:
    config = core.load_config()
    config["include_new_courses"] = body.include_new
    core.save_config(config)
    return {"ok": True}


# --- Dateien ------------------------------------------------------------------


@app.get("/api/files", dependencies=[api])
def list_files() -> dict:
    cached = cached_by_path()
    files = [file_info(p, cached) for p in mirror_files()]
    files.sort(key=lambda f: (f["course"].casefold(), f["folder"].casefold(), f["name"].casefold()))
    return {"files": files}


@app.get("/api/file", dependencies=[api])
def get_file(path: str) -> FileResponse:
    file = mirror_path(path)
    return FileResponse(file, content_disposition_type="inline", filename=file.name)


@app.post("/api/reveal", dependencies=[api])
def reveal(body: dict) -> dict:
    config = core.load_config()
    file = mirror_path(body.get("path", ""))  # nur Dateien aus dem Spiegel, kein „../“
    target = Path(config["target_dir"]) / file.relative_to(MIRROR_DIR.resolve()) if config["target_dir"] else None
    file = target if target and target.exists() else file
    subprocess.run(["open", "-R", str(file)], check=False)
    return {"ok": True}


@app.post("/api/open", dependencies=[api])
def open_file(body: dict) -> dict:
    subprocess.run(["open", str(mirror_path(body.get("path", "")))], check=False)
    return {"ok": True}


# --- KI -----------------------------------------------------------------------


@app.get("/api/ai/providers", dependencies=[api])
def ai_providers() -> dict:
    config = core.load_config()
    return {**ai.providers(), "default_provider": config.get("ai_provider", "claude"),
            "claude_model": config.get("claude_model", ai.DEFAULT_CLAUDE_MODEL),
            "openai_model": config.get("openai_model", ai.DEFAULT_OPENAI_MODEL),
            "gemini_model": config.get("gemini_model", ai.DEFAULT_GEMINI_MODEL),
            "gemma_api_model": ai.gemma_api_model()}


@app.get("/api/ai/usage", dependencies=[api])
def ai_usage(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$")) -> dict:
    """Geschätzte KI-Kosten eines Monats (gespeicherte Ergebnisse, Listenpreise; ohne Sprachtutor)."""
    return ai.usage(month)


@app.get("/api/ai/result", dependencies=[api])
def ai_result(path: str) -> dict:
    entry = ai.load_entry(mirror_path(path))
    return {"summary": entry.get("summary"), "flashcards": entry.get("flashcards"), "qa": entry.get("qa", [])}


class AIRequest(BaseModel):
    path: str
    task: str
    provider: str | None = None
    question: str = ""
    force: bool = False


@app.post("/api/ai/run", dependencies=[api])
def ai_run(body: AIRequest) -> dict:
    config = core.load_config()
    provider = body.provider or config.get("ai_provider", "claude")
    model = provider_model(config, provider)
    try:
        return ai.run(mirror_path(body.path), body.path, body.task, provider,
                      model=model, question=body.question, force=body.force)
    except ai.AIError as error:
        raise HTTPException(400, str(error)) from None


@app.get("/api/learn", dependencies=[api])
def learn() -> dict:
    items = []
    for entry in ai.all_entries():
        if not entry.get("path"):
            continue
        items.append({
            "path": entry["path"],
            "name": entry["path"].rsplit("/", 1)[-1],
            "course": entry["path"].split("/", 1)[0],
            "summary": entry.get("summary"),
            "flashcards": entry.get("flashcards"),
            "qa": len(entry.get("qa", [])),
        })
    return {"items": items}


class ShareRequest(BaseModel):
    path: str
    task: str  # summary | flashcards | original
    target: str  # telegram | remarkable


@app.post("/api/share", dependencies=[api])
def share(body: ShareRequest) -> dict:
    file = mirror_path(body.path)
    try:
        if body.task == "original":
            if body.target != "remarkable":
                raise HTTPException(400, "Originaldateien gehen nur ans reMarkable")
            return {"ok": True, "via": integrations.send_remarkable(file)}
        result = ai.load_entry(file).get(body.task)
        if not result:
            raise HTTPException(400, "Noch kein Ergebnis vorhanden")
        if body.target == "telegram":
            if not core.load_config()["telegram"]:
                raise HTTPException(400, "Telegram ist nicht verbunden (Einstellungen › Telegram)")
            integrations.send_telegram(file.stem, body.task, result["output"])
            return {"ok": True, "via": "Telegram"}
        label = "Lernkarten" if body.task == "flashcards" else "Zusammenfassung"
        pdf = integrations.text_to_pdf(integrations.result_as_text(file.stem, body.task, result["output"]),
                                       f"{file.stem} – {label}")
        return {"ok": True, "via": integrations.send_remarkable(pdf)}
    except integrations.ShareError as error:
        raise HTTPException(400, str(error)) from None


class ClaudeCoach(BaseModel):
    kurs: str | None = None


@app.post("/api/claude/open", dependencies=[api])
def claude_open(body: ClaudeCoach) -> dict:
    """Neuer Chat in Claude Desktop, der über den MCP-Server als Lerncoach arbeitet."""
    # Nur echte Kursnamen in den Auftrag übernehmen
    kurs = body.kurs if body.kurs in {f["course"] for f in list_files()["files"]} else None
    try:
        integrations.open_claude(kurs)
    except integrations.ShareError as error:
        raise HTTPException(400, str(error)) from None
    core.log(f"Claude Desktop als Lerncoach geöffnet{f' ({kurs})' if kurs else ''}")
    return {"ok": True, "mcp": integrations.claude_mcp_configured()}


@app.post("/api/claude/mcp", dependencies=[api])
def claude_mcp() -> dict:
    """Trägt den MCP-Server in Claude Desktop ein (Einstellungen › KI), statt die JSON-Datei von Hand zu bearbeiten."""
    try:
        changed = integrations.configure_claude_mcp(demo=DEMO)
    except integrations.ShareError as error:
        raise HTTPException(400, str(error)) from None
    if changed:
        core.log(f"Claude Desktop: MCP-Server „{integrations.MCP_NAME}“ eingetragen")
    return {"ok": True, "changed": changed}


# --- Einstellungen ------------------------------------------------------------


@app.get("/api/settings", dependencies=[api])
def settings() -> dict:
    config = core.load_config()
    return {
        "uni_id": config["uni_id"],
        "has_password": bool(config["uni_id"] and keyring.get_password(KEYCHAIN_SERVICE, config["uni_id"])),
        "target_dir": config["target_dir"],
        "interval": config["interval_minutes"],
        "schedule_active": schedule.is_active() if not DEMO else False,
        "telegram": config["telegram"],
        "goodnotes": config["goodnotes"],
        "goodnotes_available": goodnotes.find_app() is not None,
        "notion": bool(config["notion"]),
        "ai_provider": config.get("ai_provider", "claude"),
        "claude_model": config.get("claude_model", ai.DEFAULT_CLAUDE_MODEL),
        "has_api_key": bool(ai.api_key()),
        "has_profile": ai.has_profile(),
        "openai_model": config.get("openai_model", ai.DEFAULT_OPENAI_MODEL),
        "has_openai_key": bool(ai.openai_key()),
        "gemini_model": config.get("gemini_model", ai.DEFAULT_GEMINI_MODEL),
        "gemma_api_model": ai.gemma_api_model(),
        "has_google_key": bool(ai.google_key()),
        "tutor_brain": config.get("tutor_brain", tutor.DEFAULT_BRAIN),
        "voice_id": config.get("voice_id", voice.DEFAULT_VOICE),
        "has_elevenlabs_key": bool(voice.api_key()),
        "agent_id": config.get("agent_id", ""),
        "tutor_auto": config.get("tutor_auto", True),
        "remarkable": integrations.remarkable_status(),
        "claude_desktop": integrations.claude_desktop_status(demo=DEMO),
        "demo": DEMO,
        "data_dir": str(APP_DIR),
        "version": VERSION,
        "code_dir": str(ROOT),
        "folder_suggestions": folder_suggestions(),
    }


def folder_suggestions() -> list[dict]:
    """Zielordner-Vorschläge für den Einrichtungs-Assistenten, wie im Terminal-Assistenten."""
    suggestions = []
    if cli.ICLOUD.exists():
        suggestions.append({"label": "iCloud Drive › ILIAS", "path": str(cli.ICLOUD / "ILIAS"),
                            "hint": "auch auf iPad und iPhone, gut für GoodNotes"})
    suggestions.append({"label": "Dokumente › ILIAS", "path": str(Path.home() / "Documents/ILIAS"),
                        "hint": "nur auf diesem Mac"})
    return suggestions


class Account(BaseModel):
    uni_id: str
    password: str


@app.post("/api/account", dependencies=[api])
def account(body: Account) -> dict:
    """Speichert die Zugangsdaten und prüft sie bei ILIAS (wie „ilias-sync zugang“ der Terminal-Version)."""
    config = core.load_config()
    uni_id = body.uni_id.strip()
    if not uni_id or not body.password:
        raise HTTPException(400, "Uni-ID und Passwort angeben")
    previous = config["uni_id"]
    config["uni_id"] = uni_id  # für die PFERD-Konfiguration; gespeichert wird unten in die frische Fassung
    keyring.set_password(KEYCHAIN_SERVICE, uni_id, body.password)
    (APP_DIR / "cookies.txt").unlink(missing_ok=True)
    try:
        result = sync.run_pferd(config, list_only=True)
    except sync.CrawlFailed as failure:
        cli._forget_password(uni_id)
        raise HTTPException(400, "Anmeldung fehlgeschlagen. Uni-ID oder Passwort falsch?" if failure.login
                            else "Keine Verbindung zu ILIAS. Internet prüfen.") from None
    if previous and previous != uni_id:
        cli._forget_password(previous)

    def remember(fresh: dict) -> None:  # die Prüfung dauert: Einstellungen von währenddessen nicht überschreiben
        fresh["uni_id"] = uni_id
        fresh["courses"].update({key: c for key, c in result["new"].items() if key not in fresh["courses"]})

    core.update_config(remember)
    return {"ok": True, "courses": len(result["entries"])}


class SettingsUpdate(BaseModel):
    target_dir: str | None = None
    interval: int | None = None
    schedule_active: bool | None = None
    goodnotes: bool | None = None
    ai_provider: str | None = None
    claude_model: str | None = None
    api_key: str | None = None
    openai_model: str | None = None
    openai_key: str | None = None
    gemini_model: str | None = None
    gemma_api_model: str | None = None
    google_key: str | None = None
    tutor_brain: str | None = None
    voice_id: str | None = None
    elevenlabs_key: str | None = None
    agent_id: str | None = None
    tutor_auto: bool | None = None


@app.patch("/api/settings", dependencies=[api])
def update_settings(body: SettingsUpdate) -> dict:
    config, state = core.load_config(), core.load_state()
    if body.target_dir is not None:
        target = Path(body.target_dir.strip()).expanduser()
        if not body.target_dir.strip() or not target.is_absolute():
            raise HTTPException(400, "Bitte einen vollständigen Ordnerpfad angeben, z. B. ~/Documents/ILIAS")
        if str(target) != config["target_dir"] and sync_running():
            raise HTTPException(409, "Gerade läuft ein Abgleich, bitte danach den Zielordner ändern")
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise HTTPException(400, f"Ordner lässt sich nicht anlegen ({error.strerror})") from None
        if str(target) != config["target_dir"]:
            config["target_dir"] = str(target)
            state["published"] = {}  # in den neuen Ordner alles einmal kopieren
    if body.interval in (30, 60):
        config["interval_minutes"] = body.interval
    if body.goodnotes is not None:
        config["goodnotes"] = body.goodnotes and goodnotes.find_app() is not None
    if body.ai_provider in ("claude", "openai", "gemini", "gemma"):
        config["ai_provider"] = body.ai_provider
    if body.claude_model in ai.CLAUDE_MODELS:
        config["claude_model"] = body.claude_model
    if body.api_key is not None:
        ai.set_api_key(body.api_key)
    if body.openai_model in ai.OPENAI_MODELS:
        config["openai_model"] = body.openai_model
    if body.openai_key is not None:
        ai.set_openai_key(body.openai_key)
    if body.gemini_model in ai.GEMINI_MODELS:
        config["gemini_model"] = body.gemini_model
    if body.gemma_api_model in ai.GEMMA_API_MODELS:
        config["gemma_api_model"] = body.gemma_api_model
    if body.google_key is not None:
        ai.set_google_key(body.google_key)
    if body.tutor_brain in tutor.BRAINS:
        config["tutor_brain"] = body.tutor_brain
    if body.voice_id is not None:
        config["voice_id"] = body.voice_id.strip() or voice.DEFAULT_VOICE
    if body.elevenlabs_key is not None:
        voice.set_api_key(body.elevenlabs_key)
    if body.agent_id is not None:
        config["agent_id"] = body.agent_id.strip()
    if body.tutor_auto is not None:
        config["tutor_auto"] = body.tutor_auto
        _tutor_wake.set()
    core.save_config(config)
    core.save_state(state)
    if body.schedule_active is not None or (body.interval and schedule.is_active()):
        if DEMO:
            raise HTTPException(400, "Im Demo-Modus gibt es keinen Zeitplan")
        if body.schedule_active is False:
            schedule.stop()
        elif config["uni_id"] and config["target_dir"]:
            schedule.start(config["interval_minutes"])
        else:
            raise HTTPException(400, "Erst Uni-Zugang und Zielordner einrichten")
    return settings()


class TelegramConnect(BaseModel):
    token: str
    chat: str = ""  # leer: die App erkennt den Chat an der ersten Nachricht an den Bot


@app.post("/api/telegram/connect", dependencies=[api])
def telegram_connect(body: TelegramConnect) -> dict:
    """Prüft den Bot-Token. Ohne Chat-ID wartet sie bis zu 5 Minuten auf eine Nachricht an den Bot;
    mit Chat-ID prüft sie diese mit der Begrüßungsnachricht."""
    token, chat_id = body.token.strip(), body.chat.strip()
    if not re.fullmatch(r"\d+:[\w-]+", token):
        raise HTTPException(400, "Das sieht nicht wie ein Bot-Token aus (Form: 123456789:ABC…)")
    if chat_id and not re.fullmatch(r"-?\d+", chat_id):
        raise HTTPException(400, "Die Chat-ID besteht nur aus Ziffern")
    welcome = ("✅ <b>StudyHub ist mit Telegram verbunden.</b>\nHier kommen neue Dateien, Zusammenfassungen, "
               "Lernkarten und Bibliotheks-Meldungen an.\n\n/bib zeigt, wie voll die Bibliotheken gerade sind.")
    try:
        bot = telegram_bot._call(token, "getMe")
        if chat_id:
            telegram_bot._call(token, "sendMessage", chat_id=chat_id, text=welcome, parse_mode="HTML")
            who = ""
        else:
            subprocess.run(["open", f"https://t.me/{bot['username']}"], check=False)
            chat = telegram_bot._wait_for_private_chat(token)
            chat_id = str(chat["id"])
            who = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
    except telegram_bot.TelegramError as error:
        raise HTTPException(400, f"Telegram: {error}") from None
    keyring.set_password(KEYCHAIN_SERVICE, "Telegram-Token", token)
    keyring.set_password(KEYCHAIN_SERVICE, "Telegram-Chat", chat_id)
    config = core.load_config()
    config["telegram"] = True
    config["telegram_bot"] = bot["username"]
    core.save_config(config)
    if who:
        try:
            telegram_bot.send(welcome)
        except telegram_bot.TelegramError as error:
            core.log(f"Telegram: Begrüßung nicht gesendet ({error})")
    return {"ok": True, "bot": bot["username"], "who": who}


@app.post("/api/telegram/disconnect", dependencies=[api])
def telegram_disconnect() -> dict:
    telegram_bot.remove()
    config = core.load_config()
    config["telegram"] = False
    config["telegram_bot"] = ""
    core.save_config(config)
    return {"ok": True}


@app.post("/api/telegram/test", dependencies=[api])
def telegram_test() -> dict:
    try:
        telegram_bot.send("👋 Testnachricht von StudyHub.")
    except telegram_bot.TelegramError as error:
        raise HTTPException(400, f"Telegram: {error}") from None
    return {"ok": True}


# --- Study-Tutor --------------------------------------------------------------


def tutor_brain() -> tuple[str, str | None]:
    """Gehirn des Tutors und das passende Modell aus den KI-Einstellungen."""
    config = core.load_config()
    brain = config.get("tutor_brain", tutor.DEFAULT_BRAIN)
    return brain, provider_model(config, brain)


@app.get("/api/tutor/status", dependencies=[api])
def tutor_status(course: str | None = None) -> dict:
    brain, _ = tutor_brain()
    gemma = ai.providers()["gemma"]
    ready = {"gemma": gemma["ready"], "claude": ai.claude_ready(), "openai": bool(ai.openai_key()),
             "gemini": bool(ai.google_key())}
    return {**tutor.stats(course or None), "brain": brain, "brain_ready": ready[brain],
            "voice_ready": bool(voice.api_key()), "agent_ready": bool(voice.api_key() and
                                                                       core.load_config().get("agent_id")),
            "auto": {**tutor.progress, "enabled": core.load_config().get("tutor_auto", True),
                     "gemma_ready": gemma["local"]}}


class TutorPrepare(BaseModel):
    path: str


@app.post("/api/tutor/prepare", dependencies=[api])
def tutor_prepare(body: TutorPrepare) -> dict:
    """Eine Datei für den Tutor vorbereiten (die Oberfläche ruft das Datei für Datei auf)."""
    brain, model = tutor_brain()
    try:
        return tutor.prepare(mirror_path(body.path), body.path, brain, model)
    except (tutor.TutorError, ai.AIError) as error:
        raise HTTPException(400, str(error)) from None


@app.get("/api/tutor/next", dependencies=[api])
def tutor_next(course: str | None = None, exclude: int | None = None, solution: bool = False) -> dict:
    question = tutor.next_question(course or None, exclude, with_solution=solution)
    if question is None:
        raise HTTPException(404, "Noch keine Fragen: erst Material vorbereiten")
    return question


class TutorAnswer(BaseModel):
    question_id: int
    text: str


@app.post("/api/tutor/answer", dependencies=[api])
def tutor_answer(body: TutorAnswer) -> dict:
    brain, model = tutor_brain()
    try:
        return tutor.grade(body.question_id, body.text, brain, model)
    except (tutor.TutorError, ai.AIError) as error:
        raise HTTPException(400, str(error)) from None


@app.post("/api/tutor/ask", dependencies=[api])
def tutor_ask(body: TutorAnswer) -> dict:
    brain, model = tutor_brain()
    try:
        return tutor.follow_up(body.question_id, body.text, brain, model)
    except (tutor.TutorError, ai.AIError) as error:
        raise HTTPException(400, str(error)) from None


class TutorTurn(BaseModel):
    role: Literal["tutor", "user"]
    text: str = Field(max_length=4000)


class TutorChat(BaseModel):
    text: str = Field("", max_length=4000)
    history: list[TutorTurn] = Field(default_factory=list, max_length=60)
    course: str = ""
    question_id: int | None = None


@app.post("/api/tutor/chat", dependencies=[api])
def tutor_chat(body: TutorChat) -> dict:
    """Freies Lerngespräch (Push-to-Talk): ein Beitrag rein, Antwort des Tutors raus.
    Den Verlauf hält der Browser und schickt ihn jedes Mal mit."""
    brain, model = tutor_brain()
    try:
        return tutor.converse(body.text, [t.model_dump() for t in body.history], body.course or None,
                              body.question_id, brain, model)
    except (tutor.TutorError, ai.AIError) as error:
        raise HTTPException(400, str(error)) from None


@app.post("/api/tutor/transcribe", dependencies=[api])
async def tutor_transcribe(request: Request) -> dict:
    """Rohes Audio aus dem Browser (MediaRecorder) → Text über ElevenLabs."""
    audio = await request.body()
    if len(audio) > 25_000_000:
        raise HTTPException(413, "Aufnahme zu lang")
    try:
        return {"text": voice.transcribe(audio, request.headers.get("content-type", ""))}
    except voice.VoiceError as error:
        raise HTTPException(400, str(error)) from None


class TutorSpeak(BaseModel):
    text: str


@app.post("/api/tutor/speak", dependencies=[api])
def tutor_speak(body: TutorSpeak) -> Response:
    try:
        audio = voice.speak(body.text, core.load_config().get("voice_id"))
    except voice.VoiceError as error:
        raise HTTPException(400, str(error)) from None
    return Response(audio, media_type="audio/mpeg")


class TutorRecord(BaseModel):
    question_id: int
    answer: str = ""
    verdict: Literal["correct", "partial", "wrong"]
    feedback: str = ""


@app.post("/api/tutor/record", dependencies=[api])
def tutor_record(body: TutorRecord) -> dict:
    """Bewertung des ElevenLabs Agents speichern (Client-Tool record_result)."""
    try:
        return tutor.record(body.question_id, body.answer, body.verdict, body.feedback)
    except tutor.TutorError as error:
        raise HTTPException(404, str(error)) from None


class TutorAgentSession(BaseModel):
    course: str = ""


@app.post("/api/tutor/agent-session", dependencies=[api])
def tutor_agent_session(body: TutorAgentSession) -> dict:
    """Alles, was der Browser für ein Gespräch mit dem ElevenLabs Agent braucht. Der API-Key bleibt hier."""
    try:
        url = voice.signed_url(core.load_config().get("agent_id", ""))
    except voice.VoiceError as error:
        raise HTTPException(400, str(error)) from None
    return {"signed_url": url, "prompt": tutor.AGENT_PROMPT, "first_message": tutor.AGENT_FIRST_MESSAGE,
            "dynamic_variables": {"course": body.course or "allen deinen Kursen"}}


@app.post("/api/tutor/open-browser", dependencies=[api])
def tutor_open_browser(request: Request) -> dict:
    """Das native Fenster darf nicht aufs Mikrofon zugreifen: Tutor im Standardbrowser öffnen."""
    url = f"{str(request.base_url).rstrip('/')}/?t={TOKEN}#tutor"
    subprocess.run(["open", url], check=False)
    return {"ok": True}


# --- StudyHub (neue Oberfläche) -------------------------------------------------


@app.get("/api/studyhub", dependencies=[api])
def studyhub_data() -> dict:
    """Alle Daten für ui/studyhub im Format von DATEN und MODUL_DETAILS (siehe docs/studyhub-api.md)."""
    config, cached = core.load_config(), cached_by_path()
    files = [file_info(p, cached) for p in mirror_files()]
    courses = {f["course"] for f in files}
    stats = {course: tutor.stats(course) for course in courses}
    status = core.load_state()
    data = studyhub.overview(config, files, cached, stats, studyhub.load_state(), karten=cards.load(),
                             exams=studyhub.load_exams(), hidden=[file_info(p, cached) for p in mirror_files(True)])
    data["skills"] = studyhub.load_skills()
    data["sync"] = {
        "configured": bool(config["uni_id"] and config["target_dir"]), "demo": DEMO, "running": sync_running(),
        "letzter": cli.last_sync_line(), "fehler": status["crawl_failures"],
    }
    return data


class LernplanUpdate(BaseModel):
    pfad: str
    status: str | None = None
    notiz: str | None = None


@app.patch("/api/studyhub/lernplan", dependencies=[api])
def studyhub_lernplan(body: LernplanUpdate) -> dict:
    mirror_path(body.pfad)  # nur echte Dateien
    try:
        return studyhub.set_state(body.pfad, body.status, body.notiz)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


class SkillsUpdate(BaseModel):
    kurs: str
    skills: list[str] = Field(max_length=20)


@app.patch("/api/studyhub/skills", dependencies=[api])
def studyhub_skills(body: SkillsUpdate) -> dict:
    """Hinzugefügte Skills eines Kurses (eigene Tabs wie Glossar, Formelsammlung) dauerhaft merken."""
    try:
        return {"skills": studyhub.set_skills(_course(body.kurs), body.skills)}
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


class Ausblenden(BaseModel):
    pfad: str
    ausgeblendet: bool = True


@app.patch("/api/studyhub/ausblenden", dependencies=[api])
def studyhub_ausblenden(body: Ausblenden) -> dict:
    """Datei nur in der App aus- oder wieder einblenden. Auf dem Mac und in ILIAS bleibt sie."""
    mirror_path(body.pfad)  # nur echte Dateien im Spiegel
    studyhub.set_hidden(body.pfad, body.ausgeblendet)
    core.log(f"StudyHub: {body.pfad} {'ausgeblendet' if body.ausgeblendet else 'wieder eingeblendet'}")
    return {"ok": True, "ausgeblendet": body.ausgeblendet}


class KlausurUpdate(BaseModel):
    kurs: str
    datum: str | None = None  # YYYY-MM-DD, leer = löschen


@app.patch("/api/studyhub/klausur", dependencies=[api])
def studyhub_klausur(body: KlausurUpdate) -> dict:
    try:
        studyhub.set_exam(_course(body.kurs), body.datum)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    return {"ok": True}


class CardReview(BaseModel):
    id: str
    bewertung: Literal["nochmal", "schwer", "gewusst"]


@app.post("/api/cards/review", dependencies=[api])
def cards_review(body: CardReview) -> dict:
    """Bewertung einer Karteikarte speichern (SM-2); liefert die Tage bis zur nächsten Wiederholung."""
    try:
        result = cards.review(body.id, body.bewertung)
    except cards.CardError as error:
        raise HTTPException(400, str(error)) from None
    return {"ok": True, "inTagen": result["interval"], "faellig": result["due"]}


def _course(name: str) -> str:
    """Nur Kurse mit Dateien im Spiegel (wie in StudyHub)."""
    if name not in {f["course"] for f in list_files()["files"]}:
        raise HTTPException(404, "Kurs nicht gefunden")
    return name


@app.post("/api/cards/import", dependencies=[api])
def cards_import(kurs: Annotated[str, Form()], file: Annotated[UploadFile, File()]) -> dict:
    """Karten aus einer Textdatei (Anki: „Notizen als Text“, oder eigene Liste mit Tabulator)."""
    data = file.file.read(5_000_001)
    if len(data) > 5_000_000:
        raise HTTPException(400, "Datei größer als 5 MB")
    try:
        parsed = cards.parse_text(data.decode("utf-8", errors="replace"))
        return cards.add_cards(_course(kurs), parsed, f"Textdatei · {file.filename or 'Import'}")
    except cards.CardError as error:
        raise HTTPException(400, str(error)) from None


@app.get("/api/cards/export", dependencies=[api])
def cards_export(kurs: str) -> Response:
    """Alle Karten eines Kurses als Textdatei für Anki (Datei › Importieren)."""
    text = cards.to_text(cards.all_for_course(_course(kurs), cached_by_path()))
    name = quote(f"Karten {kurs}.txt")
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})


DOWNLOADS = Path.home() / "Downloads"


class CardsExport(BaseModel):
    kurs: str


@app.post("/api/cards/export", dependencies=[api])
def cards_export_file(body: CardsExport) -> dict:
    """Wie GET, aber als Datei im Download-Ordner (im App-Fenster gibt es keine Browser-Downloads)."""
    found = cards.all_for_course(_course(body.kurs), cached_by_path())
    if not found:
        raise HTTPException(400, "Dieser Kurs hat noch keine Karteikarten")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[/:\x00-\x1f]", "-", f"Karten {body.kurs}")[:150]
    path, n = DOWNLOADS / f"{base}.txt", 2
    while path.exists():
        path, n = DOWNLOADS / f"{base} ({n}).txt", n + 1
    path.write_text(cards.to_text(found), encoding="utf-8")
    subprocess.run(["open", "-R", str(path)], check=False)
    core.log(f"Karten: {len(found)} aus {body.kurs} nach {path.name} exportiert")
    return {"ok": True, "datei": path.name, "karten": len(found)}


@app.get("/api/anki/status", dependencies=[api])
def anki_status() -> dict:
    return integrations.anki_status()


class AnkiImport(BaseModel):
    kurs: str
    deck: str = Field(min_length=1, max_length=300)


@app.post("/api/anki/import", dependencies=[api])
def anki_import(body: AnkiImport) -> dict:
    """Karten eines Anki-Decks über AnkiConnect übernehmen (Lernstand beginnt in StudyHub neu)."""
    kurs = _course(body.kurs)
    try:
        found = integrations.anki_cards(body.deck)
    except integrations.AnkiError as error:
        raise HTTPException(400, str(error)) from None
    if not found:
        raise HTTPException(400, f"Im Deck „{body.deck}“ sind keine Karten mit Vorder- und Rückseite")
    return cards.add_cards(kurs, [(cards.plain(f), cards.plain(b)) for f, b in found], f"Anki · {body.deck}")


class AnkiExport(BaseModel):
    kurs: str


@app.post("/api/anki/export", dependencies=[api])
def anki_export(body: AnkiExport) -> dict:
    """Alle Karten eines Kurses über AnkiConnect nach Anki (Deck „StudyHub::<Kurs>“)."""
    found = cards.all_for_course(_course(body.kurs), cached_by_path())
    if not found:
        raise HTTPException(400, "Dieser Kurs hat noch keine Karteikarten")
    try:
        return integrations.anki_export(body.kurs, found)
    except integrations.AnkiError as error:
        raise HTTPException(400, str(error)) from None


@app.get("/api/libraries", dependencies=[api])
def libraries_overview() -> dict:
    """Auslastung der Bibliotheksbereiche: aktueller Stand und Verlauf je Wochentag/Stunde."""
    return {**libraries.overview(), "demo": DEMO}


@app.post("/api/libraries/refresh", dependencies=[api])
def libraries_refresh() -> dict:
    """Jetzt messen (höchstens einmal pro Minute, die UB aktualisiert seltener)."""
    data = libraries.overview()
    if data["stand"] and data["alterMinuten"] is not None and data["alterMinuten"] < 1:
        return {"neu": False, **data, "demo": DEMO}
    try:
        result = libraries.sample()
    except libraries.LibraryError as error:
        raise HTTPException(502, str(error)) from None
    return {"neu": result["neu"], **libraries.overview(), "demo": DEMO}


class LibraryBackground(BaseModel):
    aktiv: bool


@app.patch("/api/libraries/background", dependencies=[api])
def libraries_background(body: LibraryBackground) -> dict:
    """Messen auch bei geschlossener App (launchd-Job alle fünf Minuten)."""
    if DEMO:
        raise HTTPException(400, "Im Demo-Modus nicht verfügbar")
    libraries.background_start() if body.aktiv else libraries.background_stop()
    return {"aktiv": libraries.background_active()}


class LibraryAlerts(BaseModel):
    aktiv: bool | None = None
    schwelle: int | None = Field(None, ge=50, le=100)
    bereiche: list[str] | None = None


@app.patch("/api/libraries/alerts", dependencies=[api])
def libraries_alerts(body: LibraryAlerts) -> dict:
    """Telegram-Meldung, wenn ein Bereich voll wird und wenn dort wieder Platz ist."""
    if body.aktiv and not core.load_config()["telegram"]:
        raise HTTPException(400, "Erst Telegram verbinden")
    libraries.save_alert_settings(body.aktiv, body.schwelle, body.bereiche)
    return libraries.telegram_status()


@app.post("/api/libraries/telegram", dependencies=[api])
def libraries_telegram() -> dict:
    """Den aktuellen Stand an Telegram schicken (wie die Antwort auf /bib)."""
    if not core.load_config()["telegram"]:
        raise HTTPException(400, "Erst Telegram verbinden")
    try:
        telegram_bot.send(libraries.status_text())
    except telegram_bot.TelegramError as error:
        raise HTTPException(400, f"Telegram: {error}") from None
    return {"ok": True}


class StudyHubBrowser(BaseModel):
    hash: str = ""


@app.post("/api/studyhub/open-browser", dependencies=[api])
def studyhub_open_browser(request: Request, body: StudyHubBrowser) -> dict:
    """Im App-Fenster gibt es kein Mikrofon: StudyHub an derselben Stelle im Standardbrowser öffnen."""
    # Nur StudyHub-Adressen wie „#/modul/statistik-i/sprachtutor“ übernehmen, sonst die Startseite
    erlaubt = body.hash.startswith("#/") and all(c.isalnum() or c in "-_/" for c in body.hash[2:])
    ziel = body.hash if erlaubt else ""
    url = f"{str(request.base_url).rstrip('/')}/ui/studyhub/index.html?t={TOKEN}{ziel}"
    subprocess.run(["open", url], check=False)
    return {"ok": True}


# --- Eigene Dateien hochladen -------------------------------------------------


@app.post("/api/upload", dependencies=[api])
def upload(course: Annotated[str, Form()], files: Annotated[list[UploadFile], File()],
           art: Annotated[Literal["material", "zusammenfassung"], Form()] = "material") -> dict:
    """Dateien in einen Kurs hochladen: Material nach <Kurs>/Eigene Dateien/, eigene Zusammenfassungen
    nach <Kurs>/Eigene Zusammenfassungen/ (siehe server/uploads.py)."""
    # blockweise speichern, save() bricht über 100 MB ab
    return _save_uploads(course, art, [(f.filename or "", iter(lambda f=f: f.file.read(1 << 20), b"")) for f in files])


class UploadPaths(BaseModel):
    course: str
    paths: list[str]
    art: Literal["material", "zusammenfassung"] = "material"


@app.post("/api/upload/paths", dependencies=[api])
def upload_paths(body: UploadPaths) -> dict:
    """Wie /api/upload, aber mit Dateien, die im nativen Dialog der App gewählt wurden (pywebview):
    WebKit im App-Fenster liefert über <input type="file"> nicht immer Dateien."""
    items, missing = [], []
    for raw in body.paths:
        path = Path(raw).expanduser()
        if path.is_file():
            items.append((path.name, path))
        else:
            missing.append(f"{path.name}: nicht gefunden")

    def chunks(path: Path):
        with open(path, "rb") as file:
            yield from iter(lambda: file.read(1 << 20), b"")

    return _save_uploads(body.course, body.art, [(name, chunks(path)) for name, path in items], missing)


def _save_uploads(course: str, art: str, items: list, errors: list[str] | None = None) -> dict:
    config = core.load_config()
    folder = uploads.SUMMARY_FOLDER if art == "zusammenfassung" else uploads.FOLDER
    saved, errors = [], list(errors or [])
    for name, chunks in items:
        try:
            saved.append(uploads.save(config, course, name, chunks, folder))
        except uploads.UploadError as error:
            errors.append(str(error))
    if not saved:
        raise HTTPException(400, "; ".join(errors) or "Keine Datei erhalten")
    _after_upload(config)
    return {"saved": saved, "errors": errors}


def _after_upload(config: dict) -> None:
    # Gleich in den Zielordner kopieren, wenn kein Abgleich läuft (sonst übernimmt das der nächste)
    if not sync_running():
        state = core.load_state()
        sync.publish(config, state)
        core.save_state(state)
    _tutor_wake.set()


class SummaryText(BaseModel):
    kurs: str
    titel: str
    text: str


@app.post("/api/summaries", dependencies=[api])
def summary_write(body: SummaryText) -> dict:
    """In StudyHub geschriebene Zusammenfassung speichern (Markdown unter „Eigene Zusammenfassungen“)."""
    config = core.load_config()
    try:
        path = uploads.save_summary_text(config, body.kurs, body.titel, body.text)
    except uploads.UploadError as error:
        raise HTTPException(400, str(error)) from None
    _after_upload(config)
    return {"ok": True, "pfad": path}

