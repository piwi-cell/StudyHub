"""Gemma über die Gemini API (Google AI Studio) mit nachgebauten Antworten: Anfrageform, Auswahl
lokal/API, JSON-Auswertung, Fehlerfälle, Einstellungen und Tutor-Automatik."""

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


def _reply(*texts: str, thought: str = "") -> dict:
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": t} for t in texts]
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]}


@pytest.fixture
def gemini(monkeypatch):
    """Kein Ollama, Google-Key gesetzt; `calls` enthält die gesendeten Anfragen."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    ai.set_google_key("AIza-test")
    calls, replies = [], []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "body": json, "headers": headers})
        return replies.pop(0)

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    return calls, replies


def _doc(text: str = "Elastizität der Nachfrage. " * 50):
    path = core.MIRROR_DIR / "Mikro/kapitel5.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, "Mikro/kapitel5.txt"


def test_summary_goes_to_gemini_api_without_thoughts(gemini):
    calls, replies = gemini
    replies.append(FakeResponse(200, _reply("## Kernaussagen", " (S. 1)", thought="Ich überlege …")))
    path, relative = _doc()
    result = ai.run(path, relative, "summary", "gemma")

    call = calls[0]
    assert call["url"] == ai.GEMINI_URL.format(model=ai.DEFAULT_GEMMA_API_MODEL)
    assert call["headers"] == {"x-goog-api-key": "AIza-test"}
    assert call["body"]["systemInstruction"]["parts"][0]["text"] == ai.SYSTEM
    assert "Elastizität" in call["body"]["contents"][0]["parts"][0]["text"]
    assert result["output"] == "## Kernaussagen (S. 1)" and result["provider"] == "gemma"
    assert result["model"] == ai.DEFAULT_GEMMA_API_MODEL and result["input_mode"] == "Text (Gemini API)"


def test_json_tasks_put_schema_in_prompt_and_unwrap_fences(gemini):
    calls, replies = gemini
    cards = {"cards": [{"front": "Was ist e?", "back": "Preiselastizität"}]}
    replies.append(FakeResponse(200, _reply("```json\n" + json.dumps(cards) + "\n```")))
    path, relative = _doc()
    assert ai.run(path, relative, "flashcards", "gemma")["output"] == cards
    assert '"front"' in calls[0]["body"]["contents"][0]["parts"][0]["text"]  # Schema steht im Prompt

    replies.append(FakeResponse(200, _reply("Leider kein JSON")))
    with pytest.raises(ai.AIFormatError, match="kein gültiges JSON"):
        ai.run(path, relative, "thema", "gemma")


def test_model_choice_and_tutor_complete(gemini):
    calls, replies = gemini
    core.save_config({**core.load_config(), "gemma_api_model": "gemma-4-31b-it"})
    replies.append(FakeResponse(200, _reply('{"verdict": "correct", "feedback": "Gut"}')))
    result = ai.complete("gemma", "System", "Bewerte", tutor.GRADE_SCHEMA)
    assert result == {"verdict": "correct", "feedback": "Gut"}
    assert calls[0]["url"].endswith("/gemma-4-31b-it:generateContent")
    assert calls[0]["body"]["generationConfig"]["maxOutputTokens"] == 2000


@pytest.mark.parametrize(("status", "payload", "message"), [
    (400, {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT"}}, "Key ungültig"),
    (429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}, "Kontingent"),
    (404, {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}}, "gibt es bei der Gemini API nicht"),
    (500, {"error": {"code": 500, "message": "Internal", "status": "INTERNAL"}}, "Gemini-API-Fehler: Internal"),
    (200, {"promptFeedback": {"blockReason": "SAFETY"}}, "keine Antwort geliefert \\(SAFETY\\)"),
])
def test_api_errors_are_readable_and_never_show_the_key(gemini, status, payload, message):
    _, replies = gemini
    retried = status == 500
    replies.extend([FakeResponse(status, payload)] * (ai.GEMINI_TRIES if retried else 1))
    path, relative = _doc()
    with pytest.raises(ai.AIError, match=message) as error:
        ai.run(path, relative, "summary", "gemma")
    assert "AIza-test" not in str(error.value)


def test_temporary_errors_are_retried(gemini):
    calls, replies = gemini
    replies.extend([FakeResponse(500, {"error": {"code": 500, "message": "Internal"}}),
                    FakeResponse(200, {"usageMetadata": {}}),  # leere Antwort ohne Sperrgrund
                    FakeResponse(200, _reply("## Kernaussagen"))])
    path, relative = _doc()
    assert ai.run(path, relative, "summary", "gemma")["output"] == "## Kernaussagen"
    assert len(calls) == 3 and not replies


def test_local_ollama_wins_over_api(monkeypatch):
    ai.set_google_key("AIza-test")
    monkeypatch.setattr(ai, "ollama_models", lambda: ["gemma3:4b"])
    assert ai.gemma_backend() == "ollama"
    gemma = ai.providers()["gemma"]
    assert gemma["ready"] and gemma["local"] and gemma["api"] and gemma["model"] == "gemma3:4b"

    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    assert ai.gemma_backend() == "api" and ai.providers()["gemma"]["model"] == ai.DEFAULT_GEMMA_API_MODEL
    ai.set_google_key("")
    assert ai.gemma_backend() is None and ai.providers()["gemma"]["ready"] is False


def test_settings_store_key_in_keyring_and_auto_stays_local(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    client = TestClient(app)
    body = {"google_key": "AIza-geheim", "gemma_api_model": "gemma-4-31b-it", "tutor_brain": "gemma"}
    assert client.patch("/api/settings", json=body, headers=AUTH).status_code == 200
    assert ai.google_key() == "AIza-geheim" and "AIza-geheim" not in core.CONFIG_FILE.read_text(encoding="utf-8")

    settings = client.get("/api/settings", headers=AUTH).json()
    assert settings["has_google_key"] is True and settings["gemma_api_model"] == "gemma-4-31b-it"
    assert "AIza-geheim" not in json.dumps(settings)
    assert client.get("/api/ai/providers", headers=AUTH).json()["gemma"]["api"] is True

    # Der Tutor kann mit der API bewerten, die automatische Vorbereitung läuft aber nur lokal
    status = client.get("/api/tutor/status", headers=AUTH).json()
    assert status["brain_ready"] is True and status["auto"]["gemma_ready"] is False

    client.patch("/api/settings", json={"gemma_api_model": "gemma-99"}, headers=AUTH)
    assert ai.gemma_api_model() == "gemma-4-31b-it"  # unbekanntes Modell wird ignoriert
