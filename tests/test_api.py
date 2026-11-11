"""Lokale API: Token-Schutz, Pfadschutz, Grundfunktionen im Demo-Datenordner."""


import pytest
from fastapi.testclient import TestClient

import ai
import app as app_module
import core
import integrations
from app import app

AUTH = {"x-app-token": "test-token"}


@pytest.fixture
def client():
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}})
    path = core.MIRROR_DIR / "Statistik/Vorlesung/07 Tests.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Hypothesentests", encoding="utf-8")
    return TestClient(app)


def test_requires_token(client):
    assert client.get("/api/status").status_code == 403
    assert client.get("/api/status", headers={"x-app-token": "falsch"}).status_code == 403


def test_status_and_files(client):
    status = client.get("/api/status", headers=AUTH).json()
    assert status["demo"] is True and status["files"] == 1
    files = client.get("/api/files", headers=AUTH).json()["files"]
    assert files[0]["course"] == "Statistik" and files[0]["folder"] == "Vorlesung"


def test_file_download_and_path_traversal(client):
    ok = client.get("/api/file", params={"path": "Statistik/Vorlesung/07 Tests.txt", "t": "test-token"})
    assert ok.status_code == 200 and ok.text == "Hypothesentests"
    core.APP_DIR.joinpath("geheim.txt").write_text("nein", encoding="utf-8")
    for bad in ("../geheim.txt", "../config.json", "/etc/hosts"):
        assert client.get("/api/file", params={"path": bad}, headers=AUTH).status_code == 404


def test_share_without_result_or_telegram(client):
    body = {"path": "Statistik/Vorlesung/07 Tests.txt", "task": "summary", "target": "telegram"}
    response = client.post("/api/share", json=body, headers=AUTH)
    assert response.status_code == 400


def test_sync_is_disabled_in_demo_mode(client):
    assert client.post("/api/sync", headers=AUTH).json()["started"] is False


def test_markdown_to_telegram_escapes_html():
    text = integrations.markdown_to_telegram("## Titel <x>\n- **fett** & `code`")
    assert text == "<b>Titel &lt;x&gt;</b>\n• <b>fett</b> &amp; <code>code</code>"


def test_settings_offer_folder_suggestions(client, monkeypatch, tmp_path):
    import cli
    monkeypatch.setattr(cli, "ICLOUD", tmp_path / "fehlt")
    labels = [s["label"] for s in client.get("/api/settings", headers=AUTH).json()["folder_suggestions"]]
    assert labels == ["Dokumente › ILIAS"]
    (tmp_path / "fehlt").mkdir()
    labels = [s["label"] for s in client.get("/api/settings", headers=AUTH).json()["folder_suggestions"]]
    assert labels[0] == "iCloud Drive › ILIAS"


def test_settings_show_version_and_program_folder(client, monkeypatch):
    import tomllib

    settings = client.get("/api/settings", headers=AUTH).json()
    project = core.CODE_DIR.parent
    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert settings["version"] == pyproject["project"]["version"]
    assert settings["code_dir"] == str(project)


def test_status_shows_sync_progress_only_while_running(client, monkeypatch):
    import sys
    import time

    import sync

    server = sys.modules["app"]
    core.save_json(sync.PROGRESS_FILE, {"phase": "kurse", "total": 8, "done": 3, "started": time.time() - 80.5})
    assert client.get("/api/status", headers=AUTH).json()["progress"] is None  # Rest eines alten Laufs
    monkeypatch.setattr(server, "sync_running", lambda: True)
    progress = client.get("/api/status", headers=AUTH).json()["progress"]
    assert progress["text"] == "3 von 8 Kursen fertig · 1:20" and progress["done"] == 3


def test_ai_usage_endpoint(client):
    usage = client.get("/api/ai/usage", headers=AUTH).json()
    assert usage["ergebnisse"] == 0 and usage["kosten_usd"] == 0
    assert client.get("/api/ai/usage", params={"month": "2026-10"}, headers=AUTH).json()["monat"] == "2026-10"
    assert client.get("/api/ai/usage", params={"month": "../x"}, headers=AUTH).status_code == 422


def test_renaming_a_course_keeps_ai_results_learning_state_cards_and_search(client):
    """Regression: Nach dem Umbenennen eines Kurses (StudyHub › Kurse) fehlten KI-Ergebnisse, Lernplan-Status,
    Kartenfortschritt und Klausurtermin, weil sie am alten Pfad bzw. Kursnamen hingen."""
    import cards
    import search_index
    import studyhub

    config = core.load_config()
    config["courses"] = {"Statistik [V] (HWS 2026)": {"name": "Statistik", "sync": True}}
    core.save_config(config)
    old = "Statistik/Vorlesung/07 Tests.txt"
    file = core.MIRROR_DIR / old
    file.write_text("Hypothesentests: Die Nullhypothese H0 wird gegen H1 getestet. " * 10, encoding="utf-8")
    entry = ai.load_entry(file)
    entry["flashcards"] = {"output": {"cards": [{"front": "Was ist H0?", "back": "Nullhypothese"}]}, "created": 1}
    ai.save_entry(entry, old)
    cards.review(cards.card_id(old, "Was ist H0?"), "gewusst")
    cards.add_cards("Statistik", [("Alpha?", "5 %")], "Textdatei")
    studyhub.set_state(old, "erledigt")
    studyhub.set_hidden(old, True)
    studyhub.set_hidden(old, False)
    studyhub.set_exam("Statistik", "2099-02-01")
    studyhub.set_skills("Statistik", ["glossar"])
    assert search_index.index_all([(file, old)]) == 1

    answer = client.patch("/api/courses", json={"title": "Statistik [V] (HWS 2026)", "name": "Statistik I"},
                          headers=AUTH)
    assert answer.json() == {"ok": True}
    new = "Statistik I/Vorlesung/07 Tests.txt"
    assert [f["path"] for f in client.get("/api/files", headers=AUTH).json()["files"]] == [new]
    assert client.get(f"/api/ai/result?path={new}", headers=AUTH).json()["flashcards"]
    assert studyhub.load_state()[new]["status"] == "erledigt"
    assert studyhub.load_exams() == {"Statistik I": "2099-02-01"}
    assert studyhub.load_skills() == {"Statistik I": ["glossar"]}
    data = cards.load()
    assert data["reviews"][cards.card_id(new, "Was ist H0?")]["reps"] == 1
    assert [c["kurs"] for c in data["imported"].values()] == ["Statistik I"]
    assert [h["path"] for h in search_index.search_material("Nullhypothese")] == [new]
    detail = client.get("/api/studyhub", headers=AUTH).json()
    assert detail["skills"] == {"Statistik I": ["glossar"]}


def test_target_folder_must_be_a_full_path(client, monkeypatch):
    for value in ("", "   ", "Uni/ILIAS"):
        answer = client.patch("/api/settings", json={"target_dir": value}, headers=AUTH)
        assert answer.status_code == 400 and "vollständigen Ordnerpfad" in answer.json()["detail"]
    assert core.load_config()["target_dir"] == ""

    monkeypatch.setattr(app_module, "sync_running", lambda: True)
    answer = client.patch("/api/settings", json={"target_dir": str(core.APP_DIR / "Ziel")}, headers=AUTH)
    assert answer.status_code == 409 and not (core.APP_DIR / "Ziel").exists()


def test_skills_are_saved_per_course(client):
    assert client.patch("/api/studyhub/skills", json={"kurs": "Statistik", "skills": ["glossar", "mindmap", "glossar"]},
                        headers=AUTH).json() == {"skills": ["glossar", "mindmap"]}
    assert client.get("/api/studyhub", headers=AUTH).json()["skills"] == {"Statistik": ["glossar", "mindmap"]}
    assert client.patch("/api/studyhub/skills", json={"kurs": "Statistik", "skills": ["probeklausur"]},
                        headers=AUTH).status_code == 400
    assert client.patch("/api/studyhub/skills", json={"kurs": "Gibt es nicht", "skills": []},
                        headers=AUTH).status_code == 404
    assert client.patch("/api/studyhub/skills", json={"kurs": "Statistik", "skills": []}, headers=AUTH).json() == {
        "skills": []}


def test_reveal_only_shows_files_from_the_mirror(client, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module.subprocess, "run", lambda args, **_: calls.append(args))
    assert client.post("/api/reveal", json={"path": "../../etc/passwd"}, headers=AUTH).status_code == 404
    assert client.post("/api/reveal", json={"path": "Statistik/Vorlesung/07 Tests.txt"}, headers=AUTH).json()["ok"]
    assert calls == [["open", "-R", str((core.MIRROR_DIR / "Statistik/Vorlesung/07 Tests.txt").resolve())]]


def test_ui_files_are_revalidated_after_updates(client):
    answer = client.get("/ui/studyhub/js/app.js")
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-cache"


def test_start_page_is_studyhub(client):
    answer = client.get("/?t=abc", follow_redirects=False)
    assert answer.status_code == 307 and answer.headers["location"] == "/ui/studyhub/index.html?t=abc"
    assert not (app_module.UI_DIR / "index.html").exists()  # klassische Ansicht entfernt


def test_search_finds_file_names_and_text_but_not_hidden_files(client):
    import search_index
    import studyhub

    text = "Beim Hypothesentest prüft man die Nullhypothese <H0> gegen die Alternative. " * 5
    (core.MIRROR_DIR / "Statistik/Vorlesung/07 Tests.txt").write_text(text, encoding="utf-8")
    other = core.MIRROR_DIR / "Statistik/Übung/Blatt 3 Hypothesen.md"
    other.parent.mkdir(parents=True)
    other.write_text("Aufgabe 1: Konfidenzintervall berechnen. " * 10, encoding="utf-8")
    files = [(p, core.nfc(p.relative_to(core.MIRROR_DIR).as_posix())) for p in app_module.mirror_files()]
    assert client.get("/api/search?q=Nullhyp", headers=AUTH).json()["ausstehend"] == 2
    assert search_index.index_all(files) == 2 and search_index.index_all(files) == 0  # unverändert: nicht noch einmal

    result = client.get("/api/search?q=Nullhyp", headers=AUTH).json()
    assert result["ausstehend"] == 0
    hit = result["treffer"][0]
    assert hit["pfad"] == "Statistik/Vorlesung/07 Tests.txt" and hit["seite"] == 1
    assert "<mark>Nullhypothese</mark>" in hit["ausschnitt"] and "&lt;H0&gt;" in hit["ausschnitt"]
    names = client.get("/api/search?q=blatt hypo", headers=AUTH).json()["treffer"]
    assert names[0]["name"] == "Blatt 3 Hypothesen.md" and names[0]["seite"] is None
    assert client.get("/api/search?q=x", headers=AUTH).json()["treffer"] == []

    studyhub.set_hidden("Statistik/Vorlesung/07 Tests.txt", True)
    assert client.get("/api/search?q=Nullhyp", headers=AUTH).json()["treffer"] == []


def test_share_learning_topic_and_original(client, monkeypatch):
    sent = []
    monkeypatch.setattr(integrations, "send_telegram", lambda title, task, output: sent.append((title, task, output)))
    path = "Statistik/Vorlesung/07 Tests.txt"
    body = {"path": path, "task": "thema", "target": "telegram"}
    assert "Noch kein Ergebnis" in client.post("/api/share", json=body, headers=AUTH).json()["detail"]

    entry = ai.load_entry(core.MIRROR_DIR / path)
    entry["thema"] = {"output": {"titel": "Tests", "kernidee": "Man prüft eine Annahme.", "einfacher": "",
                                 "formeln": [], "falle": "p-Wert falsch deuten", "seite": 2}, "created": 1}
    ai.save_entry(entry, path)
    assert "nicht verbunden" in client.post("/api/share", json=body, headers=AUTH).json()["detail"]
    config = core.load_config()
    config["telegram"] = True
    core.save_config(config)
    assert client.post("/api/share", json=body, headers=AUTH).json() == {"ok": True, "via": "Telegram"}
    title, task, output = sent[0]
    assert title == "07 Tests" and task == "summary" and output.startswith("## Worum es geht\nMan prüft eine Annahme.")
    assert "S. 2" in output and "Klausurfalle: p-Wert" in output

    original = {"path": path, "task": "original", "target": "remarkable"}
    assert client.post("/api/share", json=original, headers=AUTH).json()["detail"] == "Ans reMarkable gehen nur PDFs"
    assert client.post("/api/share", json={**body, "task": "alles"}, headers=AUTH).status_code == 422


def test_questions_about_a_document_appear_in_its_topic(client, monkeypatch):
    path = "Statistik/Vorlesung/07 Tests.txt"
    (core.MIRROR_DIR / path).write_text("Hypothesentests prüfen eine Annahme anhand von Daten. " * 10, encoding="utf-8")
    monkeypatch.setattr(ai, "_claude", lambda pages, p, task, instruction, model: (
        "**H0** ist die Nullhypothese." if task == "qa" else "## Worum es geht\nTests.", {"provider": "claude"}))
    monkeypatch.setattr(ai, "has_profile", lambda: True)
    for task, question in (("summary", ""), ("qa", "Was ist <H0>?")):
        assert client.post("/api/ai/run", json={"path": path, "task": task, "question": question,
                                                "provider": "claude"}, headers=AUTH).status_code == 200
    thema = client.get("/api/studyhub", headers=AUTH).json()["details"]["statistik"]["themen"][0]
    assert thema["fragen"] == [{"frage": "Was ist &lt;H0&gt;?", "antwort": "<b>H0</b> ist die Nullhypothese."}]
