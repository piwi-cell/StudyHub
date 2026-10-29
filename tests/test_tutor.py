"""Study-Tutor mit nachgebauter KI und nachgebautem ElevenLabs: Material, Fragen, Bewertung, Sprache, API."""

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import keyring
import pytest
from fastapi.testclient import TestClient

import ai
import core
import tutor
import voice
from app import app

AUTH = {"x-app-token": "test-token"}
PAGES = ["Die Bilanz stellt Aktiva und Passiva gegenüber. " * 6, "Ein Aktivtausch ändert die Bilanzsumme nicht. " * 6]


@pytest.fixture
def brain(monkeypatch):
    """Ersetzt ai.complete; `calls` sammelt (Anbieter, Prompt), `replies` liefert die Antworten der Reihe nach."""
    calls, replies = [], []

    def fake_complete(provider, system, prompt, schema=None, model=None):
        calls.append((provider, prompt))
        return replies.pop(0)

    monkeypatch.setattr(ai, "complete", fake_complete)
    monkeypatch.setattr(ai, "extract_pages", lambda path: PAGES)
    return calls, replies


def _material(name: str = "bilanz.pdf") -> tuple:
    path = core.MIRROR_DIR / "Accounting" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF " + name.encode())
    return path, f"Accounting/{name}"


QUESTIONS = {"questions": [
    {"question": "Was zeigt die Bilanz?", "answer": "Aktiva und Passiva", "page": 1},
    {"question": "Was macht ein Aktivtausch?", "answer": "Bilanzsumme bleibt gleich", "page": 7},  # Seite erfunden
    {"question": " ", "answer": "leer", "page": 1},  # unbrauchbar
]}


def test_prepare_indexes_once_and_fixes_pages(brain):
    calls, replies = brain
    replies.append(QUESTIONS)
    path, relative = _material()
    assert tutor.prepare(path, relative, "gemma") == {"path": relative, "questions": 2, "skipped": False}
    assert tutor.prepare(path, relative, "gemma")["skipped"] is True  # gleicher Inhalt: kein zweiter KI-Aufruf
    assert len(calls) == 1 and "[Seite 2]" in calls[0][1]
    with closing(tutor.connect()) as db:
        pages = [row[0] for row in db.execute("SELECT page FROM questions ORDER BY id")]
    assert pages == [1, 2]  # erfundene Seite 7 → nächste echte Seite


def test_fixed_questions_need_no_ai_and_are_added_once(brain):
    calls, _ = brain
    path, relative = _material()
    fixed = [{"question": "Was zeigt die Bilanz?", "answer": "Aktiva und Passiva", "page": 9}]
    assert tutor.add_fixed_questions(path, relative, fixed) == 1
    assert tutor.add_fixed_questions(path, relative, fixed) == 0  # zweiter Demo-Start: nichts doppelt
    assert calls == []
    question = tutor.next_question()
    assert question["source"] == "bilanz, S. 2"  # Seite 9 gibt es nicht → nächste echte Seite


def test_demo_data_seeds_tutor_questions(brain):
    import importlib.util

    spec = importlib.util.spec_from_file_location("demo_data", Path(__file__).parent.parent / "scripts/demo_data.py")
    demo_data = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo_data)
    for relative in demo_data.DEMO_QUESTIONS:
        (core.MIRROR_DIR / relative).parent.mkdir(parents=True, exist_ok=True)
        (core.MIRROR_DIR / relative).write_bytes(b"%PDF " + relative.encode())
    demo_data.seed_tutor()
    stats = tutor.stats()
    assert stats["questions"] == sum(len(q) for q in demo_data.DEMO_QUESTIONS.values()) >= 10
    assert "Statistik I" in stats["courses"]


def test_scanned_material_is_rejected(brain, monkeypatch):
    monkeypatch.setattr(ai, "extract_pages", lambda path: ["", ""])
    path, relative = _material("scan.pdf")
    with pytest.raises(tutor.TutorError, match="gescannte"):
        tutor.prepare(path, relative, "gemma")


def test_next_grade_and_stats(brain):
    _, replies = brain
    replies.append(QUESTIONS)
    path, relative = _material()
    tutor.prepare(path, relative, "gemma")
    question = tutor.next_question("Accounting")
    assert question["source"] in ("bilanz, S. 1", "bilanz, S. 2")
    other = tutor.next_question(exclude=question["id"])
    assert other["id"] != question["id"]
    assert tutor.next_question("Anderer Kurs") is None

    replies.append({"verdict": "wrong", "feedback": "Es fehlt die Passivseite."})
    result = tutor.grade(question["id"], "nur Aktiva", "gemma")
    assert result["verdict"] == "wrong" and result["solution"]
    replies.append({"verdict": "unsinn", "feedback": ""})  # ungültige Bewertung → partial, Standardtext
    assert tutor.grade(question["id"], "Aktiva und Passiva", "gemma")["verdict"] == "partial"
    with pytest.raises(tutor.TutorError):
        tutor.grade(question["id"], "   ", "gemma")

    stats = tutor.stats()
    assert (stats["questions"], stats["answered"], stats["wrong"], stats["partial"]) == (2, 2, 1, 1)
    assert stats["courses"] == ["Accounting"]
    assert tutor.next_question(exclude=None)["last"] in (None, "partial")


def test_follow_up_uses_full_text_search(brain):
    calls, replies = brain
    replies.append(QUESTIONS)
    path, relative = _material()
    tutor.prepare(path, relative, "gemma")
    question = tutor.next_question()
    replies.append("Beim Aktivtausch bleibt die Summe gleich. Quelle: bilanz, S. 2")
    result = tutor.follow_up(question["id"], "Was ist ein Aktivtausch?", "claude")
    assert "bilanz, S. 2" in result["sources"]
    assert calls[-1][0] == "claude" and "Aktivtausch ändert" in calls[-1][1]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code, self._payload, self.content = status_code, payload or {}, content

    def json(self):
        return self._payload


@pytest.fixture
def eleven(monkeypatch):
    keyring.set_password(core.KEYCHAIN_SERVICE, voice.KEY_ACCOUNT, "xi-test")
    sent, replies = [], []

    def fake_request(url, **kwargs):
        sent.append({"url": url, **kwargs})
        return replies.pop(0)

    # nur voice.py umleiten: andere Module (Ollama-Check, reMarkable) nutzen dasselbe httpx
    fake_httpx = SimpleNamespace(post=fake_request, get=fake_request, HTTPError=voice.httpx.HTTPError)
    monkeypatch.setattr(voice, "httpx", fake_httpx)
    return sent, replies


def test_transcribe_sends_audio_with_key(eleven):
    sent, replies = eleven
    replies.append(FakeResponse(payload={"text": " Aktiva und Passiva "}))
    assert voice.transcribe(b"x" * 2000, "audio/mp4;codecs=mp4a") == "Aktiva und Passiva"
    call = sent[0]
    assert call["url"].endswith("/speech-to-text") and call["headers"] == {"xi-api-key": "xi-test"}
    assert call["data"]["model_id"] == voice.STT_MODEL and call["files"]["file"][0] == "antwort.mp4"
    with pytest.raises(voice.VoiceError, match="zu kurz"):
        voice.transcribe(b"x", "audio/webm")


def test_speak_and_errors(eleven):
    sent, replies = eleven
    replies.append(FakeResponse(content=b"ID3mp3"))
    assert voice.speak("**Hallo**", "stimme1") == b"ID3mp3"
    assert sent[0]["url"].endswith("/text-to-speech/stimme1") and sent[0]["json"]["model_id"] == voice.TTS_MODEL
    replies.append(FakeResponse(401, {"detail": {"message": "invalid"}}))
    with pytest.raises(voice.VoiceError, match="ungültig"):
        voice.speak("Hallo")
    voice.set_api_key("")
    with pytest.raises(voice.VoiceError, match="Kein ElevenLabs"):
        voice.speak("Hallo")


def test_tutor_api_flow(brain, eleven, monkeypatch):
    _, replies = brain
    _, voice_replies = eleven
    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}, "tutor_brain": "claude"})
    monkeypatch.setattr(ai, "claude_ready", lambda: True)
    client = TestClient(app)
    path, relative = _material()

    assert client.get("/api/tutor/next", headers=AUTH).status_code == 404
    replies.append(QUESTIONS)
    assert client.post("/api/tutor/prepare", json={"path": relative}, headers=AUTH).json()["questions"] == 2
    assert client.post("/api/tutor/prepare", json={"path": "../config.json"}, headers=AUTH).status_code == 404
    status = client.get("/api/tutor/status", headers=AUTH).json()
    assert (status["questions"], status["brain"]) == (2, "claude")
    assert status["brain_ready"] is True and status["voice_ready"] is True

    question = client.get("/api/tutor/next", headers=AUTH).json()
    replies.append({"verdict": "correct", "feedback": "Genau."})
    graded = client.post("/api/tutor/answer", json={"question_id": question["id"], "text": "Aktiva"}, headers=AUTH)
    assert graded.json()["verdict"] == "correct"

    voice_replies.append(FakeResponse(payload={"text": "Aktiva und Passiva"}))
    heard = client.post("/api/tutor/transcribe", content=b"a" * 3000, headers={**AUTH, "content-type": "audio/webm"})
    assert heard.json() == {"text": "Aktiva und Passiva"}
    voice_replies.append(FakeResponse(content=b"ID3"))
    spoken = client.post("/api/tutor/speak", json={"text": "Genau."}, headers=AUTH)
    assert spoken.headers["content-type"] == "audio/mpeg" and spoken.content == b"ID3"
    assert client.post("/api/tutor/speak", json={"text": "x"}).status_code == 403


def test_signed_url_needs_agent_and_key(eleven):
    sent, replies = eleven
    replies.append(FakeResponse(payload={"signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?x=1"}))
    assert voice.signed_url(" agent_1 ").startswith("wss://")
    assert sent[0]["url"].endswith("/convai/conversation/get-signed-url")
    assert sent[0]["params"] == {"agent_id": "agent_1"} and sent[0]["headers"] == {"xi-api-key": "xi-test"}
    replies.append(FakeResponse(404, {"detail": "not found"}))
    with pytest.raises(voice.VoiceError, match="nicht gefunden"):
        voice.signed_url("agent_falsch")
    with pytest.raises(voice.VoiceError, match="Agent-ID"):
        voice.signed_url("")


def test_record_stores_agent_verdict(brain):
    path, relative = _material()
    tutor.add_fixed_questions(path, relative, [{"question": "Was zeigt die Bilanz?", "answer": "Aktiva und Passiva",
                                                "page": 1}])
    question = tutor.next_question(with_solution=True)
    assert question["solution"] == "Aktiva und Passiva"
    assert "solution" not in tutor.next_question()
    assert tutor.next_question(exclude=question["id"])["id"] == question["id"]  # einzige Frage: wiederholen
    result = tutor.record(question["id"], "Aktiva", "partial", "Die Passiva fehlen.")
    assert (result["verdict"], result["source"]) == ("partial", "bilanz, S. 1")
    assert tutor.record(question["id"], "", "unsinn", "")["feedback"]  # ungültig → partial mit Standardtext
    assert (tutor.stats()["partial"], tutor.stats()["answered"]) == (2, 2)
    with pytest.raises(tutor.TutorError):
        tutor.record(9999, "x", "correct", "")


def test_agent_api(brain, eleven, monkeypatch):
    _, voice_replies = eleven
    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    client = TestClient(app)
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}})
    path, relative = _material()
    tutor.add_fixed_questions(path, relative, [{"question": "Was zeigt die Bilanz?", "answer": "Aktiva und Passiva",
                                                "page": 1}])

    assert client.get("/api/tutor/status", headers=AUTH).json()["agent_ready"] is False
    assert client.post("/api/tutor/agent-session", json={}, headers=AUTH).status_code == 400
    client.patch("/api/settings", json={"agent_id": " agent_1 "}, headers=AUTH)
    assert client.get("/api/settings", headers=AUTH).json()["agent_id"] == "agent_1"
    assert client.get("/api/tutor/status", headers=AUTH).json()["agent_ready"] is True

    voice_replies.append(FakeResponse(payload={"signed_url": "wss://signed"}))
    session = client.post("/api/tutor/agent-session", json={"course": "Accounting"}, headers=AUTH).json()
    assert session["signed_url"] == "wss://signed" and "xi-test" not in str(session)
    assert "{{course}}" in session["prompt"] and session["dynamic_variables"] == {"course": "Accounting"}

    question = client.get("/api/tutor/next?solution=true", headers=AUTH).json()
    assert question["solution"] == "Aktiva und Passiva"
    body = {"question_id": question["id"], "answer": "Aktiva", "verdict": "correct", "feedback": "Genau."}
    assert client.post("/api/tutor/record", json=body, headers=AUTH).json()["verdict"] == "correct"
    assert client.post("/api/tutor/record", json={**body, "verdict": "egal"}, headers=AUTH).status_code == 422
    assert client.post("/api/tutor/record", json={**body, "question_id": 9999}, headers=AUTH).status_code == 404
    assert client.post("/api/tutor/record", json=body).status_code == 403


def test_prepare_pending_handles_new_changed_and_bad_files(brain, monkeypatch):
    calls, replies = brain
    good, good_rel = _material("bilanz.pdf")
    scan, scan_rel = _material("scan.pdf")
    other = core.MIRROR_DIR / "Accounting" / "bild.png"
    other.write_bytes(b"png")
    files = [(good, good_rel), (scan, scan_rel), (other, "Accounting/bild.png")]

    def pages(path):
        return ["", ""] if path.name == "scan.pdf" else PAGES

    monkeypatch.setattr(ai, "extract_pages", pages)
    assert [rel for _, rel in tutor.pending(files)] == [good_rel, scan_rel]  # PNG zählt nicht
    replies.append(QUESTIONS)
    result = tutor.prepare_pending(files)
    assert result == {"questions": 2, "files": 2, "pending": 0}
    assert calls[0][0] == tutor.AUTO_BRAIN == "gemma"
    assert tutor.pending(files) == []  # gute Datei fertig, gescannte übersprungen
    assert tutor.progress["running"] is False

    scan.write_bytes(b"%PDF neu, jetzt mit Text")  # geänderte Datei wird erneut versucht
    assert [rel for _, rel in tutor.pending(files)] == [scan_rel]


def test_prepare_pending_stops_when_gemma_fails(brain, monkeypatch):
    path, relative = _material()

    def offline(*args, **kwargs):
        raise ai.AIError("Ollama läuft nicht")

    monkeypatch.setattr(ai, "complete", offline)
    result = tutor.prepare_pending([(path, relative)])
    assert result["pending"] == 1 and "Ollama" in tutor.progress["error"]
    assert tutor.pending([(path, relative)]) == [(path, relative)]  # nächster Durchlauf versucht es erneut


def test_prepare_pending_skips_file_with_invalid_json_and_continues(brain, monkeypatch):
    calls, replies = brain
    bad, bad_rel = _material("kaputt.pdf")
    good, good_rel = _material("bilanz.pdf")
    monkeypatch.setattr(ai, "gemma_model", lambda: "gemma3:4b")
    answers = iter([ai.AIFormatError("Gemma hat kein gültiges JSON geliefert"), QUESTIONS])

    def complete(*args, **kwargs):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(ai, "complete", complete)
    files = [(bad, bad_rel), (good, good_rel)]
    result = tutor.prepare_pending(files)
    assert result == {"questions": 2, "files": 2, "pending": 0} and tutor.progress["error"] == ""
    assert tutor.prepare_pending(files)["files"] == 0  # unbrauchbare Datei nicht sofort erneut

    monkeypatch.setattr(ai, "gemma_model", lambda: "gemma3:12b")  # anderes Modell: neuer Versuch
    answers = iter([QUESTIONS])
    assert tutor.prepare_pending(files)["questions"] == 2


def test_auto_worker_skips_tiny_gemma(monkeypatch):
    import app as app_module
    monkeypatch.setattr(ai, "providers", lambda: {"gemma": {"local": True, "small": True, "model": "gemma3:270m"}})
    monkeypatch.setattr(tutor, "prepare_pending", lambda *args, **kwargs: pytest.fail("darf nicht laufen"))
    waits = []

    class Wake:  # erster Aufruf: Startpause, zweiter: nach einem Durchlauf beenden
        def wait(self, _seconds):
            waits.append(_seconds)
            if len(waits) == 2:
                app_module._stopping.set()

        def clear(self):
            pass

    monkeypatch.setattr(app_module, "_tutor_wake", Wake())
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}})
    try:
        app_module.tutor_auto_worker()
    finally:
        app_module._stopping.clear()
    assert "gemma3:270m ist für automatische Fragen zu klein" in tutor.progress["error"]
    tutor.progress["error"] = ""


def test_auto_setting_and_status(brain, monkeypatch):
    monkeypatch.setattr(ai, "ollama_models", lambda: None)
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}})
    client = TestClient(app)
    auto = client.get("/api/tutor/status", headers=AUTH).json()["auto"]
    assert auto["enabled"] is True and auto["gemma_ready"] is False
    client.patch("/api/settings", json={"tutor_auto": False}, headers=AUTH)
    assert client.get("/api/tutor/status", headers=AUTH).json()["auto"]["enabled"] is False


def _index(path, relative):
    with closing(tutor.connect()) as db:
        tutor.index_file(db, path, relative)


def _chat(say, kind="chat", verdict="none", question="", solution="", ref="", course=""):
    return {"say": say, "kind": kind, "verdict": verdict, "question": question, "solution": solution,
            "ref": ref, "course": course}


def test_converse_asks_own_question_hints_and_grades(brain):
    calls, replies = brain
    path, relative = _material()
    _index(path, relative)

    # Start: Tutor stellt eine eigene Frage aus dem Material → landet im Pool
    replies.append(_chat("Hallo! Was zeigt die Bilanz?", "question", question="Was zeigt die Bilanz?",
                         solution="Aktiva und Passiva", ref="M1"))
    first = tutor.converse("", [], "Accounting", None, "claude")
    assert first["kind"] == "question" and first["question_id"] and first["source"].startswith("bilanz, S.")
    assert "Material:" in calls[-1][1] and "Beginn des Gesprächs" in calls[-1][1]
    history = [{"role": "tutor", "text": first["say"]}]

    # Falsche Antwort: erst ein Hinweis, Frage bleibt offen, nichts gespeichert
    replies.append(_chat("Fast. Denk an die zweite Seite der Bilanz.", "hint"))
    hint = tutor.converse("nur Aktiva", history, "Accounting", first["question_id"], "claude")
    assert hint["question_id"] == first["question_id"] and hint["verdict"] is None
    assert "Musterlösung: Aktiva und Passiva" in calls[-1][1]
    assert f"[P{first['question_id']}]" not in calls[-1][1]  # offene Frage nicht noch einmal als Vorschlag
    assert calls[-1][1].count("bilanz, S. 1\n") <= 1  # jede Seite nur einmal im Material
    assert tutor.stats()["answered"] == 0

    # Zweiter Versuch richtig: Bewertung gespeichert, neue Pool-Frage aus dem Gespräch
    replies.append(_chat("Genau! Und was ist ein Aktivtausch?", "feedback", "correct",
                         "Was ist ein Aktivtausch?", "Bilanzsumme bleibt gleich", "M1"))
    done = tutor.converse("Aktiva und Passiva", history, "Accounting", first["question_id"], "claude")
    assert done["verdict"] == "correct" and done["question_id"] not in (None, first["question_id"])
    assert tutor.stats()["correct"] == 1 and tutor.stats()["questions"] == 2


def test_converse_explains_and_switches_course(brain, monkeypatch):
    calls, replies = brain
    path, relative = _material()
    _index(path, relative)
    stats = core.MIRROR_DIR / "Statistik" / "tests.pdf"
    stats.parent.mkdir(parents=True, exist_ok=True)
    stats.write_bytes(b"%PDF stat")
    monkeypatch.setattr(ai, "extract_pages", lambda p: ["Ein Fehler 1. Art verwirft eine wahre Nullhypothese. " * 5])
    _index(stats, "Statistik/tests.pdf")

    # Freie Frage: Erklärung, offene Frage bleibt bestehen
    replies.append(_chat("Ein Aktivtausch ändert die Bilanzsumme nicht. Quelle: bilanz, S. 2", "explanation", ref="M1"))
    answer = tutor.converse("Was ist ein Aktivtausch?", [], "Accounting", None, "gemma")
    assert answer["kind"] == "explanation" and answer["question_id"] is None and answer["sources"]

    # Kurswechsel per Sprache: zweiter Aufruf mit dem Material des neuen Kurses
    replies.append(_chat("Gern, wechseln wir.", course="statistik"))
    replies.append(_chat("Was ist ein Fehler 1. Art?", "question", question="Was ist ein Fehler 1. Art?",
                         solution="Wahre H0 wird verworfen", ref="M1"))
    switched = tutor.converse("Lass uns Statistik machen", [], "Accounting", None, "gemma")
    assert switched["course"] == "Statistik" and "Aktueller Kurs: Statistik" in calls[-1][1]
    assert "Fehler 1. Art" in calls[-1][1] and switched["source"] == "tests, S. 1"


def test_chat_api(brain, monkeypatch):
    _, replies = brain
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}, "tutor_brain": "claude"})
    path, relative = _material()
    _index(path, relative)
    client = TestClient(app)
    replies.append(_chat("Was zeigt die Bilanz?", "question", question="Was zeigt die Bilanz?",
                         solution="Aktiva und Passiva", ref="M1"))
    body = {"text": "", "history": [], "course": "Accounting"}
    result = client.post("/api/tutor/chat", json=body, headers=AUTH).json()
    assert result["say"] == "Was zeigt die Bilanz?" and result["question_id"]
    bad = {**body, "history": [{"role": "system", "text": "x"}]}
    assert client.post("/api/tutor/chat", json=bad, headers=AUTH).status_code == 422
    assert client.post("/api/tutor/chat", json=body).status_code == 403

    def offline(*args, **kwargs):
        raise ai.AIError("Ollama läuft nicht")

    monkeypatch.setattr(ai, "complete", offline)
    assert client.post("/api/tutor/chat", json=body, headers=AUTH).json()["detail"] == "Ollama läuft nicht"
