"""Karteikarten: SM-2, Lernstand in StudyHub, eigene Karten, Textimport/-export, Klausurtermine."""

import time

import pytest
from fastapi.testclient import TestClient
from test_studyhub import AI, CONFIG, FILES

import cards
import core
import studyhub
from app import app

AUTH = {"x-app-token": "test-token"}
DAY = 86400
NOW = 1_800_000_000.0


def test_sm2_intervals_grow_and_reset():
    r = cards.schedule(None, "gewusst", NOW)
    assert (r["reps"], r["interval"], r["due"]) == (1, 1, NOW + DAY) and r["ease"] == 2.6
    r = cards.schedule(r, "gewusst", NOW)
    assert r["interval"] == 6
    r = cards.schedule(r, "schwer", NOW)
    assert r["interval"] == round(6 * 2.7) and r["ease"] == pytest.approx(2.56)
    r = cards.schedule(r, "nochmal", NOW)
    assert (r["reps"], r["lapses"], r["due"]) == (0, 1, NOW + cards.RELEARN_SECONDS)
    assert r["ease"] == pytest.approx(2.02)
    for _ in range(10):
        r = cards.schedule(r, "nochmal", NOW)
    assert r["ease"] == cards.MIN_EASE
    with pytest.raises(cards.CardError):
        cards.schedule(None, "super", NOW)


def test_overview_shows_due_new_and_own_cards():
    path = "Accounting/Vorlesung/01 Bilanz.pdf"
    ki_id = cards.card_id(path, "Was ist <b>Aktiva</b>?")
    karten = {"reviews": {ki_id: cards.schedule(None, "gewusst", NOW)}, "imported": {}}
    data = studyhub.overview(CONFIG, FILES, AI, {}, {}, now=NOW, karten=karten)
    k = data["details"]["accounting"]["karten"]
    assert (k["faellig"], k["gesamt"], k["naechste"]) == (0, 1, 1)
    assert k["liste"][0]["id"] == ki_id and k["liste"][0]["faellig"] is False
    assert data["daten"]["semester"][0]["module"][0]["karten"] == 0

    karten["imported"]["x" * 16] = {"kurs": "Accounting", "front": "<i>Soll</i>", "back": "links",
                                    "quelle": "Anki · BWL", "created": NOW}
    data = studyhub.overview(CONFIG, FILES, AI, {}, {}, now=NOW + 2 * DAY, karten=karten)
    liste = data["details"]["accounting"]["karten"]["liste"]
    assert [(c["neu"], c["faellig"], c["thema"]) for c in liste] == [(False, True, 1), (True, True, 0)]
    assert liste[1]["frage"] == "&lt;i&gt;Soll&lt;/i&gt;" and liste[1]["lernplan"] is None


def test_review_endpoint_saves_state():
    core.MIRROR_DIR.joinpath("Accounting").mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    cid = cards.card_id("Accounting/x.pdf", "Frage")
    r = client.post("/api/cards/review", headers=AUTH, json={"id": cid, "bewertung": "gewusst"}).json()
    assert r["inTagen"] == 1 and cards.load()["reviews"][cid]["reps"] == 1
    bad = {"id": "../x", "bewertung": "gewusst"}
    assert client.post("/api/cards/review", headers=AUTH, json=bad).status_code == 400
    assert client.post("/api/cards/review", headers=AUTH, json={"id": cid, "bewertung": "egal"}).status_code == 422
    assert client.post("/api/cards/review", json={"id": cid, "bewertung": "gewusst"}).status_code == 403


def test_text_import_and_export_round_trip():
    text = ("#separator:tab\n#html:true\n#tags column:3\n"
            "Was ist <b>EK</b>?\tEigenkapital<br>(Passiva)\tbwl\n"
            "\n"
            "nur eine Spalte\n"
            "Bilanz &amp; GuV\t[sound:x.mp3]Zwei Rechnungen\n")
    parsed = cards.parse_text(text)
    assert parsed == [("Was ist EK?", "Eigenkapital\n(Passiva)"), ("Bilanz & GuV", "Zwei Rechnungen")]
    assert cards.parse_text("Frage;Antwort") == [("Frage", "Antwort")]
    with pytest.raises(cards.CardError):
        cards.parse_text("keine Karten hier")
    exported = cards.to_text(parsed)
    assert exported.startswith("#separator:tab\n#html:true\n")
    assert "Eigenkapital<br>(Passiva)" in exported and "Bilanz &amp; GuV" in exported
    assert cards.parse_text(exported) == parsed

    assert cards.add_cards("Accounting", parsed + [("Was ist EK?", "doppelt")], "Textdatei")["neu"] == 2
    assert [c["front"] for c in cards.course_cards("Accounting")] == ["Was ist EK?", "Bilanz & GuV"]


def test_exam_dates():
    studyhub.set_exam("Accounting", "2027-02-10")
    with pytest.raises(ValueError):
        studyhub.set_exam("Accounting", "10.02.2027")
    now = time.mktime(time.strptime("2027-01-31", "%Y-%m-%d"))
    data = studyhub.overview(CONFIG, FILES, AI, {}, {}, now=now, exams=studyhub.load_exams())
    assert data["daten"]["naechsteKlausur"] == {"modulId": "accounting", "tage": 10}
    assert data["daten"]["semester"][0]["module"][0]["klausur"] == {"datum": "2027-02-10", "tage": 10}
    later = time.mktime(time.strptime("2027-03-01", "%Y-%m-%d"))  # vorbei: nicht mehr anzeigen
    assert studyhub.overview(CONFIG, FILES, AI, {}, {}, now=later, exams=studyhub.load_exams())["daten"][
        "naechsteKlausur"] is None
    studyhub.set_exam("Accounting", None)
    assert studyhub.load_exams() == {}


def test_exam_endpoint():
    path = core.MIRROR_DIR / "Accounting/Vorlesung/01.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    client = TestClient(app)
    assert client.patch("/api/studyhub/klausur", headers=AUTH, json={"kurs": "Accounting", "datum": "2027-02-10"}
                        ).status_code == 200
    assert studyhub.load_exams() == {"Accounting": "2027-02-10"}
    assert client.patch("/api/studyhub/klausur", headers=AUTH, json={"kurs": "Gibt es nicht", "datum": "2027-02-10"}
                        ).status_code == 404
    assert client.patch("/api/studyhub/klausur", headers=AUTH, json={"kurs": "Accounting", "datum": "morgen"}
                        ).status_code == 400


class FakeAnki:
    """Ersetzt AnkiConnect: Decks mit Notizen, merkt sich hinzugefügte Notizen."""

    def __init__(self, models=("Basic",)):
        self.models = list(models)
        self.added, self.calls = [], []
        self.notes = {1: {"Front": "Was ist <b>EK</b>?", "Back": "Eigenkapital"},
                      2: {"Text": "nur ein Feld"}}

    def __call__(self, url, json, timeout):
        import integrations
        assert url == integrations.ANKI_URL and json["version"] == 6
        action, params = json["action"], json["params"]
        self.calls.append(action)
        result = {
            "deckNames": lambda: ["BWL", "Default"],
            "findNotes": lambda: [1, 2] if params["query"] == 'deck:"BWL"' else [],
            "notesInfo": lambda: [{"noteId": n, "modelName": "Basic", "tags": [], "cards": [], "mod": 0,
                                   "fields": {k: {"value": v, "order": i} for i, (k, v) in
                                              enumerate(self.notes[n].items())}} for n in params["notes"]],
            "modelNames": lambda: self.models,
            "modelFieldNames": lambda: ["Vorderseite", "Rückseite"] if params["modelName"] == "Einfach"
            else ["Front", "Back"],
            "createDeck": lambda: 99,
            "canAddNotes": lambda: [n["fields"][list(n["fields"])[0]] != "Bilanz" for n in params["notes"]],
            "addNotes": lambda: self.added.extend(params["notes"]) or [1] * len(params["notes"]),
        }[action]()
        return SimpleResponse({"result": result, "error": None})


class SimpleResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


@pytest.fixture
def course():
    path = core.MIRROR_DIR / "Accounting/Vorlesung/01.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return TestClient(app)


def test_anki_import_and_export(course, monkeypatch):
    import ai
    import integrations
    fake = FakeAnki(models=("Cloze", "Einfach"))
    monkeypatch.setattr(integrations.httpx, "post", fake)
    assert course.get("/api/anki/status", headers=AUTH).json() == {"ready": True, "decks": ["BWL", "Default"]}

    r = course.post("/api/anki/import", headers=AUTH, json={"kurs": "Accounting", "deck": "BWL"}).json()
    assert r["neu"] == 1  # Notiz mit nur einem Feld zählt nicht
    assert cards.course_cards("Accounting")[0] | {"id": 0, "created": 0, "nr": 0} == {
        "id": 0, "created": 0, "nr": 0, "kurs": "Accounting", "front": "Was ist EK?", "back": "Eigenkapital",
        "quelle": "Anki · BWL"}
    assert course.post("/api/anki/import", headers=AUTH, json={"kurs": "Accounting", "deck": "Default"}
                       ).status_code == 400

    entry = ai.load_entry(core.MIRROR_DIR / "Accounting/Vorlesung/01.txt")
    entry["flashcards"] = {"output": {"cards": [{"front": "Bilanz", "back": "Aktiva = Passiva"},
                                                {"front": "GuV", "back": "Erfolg\nrechnung"}]},
                           "created": NOW}
    ai.save_entry(entry, "Accounting/Vorlesung/01.txt")
    r = course.post("/api/anki/export", headers=AUTH, json={"kurs": "Accounting"}).json()
    assert r == {"deck": "StudyHub::Accounting", "neu": 2, "vorhanden": 1}  # „Bilanz“ kennt Anki schon
    assert fake.added[0] == {"deckName": "StudyHub::Accounting", "modelName": "Einfach", "tags": ["StudyHub"],
                             "fields": {"Vorderseite": "GuV", "Rückseite": "Erfolg<br>rechnung"}}

    text = course.get("/api/cards/export", params={"kurs": "Accounting"}, headers=AUTH)
    assert text.headers["content-type"].startswith("text/plain")
    assert cards.parse_text(text.text) == [("Bilanz", "Aktiva = Passiva"), ("GuV", "Erfolg\nrechnung"),
                                           ("Was ist EK?", "Eigenkapital")]
    assert course.get("/api/cards/export", params={"kurs": "Fremd"}, headers=AUTH).status_code == 404


def test_anki_not_running(course, monkeypatch):
    import integrations

    def offline(*args, **kwargs):
        raise integrations.httpx.ConnectError("refused")

    monkeypatch.setattr(integrations.httpx, "post", offline)
    status = course.get("/api/anki/status", headers=AUTH).json()
    assert status["ready"] is False and "2055492159" in status["hinweis"]
    r = course.post("/api/anki/import", headers=AUTH, json={"kurs": "Accounting", "deck": "BWL"})
    assert r.status_code == 400 and "Anki nicht erreichbar" in r.json()["detail"]


def test_text_import_endpoint(course):
    data = b"#separator:tab\nFrage 1\tAntwort 1\nFrage 2\tAntwort 2\n"
    r = course.post("/api/cards/import", headers=AUTH, data={"kurs": "Accounting"},
                    files={"file": ("deck.txt", data, "text/plain")})
    assert r.json() == {"neu": 2, "doppelt": 0, "gekuerzt": False}
    assert cards.course_cards("Accounting")[1]["quelle"] == "Textdatei · deck.txt"
    bad = course.post("/api/cards/import", headers=AUTH, data={"kurs": "Accounting"},
                      files={"file": ("x.txt", b"nichts", "text/plain")})
    assert bad.status_code == 400


def test_export_file_lands_in_downloads(course, monkeypatch, tmp_path):
    import app as app_module
    opened = []
    monkeypatch.setattr(app_module, "DOWNLOADS", tmp_path / "Downloads")
    monkeypatch.setattr(app_module.subprocess, "run", lambda args, check=False: opened.append(args))
    assert course.post("/api/cards/export", headers=AUTH, json={"kurs": "Accounting"}).status_code == 400
    cards.add_cards("Accounting", [("F", "A")], "Textdatei")
    r = course.post("/api/cards/export", headers=AUTH, json={"kurs": "Accounting"}).json()
    assert r == {"ok": True, "datei": "Karten Accounting.txt", "karten": 1}
    assert course.post("/api/cards/export", headers=AUTH, json={"kurs": "Accounting"}).json()["datei"] == \
        "Karten Accounting (2).txt"
    assert (tmp_path / "Downloads/Karten Accounting.txt").read_text(encoding="utf-8").endswith("F\tA\n")
    assert opened[0][:2] == ["open", "-R"]
