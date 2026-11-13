"""Chat zum Dokument oder Kurs. Nie ein echter Claude-Aufruf: claude_cli.run wird ersetzt."""

import pytest
from fastapi.testclient import TestClient

import chat
import claude_cli
import core
import markdown_docs
from app import app

AUTH = {"x-app-token": "test-token"}
DOC = "Statistik/Vorlesung/07 Tests.txt"


def _doc(relative: str = DOC, text: str = "Die Nullhypothese H0 wird getestet. " * 20):
    path = core.MIRROR_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, relative


@pytest.fixture
def fake_cli(monkeypatch):
    calls = []

    def run(prompt, system, model, schema=None, read_dirs=None, max_turns=1):
        calls.append({"prompt": prompt, "system": system, "schema": schema, "read_dirs": read_dirs,
                      "max_turns": max_turns})
        output = {"antwort": f"Antwort {len(calls)} <b>", "quellen": ["07 Tests, S. 1"]}
        return {"output": output, "model": model, "tokens_in": 10, "tokens_out": 5, "cache_read": 0,
                "cache_write": 0, "cost_usd_estimate": 0.01}

    monkeypatch.setattr(claude_cli, "run", run)
    return calls


def test_document_chat_sends_markdown_and_keeps_history(fake_cli):
    _doc()
    _doc("Statistik/Übung/Blatt 1.txt", "Aufgabe: Teste H0 gegen H1. " * 20)
    client = TestClient(app)
    first = client.post("/api/chat", headers=AUTH, json={"kurs": "Statistik", "pfad": DOC, "text": " Was ist H0? "})
    assert first.status_code == 200
    assert first.json() == {"antwort": "Antwort 1 <b>", "quellen": ["07 Tests, S. 1"],
                            "kontext": "Statistik · 07 Tests.txt", "modus": "dokument", "hinweis": ""}
    call = fake_cli[0]
    assert call["prompt"].startswith(f'<dokument pfad="{DOC}">') and "## Seite 1" in call["prompt"]
    assert "Blatt 1" not in call["prompt"] and call["prompt"].endswith("Frage: Was ist H0?")
    assert call["schema"] == chat.SCHEMA and call["read_dirs"] is None and "nicht im Material" in call["system"]

    client.post("/api/chat", headers=AUTH, json={"kurs": "Statistik", "pfad": DOC, "text": "Und H1?"})
    assert "<verlauf>\nFrage: Was ist H0?\n\nAntwort: Antwort 1 <b>\n</verlauf>" in fake_cli[1]["prompt"]

    data = client.get("/api/chat", headers=AUTH, params={"kurs": "Statistik", "pfad": DOC}).json()
    assert [p["rolle"] for p in data["verlauf"]] == ["nutzer", "claude", "nutzer", "claude"]
    assert data["verlauf"][1]["quellen"] == ["07 Tests, S. 1"] and data["kontext"] == "Statistik · 07 Tests.txt"
    assert "installiert" in data["anmelden"]  # in Tests gibt es kein Claude Code
    # Kurs und Dokument haben getrennte Verläufe
    assert client.get("/api/chat", headers=AUTH, params={"kurs": "Statistik"}).json()["verlauf"] == []

    assert client.delete("/api/chat", headers=AUTH, params={"kurs": "Statistik", "pfad": DOC}).json() == {"ok": True}
    assert chat.history("Statistik", DOC) == []


def test_course_chat_puts_all_course_documents_into_the_prompt(fake_cli):
    _doc()
    _doc("Statistik/Übung/Blatt 1.txt", "Aufgabe: Teste H0 gegen H1. " * 20)
    _doc("Mathe/Skript.txt", "Ableitungen " * 50)
    answer = TestClient(app).post("/api/chat", headers=AUTH, json={"kurs": "Statistik", "text": "Was kommt dran?"})
    assert answer.json()["modus"] == "kurs" and answer.json()["kontext"] == "Statistik"
    prompt = fake_cli[0]["prompt"]
    assert prompt.startswith('<kurs name="Statistik">') and 'pfad="Statistik/Übung/Blatt 1.txt"' in prompt
    assert "Ableitungen" not in prompt and fake_cli[0]["read_dirs"] is None
    assert len(chat.history("Statistik")) == 2


def test_large_course_lets_claude_read_the_markdown_folder(fake_cli, monkeypatch):
    _doc()
    _doc("Statistik/Übung/Blatt 1.txt", "Aufgabe: Teste H0 gegen H1. " * 20)
    monkeypatch.setattr(chat, "MAX_CHARS", 500)
    answer = TestClient(app).post("/api/chat", headers=AUTH, json={"kurs": "Statistik", "text": "Was ist H0?"})
    assert answer.json()["modus"] == "kurs-lesen"
    call = fake_cli[0]
    assert call["read_dirs"] == [markdown_docs.MD_DIR / "Statistik"] and call["max_turns"] == chat.READ_TURNS
    assert str(markdown_docs.md_path(DOC)) in call["prompt"] and "Nullhypothese" not in call["prompt"]


def test_large_course_is_trimmed_for_other_providers(monkeypatch):
    _doc()
    _doc("Statistik/Übung/Blatt 1.txt", "Aufgabe: Teste H0 gegen H1. " * 200)
    monkeypatch.setattr(chat, "MAX_CHARS", 3000)
    seen = {}

    def complete(provider, system, prompt, schema=None, model=None):
        seen["prompt"] = prompt
        return {"antwort": "Kurz", "quellen": []}

    monkeypatch.setattr(chat.ai, "complete", complete)
    files = [(p, core.nfc(p.relative_to(core.MIRROR_DIR).as_posix())) for p in core.MIRROR_DIR.rglob("*.txt")]
    result = chat.ask("Statistik", "Was ist H0?", files, "openai")
    assert result["modus"] == "kurs-gekuerzt" and "Claude-Abo" in result["hinweis"]
    assert "[… gekürzt]" in seen["prompt"] and result["quellen"] == []


def test_failed_answer_is_not_stored_and_errors_are_explained(monkeypatch):
    _doc()

    def run(*args, **kwargs):
        raise claude_cli.CLIError("Claude ist nicht angemeldet (Einstellungen › KI › Bei Claude anmelden)")

    monkeypatch.setattr(claude_cli, "run", run)
    client = TestClient(app)
    answer = client.post("/api/chat", headers=AUTH, json={"kurs": "Statistik", "pfad": DOC, "text": "Was ist H0?"})
    assert answer.status_code == 400 and "nicht angemeldet" in answer.json()["detail"]
    assert chat.history("Statistik", DOC) == []


def test_chat_checks_token_course_and_path(fake_cli):
    _doc()
    _doc("Mathe/Skript.txt", "Ableitungen " * 50)
    client = TestClient(app)
    post = lambda body, **kw: client.post("/api/chat", json=body, **kw).status_code  # noqa: E731
    assert post({"kurs": "Statistik", "text": "Hallo"}) == 403
    assert client.get("/api/chat", params={"kurs": "Statistik"}).status_code == 403
    assert client.delete("/api/chat", params={"kurs": "Statistik"}).status_code == 403
    assert post({"kurs": "Erfunden", "text": "Hallo"}, headers=AUTH) == 404
    assert post({"kurs": "Statistik", "pfad": "../../etc/passwd", "text": "Hallo"}, headers=AUTH) == 404
    assert post({"kurs": "Statistik", "pfad": "Mathe/Skript.txt", "text": "Hallo"}, headers=AUTH) == 404  # anderer Kurs
    assert post({"kurs": "Statistik", "text": ""}, headers=AUTH) == 422
    assert not fake_cli


def test_scanned_document_is_explained(fake_cli, monkeypatch):
    path, relative = _doc("Statistik/Scan.pdf", "")
    monkeypatch.setattr(chat.ai, "extract_pages", lambda p: ["", ""])
    with pytest.raises(chat.ai.AIError, match="gescannt"):
        chat.ask("Statistik", "Was steht da?", [], chat.ai.CLAUDE_ABO, path=path, relative=relative)
    assert not fake_cli


def test_history_moves_with_renamed_course_and_is_limited(fake_cli, monkeypatch):
    path, relative = _doc()
    monkeypatch.setattr(chat, "KEEP", 4)
    for number in range(3):
        chat.ask("Statistik", f"Frage {number}", [], chat.ai.CLAUDE_ABO, path=path, relative=relative)
    assert [p["text"] for p in chat.history("Statistik", DOC)][0] == "Frage 1"  # älteste Beiträge fallen weg
    chat.ask("Statistik", "Überblick?", [(path, relative)], chat.ai.CLAUDE_ABO)
    chat.rename_folder("Statistik", "Statistik I")
    assert len(chat.history("Statistik I")) == 2
    assert len(chat.history("Statistik I", "Statistik I/Vorlesung/07 Tests.txt")) == 4
    assert chat.history("Statistik") == []
