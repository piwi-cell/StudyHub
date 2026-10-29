"""ChatGPT-Anbieter mit nachgebauter OpenAI-Antwort: Anfrageform, Auswertung, Fehlerfälle."""

import json

import keyring
import pytest

import ai
import core


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _reply(text: str, status: str = "completed", cached: int = 0) -> dict:
    return {
        "status": status,
        "model": "gpt-6.1-sol",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {"input_tokens": 1500, "input_tokens_details": {"cached_tokens": cached}, "output_tokens": 300},
    }


@pytest.fixture
def openai(monkeypatch):
    """Fängt Aufrufe an die OpenAI-API ab; `calls` enthält die gesendeten Anfragen."""
    keyring.set_password(core.KEYCHAIN_SERVICE, ai.OPENAI_KEY_ACCOUNT, "sk-test")
    calls, replies = [], []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "body": json, "headers": headers})
        return replies.pop(0)

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    return calls, replies


def _doc(text: str = "Elastizität der Nachfrage. " * 50):
    path = core.MIRROR_DIR / "Mikro/kapitel5.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, "Mikro/kapitel5.txt"


def test_summary_request_and_usage(openai):
    calls, replies = openai
    replies.append(FakeResponse(200, _reply("## Kernaussagen", cached=1200)))
    path, relative = _doc()
    result = ai.run(path, relative, "summary", "openai", model="gpt-6.1-sol")

    body = calls[0]["body"]
    assert calls[0]["url"] == ai.OPENAI_URL
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert body["store"] is False and body["instructions"] == ai.SYSTEM
    document, task = body["input"][0]["content"]
    assert document["type"] == "input_text" and "Elastizität" in document["text"]
    assert "Lernzusammenfassung" in task["text"]  # Aufgabe steht hinter dem Dokument (Cache-Prefix)
    assert "text" not in body
    assert result["output"] == "## Kernaussagen"
    assert (result["tokens_in"], result["cache_read"], result["tokens_out"]) == (300, 1200, 300)


def test_flashcards_use_json_schema(openai):
    calls, replies = openai
    cards = {"cards": [{"front": "Was ist Elastizität?", "back": "Relative Mengenänderung …"}]}
    replies.append(FakeResponse(200, _reply(json.dumps(cards))))
    path, relative = _doc()
    result = ai.run(path, relative, "flashcards", "openai")
    fmt = calls[0]["body"]["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] == ai.FLASHCARD_SCHEMA
    assert calls[0]["body"]["model"] == ai.DEFAULT_OPENAI_MODEL
    assert result["output"] == cards


def test_scanned_pdf_is_sent_as_file(openai, monkeypatch):
    calls, replies = openai
    replies.append(FakeResponse(200, _reply("Antwort")))
    path = core.MIRROR_DIR / "Mikro/scan.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 scan")
    monkeypatch.setattr(ai, "extract_pages", lambda _: ["", ""])
    ai.run(path, "Mikro/scan.pdf", "qa", "openai", question="Worum geht es?")
    document = calls[0]["body"]["input"][0]["content"][0]
    assert document["type"] == "input_file" and document["filename"] == "scan.pdf"
    assert document["file_data"].startswith("data:application/pdf;base64,")


@pytest.mark.parametrize(("status", "message"), [(401, "ungültig"), (429, "Limit"), (500, "OpenAI-Fehler 500")])
def test_http_errors_are_readable(openai, status, message):
    _, replies = openai
    replies.append(FakeResponse(status, {"error": {"message": "kaputt"}}))
    path, relative = _doc()
    with pytest.raises(ai.AIError, match=message):
        ai.run(path, relative, "summary", "openai")


def test_refusal_and_truncated_flashcards(openai):
    _, replies = openai
    path, relative = _doc()
    replies.append(FakeResponse(200, {"status": "completed", "output": [
        {"type": "message", "content": [{"type": "refusal", "refusal": "Nein"}]}]}))
    with pytest.raises(ai.AIError, match="abgelehnt"):
        ai.run(path, relative, "summary", "openai")
    replies.append(FakeResponse(200, _reply('{"cards": [', status="incomplete")))
    with pytest.raises(ai.AIError, match="unvollständig"):
        ai.run(path, relative, "flashcards", "openai")


def test_missing_key_and_provider_status(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    ai.set_openai_key("")
    path, relative = _doc()
    with pytest.raises(ai.AIError, match="Kein OpenAI-API-Key"):
        ai.run(path, relative, "summary", "openai")
    assert ai.providers()["openai"]["ready"] is False
    ai.set_openai_key("sk-neu")
    assert ai.providers()["openai"]["ready"] is True
