"""Claude über das Claude-Abo: Claude Code im headless-Modus (`claude -p`), ohne API-Key.

Aufruf laut code.claude.com/docs/en/headless und /cli-reference:
- `--output-format json` liefert `result` (Text), `structured_output` (mit `--json-schema`), `is_error`,
  `total_cost_usd`, `usage`, `session_id`.
- Kein `--bare`: bare liest die Abo-Anmeldung (OAuth/Schlüsselbund) nicht.
- Stattdessen abgeschottet: eigener Arbeitsordner, keine MCP-Server (`--strict-mcp-config`), keine Skills
  (`--disable-slash-commands`), eigene System-Anweisung, nur ausdrücklich erlaubte Werkzeuge (`--tools`),
  alles andere wird ohne Rückfrage abgelehnt (`--permission-mode dontAsk`), keine gespeicherte Sitzung.
- Anmeldung: `claude auth status` (JSON, Exit 0 = angemeldet), `claude auth login` öffnet den Browser.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import core

WORK_DIR = core.APP_DIR / "KI" / "claude-arbeitsordner"  # leer: keine CLAUDE.md, keine Projekt-Hooks
TIMEOUT = 900  # Sekunden; Kurs-Skills über viele Dokumente dauern
MAX_STDIN = 9_500_000  # Claude Code nimmt höchstens 10 MB über stdin
STATUS_TTL = 60  # Sekunden, so lange gilt ein geprüfter Anmeldestatus
# Aus dem Finder gestartet kennt die App nur einen kurzen PATH: übliche Installationsorte selbst prüfen
CANDIDATES = (Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude",
              Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude"))

_status: dict = {"checked": 0.0, "value": None}


class CLIError(Exception):
    pass


def binary() -> str | None:
    if found := shutil.which("claude"):
        return found
    return next((str(p) for p in CANDIDATES if p.is_file() and os.access(p, os.X_OK)), None)


def status(refresh: bool = False) -> dict:
    """{installed, logged_in, method, email}. Wird kurz zwischengespeichert, der Aufruf dauert etwas."""
    if not refresh and _status["value"] and time.time() - _status["checked"] < STATUS_TTL:
        return _status["value"]
    claude = binary()
    value = {"installed": bool(claude), "logged_in": False, "method": "none", "email": ""}
    if claude:
        try:
            done = subprocess.run([claude, "auth", "status"], capture_output=True, text=True, timeout=20)
            data = json.loads(done.stdout or "{}")
            value.update(logged_in=done.returncode == 0 and bool(data.get("loggedIn")),
                         method=str(data.get("authMethod") or "none"), email=str(data.get("email") or ""))
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            core.log(f"Claude: Anmeldestatus nicht lesbar ({error})")
    _status.update(checked=time.time(), value=value)
    return value


def open_login() -> None:
    """Öffnet das Terminal mit `claude auth login`; die Anmeldung selbst passiert im Browser."""
    claude = binary()
    if not claude:
        raise CLIError("Claude Code ist nicht installiert (StudyHub-Installer erneut ausführen)")
    command = f"'{claude}' auth login"
    script = f'tell application "Terminal" to do script "{command}"\ntell application "Terminal" to activate'
    subprocess.run(["osascript", "-e", script], check=False)
    _status["checked"] = 0.0  # beim nächsten Blick neu prüfen


def run(prompt: str, system: str, model: str, schema: dict | None = None, read_dirs: list[Path] | None = None,
        max_turns: int = 1) -> dict:
    """Eine Anfrage an Claude. read_dirs: Ordner, aus denen Claude Dateien lesen darf (Werkzeug Read).
    Liefert {output, model, tokens_in, tokens_out, cache_read, cache_write, cost_usd_estimate}."""
    claude = binary()
    if not claude:
        raise CLIError("Claude Code ist nicht installiert (StudyHub-Installer erneut ausführen)")
    if len(prompt.encode("utf-8")) > MAX_STDIN:
        raise CLIError("Dokument zu groß für eine Anfrage, bitte aufteilen")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    command = [claude, "-p", "--output-format", "json", "--model", model, "--system-prompt", system,
               "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
               "--permission-mode", "dontAsk", "--max-turns", str(max_turns)]
    if read_dirs:
        command += ["--tools", "Read", "--allowedTools", "Read"]
        for folder in read_dirs:
            command += ["--add-dir", str(folder)]
    else:
        command += ["--tools", ""]
    if schema:
        command += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    try:
        done = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=TIMEOUT,
                              cwd=WORK_DIR, encoding="utf-8")
    except subprocess.TimeoutExpired:
        raise CLIError("Claude hat zu lange gebraucht, bitte noch einmal versuchen") from None
    except OSError as error:
        raise CLIError(f"Claude Code lässt sich nicht starten ({error.strerror})") from None
    try:
        data = json.loads(done.stdout)
    except ValueError:
        detail = (done.stderr or done.stdout or "").strip().splitlines()[-1:] or ["keine Ausgabe"]
        raise CLIError(f"Claude Code: {detail[0][:200]}") from None
    if data.get("is_error") or done.returncode != 0:
        message = str(data.get("result") or data.get("subtype") or "unbekannter Fehler")
        if "login" in message.lower() or "auth" in message.lower():
            _status["checked"] = 0.0
            raise CLIError("Claude ist nicht angemeldet (Einstellungen › KI › Bei Claude anmelden)")
        raise CLIError(f"Claude: {message[:300]}")
    if schema:
        if "structured_output" not in data:
            raise CLIError("Claude hat kein Ergebnis im verlangten Format geliefert")
        output = data["structured_output"]
    else:
        output = str(data.get("result") or "")
    usage = data.get("usage") or {}
    return {"output": output, "model": model,
            "tokens_in": usage.get("input_tokens", 0), "tokens_out": usage.get("output_tokens", 0),
            "cache_read": usage.get("cache_read_input_tokens", 0),
            "cache_write": usage.get("cache_creation_input_tokens", 0),
            "cost_usd_estimate": data.get("total_cost_usd")}
