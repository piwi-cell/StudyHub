"""StudyHub-Daten: Format wie die Mock-Daten, Maskierung, Semester, Lernplan, Endpunkte."""

import time

import pytest
from fastapi.testclient import TestClient

import core
import studyhub
from app import app

AUTH = {"x-app-token": "test-token"}
NOW = time.time()


def _file(path: str, age_days: float = 10, summary: bool = False) -> dict:
    course, *middle, name = path.split("/")
    return {"path": path, "name": name, "course": course, "folder": "/".join(middle), "ext": name.rsplit(".", 1)[-1],
            "size": 1000, "mtime": NOW - age_days * 86400, "ai": {"summary": summary, "flashcards": False, "qa": 0}}


CONFIG = {
    "uni_id": "mmuster",
    "courses": {
        "ACC 300 Financial Accounting [V] (HWS 2026)": {"name": "Accounting", "sync": True, "group": False},
        "ACC 300 Financial Accounting [1. PG] (HWS 2026)": {"name": "Accounting/Übungsgruppe", "sync": True,
                                                            "group": True},
        "MAT 100 Mathe [V] (FSS 2026)": {"name": "Mathe", "sync": True, "group": False},
    },
}
FILES = [
    _file("Accounting/Vorlesung/01 Bilanz.pdf", age_days=1),
    _file("Accounting/Übung/Blatt 1.pdf"),
    _file("Accounting/Tutorium/Tut 1.pdf"),
    _file("Mathe/Skript <img src=x onerror=alert(1)>.pdf", summary=True),
]
AI = {
    "Accounting/Vorlesung/01 Bilanz.pdf": {
        "thema": {"output": {"titel": "Die Bilanz", "kernidee": "Aktiva = **Passiva**", "einfacher": "Wie eine Waage.",
                             "formeln": [{"name": "Grundgleichung", "text": "A = EK + FK_{lang} + x^2"}],
                             "falle": "<script>x</script>", "seite": 3}},
        "flashcards": {"output": {"cards": [{"front": "Was ist <b>Aktiva</b>?", "back": "Vermögen"}]}},
    },
    "Mathe/Skript <img src=x onerror=alert(1)>.pdf": {
        "summary": {"output": "## Worum es geht\nAbleitungen.\n## Kernaussagen\n- Regel 1\n"
                              "## Wichtige Begriffe\n- **Ableitung**: Steigung\n## Prüfungsrelevant\n- Kettenregel"},
    },
}


def test_overview_matches_mock_format():
    data = studyhub.overview(CONFIG, FILES, AI, {"Accounting": {"questions": 6, "wrong": 2}},
                             {"Accounting/Übung/Blatt 1.pdf": {"status": "erledigt"}}, now=NOW)
    daten, details = data["daten"], data["details"]
    assert daten["nutzer"] == {"vorname": "mmuster", "initialen": "MM"}
    assert daten["naechsteKlausur"] is None
    semester = [(s["name"], s["status"]) for s in daten["semester"]]
    assert semester == [("HWS 2026", "aktuell"), ("FSS 2026", "abgeschlossen")]
    accounting = daten["semester"][0]["module"][0]
    assert accounting["id"] == "accounting" and accounting["fortschritt"] == 33 and accounting["neu"] == 1
    assert accounting["zeile"] == "1 von 3 Einträgen" and accounting["info"] == "1 Karten fällig"

    lp = details["accounting"]["lernplan"]
    assert [k["titel"] for k in lp["kapitel"]] == ["Vorlesung"]
    assert [(b["art"], b["titel"]) for b in lp["bereiche"]] == [("Tutorium", "Tutorium"), ("Übung", "Übung")]
    assert lp["basis"] == {"erledigt": 1, "gesamt": 3, "nochmal": 0, "offen": 2}

    thema = details["accounting"]["themen"][0]
    assert thema["titel"] == "Die Bilanz" and thema["quelle"] == "01 Bilanz.pdf, S. 3" and thema["strukturiert"]
    assert thema["kernidee"] == "Aktiva = <b>Passiva</b>"
    assert thema["formeln"][0]["text"] == "A = EK + FK<sub>lang</sub> + x<sup>2</sup>"
    assert thema["falle"] == "&lt;script&gt;x&lt;/script&gt;"
    karte = details["accounting"]["karten"]["liste"][0]
    assert karte["frage"] == "Was ist &lt;b&gt;Aktiva&lt;/b&gt;?"
    assert karte["thema"] == 1 and karte["lernplan"] == karte["pfad"]
    assert details["accounting"]["tutor"]["fragen"] == 6
    assert {c["tab"] for c in daten["heuteDran"]} == {"karteikarten", "lernplan", "dokumente"}


def test_long_topic_text_keeps_paragraphs_and_bullets():
    text = "Erster **Absatz**\nzweite Zeile\n\n- Punkt <b>1</b>\n* Punkt 2\n\n\nLetzter Absatz"
    assert studyhub.paragraphs(text) == ("Erster <b>Absatz</b><br>zweite Zeile<br><br>"
                                         "• Punkt &lt;b&gt;1&lt;/b&gt;<br>• Punkt 2<br><br>Letzter Absatz")
    assert studyhub.paragraphs("  Ein Satz.  ") == studyhub.inline("Ein Satz.")


def test_markdown_summary_fallback_and_escaping():
    data = studyhub.overview(CONFIG, FILES, AI, {}, {}, now=NOW)
    mathe = data["details"]["mathe"]
    thema = mathe["themen"][0]
    assert "<img" not in thema["titel"] and "&lt;img" in thema["titel"]
    assert thema["kernidee"].startswith("Ableitungen.") and "• Regel 1" in thema["kernidee"]
    assert thema["formeln"] == [{"name": "Ableitung", "text": "Steigung"}] and thema["falle"] == "Kettenregel"
    assert mathe["glossar"] == [{"begriff": "Ableitung", "text": "Steigung"}]
    assert mathe["dokumente"][0]["gruppe"] == "Allgemein" and mathe["dokumente"][0]["dateien"][0]["zusammengefasst"]


def test_courses_without_semester_and_slugs():
    config = {"uni_id": "", "courses": {"Kurs ohne Semester": {"name": "Übung & Co", "sync": True}}}
    data = studyhub.overview(config, [], {}, {}, {}, now=NOW)
    semester = data["daten"]["semester"]
    assert semester[0]["name"] == "Meine Kurse" and semester[0]["status"] == "aktuell"
    module = semester[0]["module"][0]
    assert module["id"] == "ubung-co" and module["fortschritt"] is None and module["info"] == "Noch keine Dateien"


def test_lernplan_state_validation():
    assert studyhub.set_state("a.pdf", "nochmal", "Folie 3")["status"] == "nochmal"
    assert studyhub.load_state()["a.pdf"] == {"status": "nochmal", "notiz": "Folie 3"}
    with pytest.raises(ValueError):
        studyhub.set_state("a.pdf", "fertig")


def test_studyhub_endpoints(monkeypatch):
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}})
    path = core.MIRROR_DIR / "Statistik/Vorlesung/07 Tests.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Hypothesentests " * 50, encoding="utf-8")
    client = TestClient(app)
    assert client.get("/api/studyhub").status_code == 403
    data = client.get("/api/studyhub", headers=AUTH).json()
    assert data["daten"]["semester"][0]["module"][0]["id"] == "statistik" and data["sync"]["demo"] is True
    body = {"pfad": "Statistik/Vorlesung/07 Tests.txt", "status": "erledigt"}
    assert client.patch("/api/studyhub/lernplan", json=body, headers=AUTH).json()["status"] == "erledigt"
    assert client.get("/api/studyhub", headers=AUTH).json()["daten"]["semester"][0]["module"][0]["fortschritt"] == 100
    assert client.patch("/api/studyhub/lernplan", json={"pfad": "../config.json", "status": "erledigt"},
                        headers=AUTH).status_code == 404
    assert client.patch("/api/studyhub/lernplan", json={**body, "status": "kaputt"}, headers=AUTH).status_code == 400


def test_hide_file_only_in_app(tmp_path):
    from fastapi.testclient import TestClient

    import core
    from app import app
    auth = {"x-app-token": "test-token"}
    core.save_config({"uni_id": "demo", "target_dir": str(tmp_path / "Ziel"),
                      "courses": {"MAT 100 Analysis [V] (HWS 2026)": {"name": "Analysis", "sync": True}}})
    for name in ("01 Grenzwerte.pdf", "02 Reihen.pdf"):
        path = core.MIRROR_DIR / "Analysis" / "Vorlesung" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4")
    client = TestClient(app)
    pfad = "Analysis/Vorlesung/02 Reihen.pdf"
    assert client.patch("/api/studyhub/ausblenden", headers=auth, json={"pfad": pfad}).json()["ausgeblendet"] is True

    detail = client.get("/api/studyhub", headers=auth).json()["details"]["analysis"]
    namen = [f["name"] for g in detail["dokumente"] for f in g["dateien"]]
    assert namen == ["01 Grenzwerte.pdf"]  # nicht mehr in Dokumente und Lernplan
    assert [e["titel"] for k in detail["lernplan"]["kapitel"] for e in k["eintraege"]] == ["01 Grenzwerte"]
    assert detail["ausgeblendet"] == [{"pfad": pfad, "name": "02 Reihen.pdf", "ordner": "Vorlesung"}]
    assert pfad not in {f["path"] for f in client.get("/api/files", headers=auth).json()["files"]}
    assert (core.MIRROR_DIR / pfad).exists()  # Datei selbst bleibt

    client.patch("/api/studyhub/ausblenden", headers=auth, json={"pfad": pfad, "ausgeblendet": False})
    detail = client.get("/api/studyhub", headers=auth).json()["details"]["analysis"]
    assert len([f for g in detail["dokumente"] for f in g["dateien"]]) == 2 and detail["ausgeblendet"] == []
    assert client.patch("/api/studyhub/ausblenden", headers=auth, json={"pfad": "../x.pdf"}).status_code == 404


def test_same_semester_with_different_spellings():
    assert studyhub.semester_of("ACC 300 Intro [V] (WT 2026)") == studyhub.semester_of("MAN 301 X [V] (HWS 2026)")
    assert studyhub.semester_of("Kurs (WS 26)")[0] == "HWS 2026"
    assert studyhub.semester_of("Kurs (SS 2026)")[0] == "FSS 2026"
    config = {"uni_id": "m", "courses": {
        "ACC 300 Introduction to Financial Accounting [V] (WT 2026)": {"name": "Intro", "sync": True},
        "MAN 301 Marketing [V] (HWS 2026)": {"name": "Marketing", "sync": True},
        "MAT 100 Mathe [V] (FSS 2026)": {"name": "Mathe", "sync": True},
    }}
    semester = studyhub.overview(config, [], {}, {}, {}, now=NOW)["daten"]["semester"]
    assert [(s["name"], s["status"], len(s["module"])) for s in semester] == [
        ("HWS 2026", "aktuell", 2), ("FSS 2026", "abgeschlossen", 1)]
