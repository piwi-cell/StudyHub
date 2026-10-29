"""Gemini als vierter Anbieter (Gemini API) mit nachgebauten Antworten: Anfrageform, gescannte PDFs,
JSON-Modus und Prüfung, Längenlimit, Tutor, Einstellungen. Kein echter Aufruf."""

import json

import pytest
from fastapi.testclient import TestClient

import ai
import core
import tutor
from app import app

AUTH = {"x-app-token": "test-token"}


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _reply(text: str, finish: str = "STOP", thought: str = "") -> dict:
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": text}]
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 1500, "cachedContentTokenCount": 1200,
                          "candidatesTokenCount": 300, "thoughtsTokenCount": 200},
        "modelVersion": "gemini-3.8-flash",
    }


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    ai.set_google_key("AIza-test")
    calls, replies = [], []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "body": json, "headers": headers})
        return replies.pop(0)

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    yield calls, replies
    ai.set_google_key("")


def _doc(text: str = "Elastizität der Nachfrage. " * 50, name: str = "kapitel5.txt"):
    path = core.MIRROR_DIR / "Mikro" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path, f"Mikro/{name}"


def test_summary_sends_document_first_and_counts_thoughts(gemini):
    calls, replies = gemini
    replies.append(FakeResponse(200, _reply("## Kernaussagen", thought="Ich überlege …")))
    path, relative = _doc()
    result = ai.run(path, relative, "summary", "gemini", model="gemini-4-argon")

    assert calls[0]["url"].endswith("/models/gemini-4-argon:generateContent")
    assert calls[0]["headers"] == {"x-goog-api-key": "AIza-test"}  # Key im Header, nie in der URL
    body = calls[0]["body"]
    parts = body["contents"][0]["parts"]
    assert parts[0]["text"].startswith("Dokument „kapitel5.txt“") and "[Seite 1]" in parts[0]["text"]
    assert parts[1]["text"] == ai.TASKS["summary"]
    assert body["systemInstruction"]["parts"][0]["text"] == ai.SYSTEM
    assert "responseMimeType" not in body["generationConfig"]
    assert result["output"] == "## Kernaussagen"  # ohne Denkschritte
    assert result["provider"] == "gemini" and result["model"] == "gemini-3.8-flash"
    assert (result["tokens_in"], result["cache_read"], result["tokens_out"]) == (300, 1200, 500)
    assert ai.run(path, relative, "summary", "gemini")["cached"] is True  # kein zweiter Aufruf
    assert len(calls) == 1


def test_flashcards_use_json_mode_and_are_checked(gemini):
    calls, replies = gemini
    cards = {"cards": [{"front": "Was ist Elastizität?", "back": "Relative Mengenänderung."}]}
    replies.append(FakeResponse(200, _reply(json.dumps(cards))))
    path, relative = _doc()
    assert ai.run(path, relative, "flashcards", "gemini")["output"] == cards
    config = calls[0]["body"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert calls[0]["url"].endswith(f"/models/{ai.DEFAULT_GEMINI_MODEL}:generateContent")
    assert '"cards"' in calls[0]["body"]["contents"][0]["parts"][-1]["text"]  # Schema im Prompt

    replies.append(FakeResponse(200, _reply('{"karten": []}')))
    with pytest.raises(ai.AIFormatError, match="unvollständiges JSON"):
        ai.run(path, relative, "flashcards", "gemini", force=True)


def test_truncated_json_is_a_readable_error(gemini):
    _, replies = gemini
    replies.append(FakeResponse(200, _reply('{"cards": [{"front": "Was', finish="MAX_TOKENS")))
    path, relative = _doc()
    with pytest.raises(ai.AIError, match="Längenlimit"):
        ai.run(path, relative, "flashcards", "gemini")


def test_scanned_pdf_goes_as_pdf(gemini, monkeypatch):
    calls, replies = gemini
    monkeypatch.setattr(ai, "extract_pages", lambda _path: ["", ""])  # keine Textebene
    replies.append(FakeResponse(200, _reply("## Kernaussagen")))
    path, relative = _doc(b"%PDF-1.4 gescannt", "folien.pdf")
    result = ai.run(path, relative, "summary", "gemini")
    document = calls[0]["body"]["contents"][0]["parts"][0]
    assert document["inlineData"]["mimeType"] == "application/pdf"
    assert result["input_mode"].startswith("PDF")


def test_tutor_can_use_gemini(gemini):
    calls, replies = gemini
    replies.append(FakeResponse(200, _reply('{"verdict": "correct", "feedback": "Gut"}')))
    result = ai.complete("gemini", "System", "Bewerte", tutor.GRADE_SCHEMA, "gemini-3.5-flash-lite")
    assert result == {"verdict": "correct", "feedback": "Gut"}
    assert calls[0]["url"].endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert "gemini" in tutor.BRAINS


def test_errors_are_readable_and_never_show_the_key(gemini):
    _, replies = gemini
    replies.append(FakeResponse(429, {"error": {"code": 429, "message": "Quota exceeded"}}))
    path, relative = _doc()
    with pytest.raises(ai.AIError, match="Kontingent") as error:
        ai.run(path, relative, "summary", "gemini")
    assert "AIza-test" not in str(error.value)


def test_settings_choose_gemini_and_model(gemini, monkeypatch):
    client = TestClient(app)
    body = {"ai_provider": "gemini", "gemini_model": "gemini-4-argon", "tutor_brain": "gemini"}
    settings = client.patch("/api/settings", json=body, headers=AUTH).json()
    assert (settings["ai_provider"], settings["gemini_model"], settings["tutor_brain"]) == \
        ("gemini", "gemini-4-argon", "gemini")
    providers = client.get("/api/ai/providers", headers=AUTH).json()
    assert providers["gemini"]["ready"] is True and providers["gemini_model"] == "gemini-4-argon"
    assert client.get("/api/tutor/status", headers=AUTH).json()["brain_ready"] is True

    client.patch("/api/settings", json={"gemini_model": "gemini-99"}, headers=AUTH)
    assert core.load_config()["gemini_model"] == "gemini-4-argon"  # unbekanntes Modell wird ignoriert

    # /api/ai/run nimmt das gewählte Modell
    _, replies = gemini
    replies.append(FakeResponse(200, _reply("## Kernaussagen")))
    _, relative = _doc()
    result = client.post("/api/ai/run", json={"path": relative, "task": "summary"}, headers=AUTH).json()
    assert result["provider"] == "gemini" and gemini[0][-1]["url"].endswith("/gemini-4-argon:generateContent")
