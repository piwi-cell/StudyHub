"""Claude über das Abo (Claude Code headless), Markdown-Fassungen und Kurs-Skills. Nie ein echter Claude-Aufruf:
claude_cli.run bzw. subprocess.run werden ersetzt."""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

import ai
import claude_cli
import core
import course_skills
import markdown_docs
import studyhub
from app import app

AUTH = {"x-app-token": "test-token"}


def _doc(relative: str = "Statistik/Vorlesung/07 Tests.txt", text: str = "Die Nullhypothese H0 wird getestet. " * 20):
    path = core.MIRROR_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, relative


@pytest.fixture
def fake_cli(monkeypatch):
    calls = []

    def run(prompt, system, model, schema=None, read_dirs=None, max_turns=1):
        calls.append({"prompt": prompt, "system": system, "model": model, "schema": schema, "read_dirs": read_dirs})
        if schema and "cards" in schema.get("properties", {}):
            output = {"cards": [{"front": "Was ist H0?", "back": "Die Nullhypothese"}]}
        elif schema:
            output = {"begriffe": [{"begriff": "<H0>", "erklaerung": "Nullhypothese", "quelle": "07 Tests, S. 1"}]}
        else:
            output = "## Worum es geht\nTests."
        return {"output": output, "model": model, "tokens_in": 10, "tokens_out": 5, "cache_read": 0,
                "cache_write": 0, "cost_usd_estimate": 0.01}

    monkeypatch.setattr(claude_cli, "run", run)
    return calls


def test_command_line_follows_headless_docs(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"], seen["kwargs"] = command, kwargs
        out = {"type": "result", "is_error": False, "structured_output": {"a": "x"},
               "usage": {"input_tokens": 3, "output_tokens": 2}, "total_cost_usd": 0.0}
        return subprocess.CompletedProcess(command, 0, json.dumps(out), "")

    monkeypatch.setattr(claude_cli, "binary", lambda: "/bin/claude")
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = claude_cli.run("Text", "System", "claude-sonnet-5-5", {"type": "object"})
    command = seen["command"]
    assert command[:4] == ["/bin/claude", "-p", "--output-format", "json"]
    assert "--bare" not in command  # bare liest die Abo-Anmeldung nicht
    for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands", "--json-schema"):
        assert flag in command
    assert command[command.index("--tools") + 1] == ""  # ohne Werkzeuge
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert seen["kwargs"]["input"] == "Text" and seen["kwargs"]["cwd"] == claude_cli.WORK_DIR
    assert result["output"] == {"a": "x"} and result["tokens_in"] == 3


def test_not_logged_in_is_explained(monkeypatch):
    out = {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}
    monkeypatch.setattr(claude_cli, "binary", lambda: "/bin/claude")
    monkeypatch.setattr(subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 0, json.dumps(out), ""))
    with pytest.raises(claude_cli.CLIError, match="nicht angemeldet"):
        claude_cli.run("x", "y", "claude-opus-5-5")


def test_missing_claude_code_is_explained():
    with pytest.raises(claude_cli.CLIError, match="nicht installiert"):
        claude_cli.run("x", "y", "claude-opus-5-5")
    assert claude_cli.status(refresh=True) == {"installed": False, "logged_in": False, "method": "none", "email": ""}


def test_abo_works_with_markdown_instead_of_pdf(fake_cli):
    path, relative = _doc()
    result = ai.run(path, relative, "flashcards", ai.CLAUDE_ABO, "claude-sonnet-5-5")
    assert result["output"]["cards"][0]["front"] == "Was ist H0?"
    assert result["provider"] == ai.CLAUDE_ABO and result["input_mode"] == "Markdown" and result["cost_usd"] == 0.0
    prompt = fake_cli[0]["prompt"]
    assert "## Seite 1" in prompt and prompt.startswith('<dokument titel="07 Tests.txt">')
    assert fake_cli[0]["schema"] == ai.FLASHCARD_SCHEMA

    md = markdown_docs.md_path(relative)
    assert md.exists() and markdown_docs.read_header(md)["quelle"] == relative
    assert markdown_docs.status(path, relative) == "aktuell"
    path.write_text("Neuer Inhalt " * 50, encoding="utf-8")
    assert markdown_docs.status(path, relative) == "veraltet"


def test_scanned_pdf_is_transcribed_once_by_claude(fake_cli, monkeypatch):
    path, relative = _doc("Statistik/Scan.pdf", "")
    monkeypatch.setattr(ai, "extract_pages", lambda p: ["", ""])
    text, art = markdown_docs.ensure(path, relative)  # Hintergrund: ohne KI
    assert art == "gescannt" and not fake_cli
    text, art = markdown_docs.ensure(path, relative, use_claude=True, model="claude-opus-5-5")
    assert art == "claude" and fake_cli[0]["read_dirs"] == [path.parent]
    markdown_docs.ensure(path, relative, use_claude=True)
    assert len(fake_cli) == 1  # danach aus der Markdown-Fassung


def test_background_creates_markdown_for_all_text_files():
    files = [_doc(), _doc("Mathe/Eigene Dateien/Notiz.md", "# Notiz\nAbleitung")]
    assert markdown_docs.ensure_all(files) == 2 and markdown_docs.ensure_all(files) == 0
    notiz = markdown_docs.MD_DIR / "Mathe/Eigene Dateien/Notiz.md.md"
    assert notiz.read_text(encoding="utf-8").count("## Seite") == 1
    markdown_docs.rename_folder("Mathe", "Mathe I")
    assert markdown_docs.read_header(markdown_docs.md_path("Mathe I/Eigene Dateien/Notiz.md"))["quelle"] == \
        "Mathe I/Eigene Dateien/Notiz.md"


def test_course_skill_endpoint_uses_all_course_documents_and_escapes(fake_cli):
    _doc()
    _doc("Statistik/Übung/Blatt 1.txt", "Aufgabe: Teste H0 gegen H1. " * 20)
    _doc("Mathe/Skript.txt", "Ableitungen " * 50)
    config = core.load_config()
    config["abo_standard"] = False  # Umstellung auf das Abo als Standard prüfen
    core.save_config(config)
    client = TestClient(app)
    assert client.post("/api/studyhub/skill-erstellen", headers=AUTH,
                       json={"kurs": "Statistik", "skill": "glossar"}).json() == {"ok": True}
    assert core.load_config()["ai_provider"] == ai.CLAUDE_ABO
    prompt = fake_cli[0]["prompt"]
    assert 'pfad="Statistik/Übung/Blatt 1.txt"' in prompt and "Ableitungen" not in prompt
    assert set(course_skills.results("Statistik")["glossar"]["quellen"]) == {
        "Statistik/Vorlesung/07 Tests.txt", "Statistik/Übung/Blatt 1.txt"}
    data = client.get("/api/studyhub", headers=AUTH).json()["kursSkills"]
    assert data["Statistik"]["glossar"]["output"]["begriffe"][0]["begriff"] == "&lt;H0&gt;"

    assert client.post("/api/studyhub/skill-erstellen", headers=AUTH,
                       json={"kurs": "Statistik", "skill": "quatsch"}).status_code == 400
    assert client.post("/api/studyhub/skill-erstellen", headers=AUTH,
                       json={"kurs": "Erfunden", "skill": "glossar"}).status_code == 404
    ohne_token = client.post("/api/studyhub/skill-erstellen", json={"kurs": "Statistik", "skill": "glossar"})
    assert ohne_token.status_code == 403


def test_every_skill_has_a_strict_schema():
    for instruction, schema in course_skills.SKILLS.values():
        assert instruction and schema["additionalProperties"] is False
    assert set(course_skills.SKILLS) == set(studyhub.SKILLS)


def test_providers_list_the_abo_first():
    providers = TestClient(app).get("/api/ai/providers", headers=AUTH).json()
    assert list(providers)[0] == ai.CLAUDE_ABO and providers[ai.CLAUDE_ABO]["installed"] is False
    assert providers["default_provider"] == ai.CLAUDE_ABO
