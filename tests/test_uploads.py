"""Eigene Dateien hochladen: Ablage, Grenzen (Kurs, Dateityp, Name, Größe), Sichtbarkeit in der App."""

import pytest
from fastapi.testclient import TestClient

import core
import uploads
from app import app

AUTH = {"x-app-token": "test-token"}


@pytest.fixture
def client(tmp_path):
    target = tmp_path / "Ziel"
    core.save_config({"uni_id": "demo", "target_dir": str(target),
                      "courses": {"MAT 100 Analysis [V] (HWS 2026)": {"name": "Analysis", "sync": True}}})
    return TestClient(app), target


def _post(client, files, course="Analysis", headers=AUTH):
    return client.post("/api/upload", data={"course": course}, files=[("files", f) for f in files], headers=headers)


def test_upload_lands_in_own_folder_and_target(client):
    http, target = client
    response = _post(http, [("Mitschrift.pdf", b"%PDF-1.4 meine Notizen", "application/pdf")])
    assert response.status_code == 200
    assert response.json() == {"saved": ["Analysis/Eigene Dateien/Mitschrift.pdf"], "errors": []}
    assert (core.MIRROR_DIR / "Analysis/Eigene Dateien/Mitschrift.pdf").read_bytes() == b"%PDF-1.4 meine Notizen"
    assert (target / "Analysis/Eigene Dateien/Mitschrift.pdf").exists()  # gleich in den Zielordner kopiert
    files = http.get("/api/files", headers=AUTH).json()["files"]
    assert files[0]["course"] == "Analysis" and files[0]["folder"] == "Eigene Dateien"


def test_upload_without_target_dir_stays_in_mirror(tmp_path, monkeypatch):
    """Vor der Wahl des Zielordners nichts kopieren: Path("") wäre das Arbeitsverzeichnis der App."""
    monkeypatch.chdir(tmp_path)
    core.save_config({"uni_id": "demo", "target_dir": "",
                      "courses": {"MAT 100 Analysis [V] (HWS 2026)": {"name": "Analysis", "sync": True}}})
    response = TestClient(app).post("/api/summaries", json={"kurs": "Analysis", "titel": "Notiz", "text": "Hallo"},
                                    headers=AUTH)
    assert response.status_code == 200
    assert (core.MIRROR_DIR / "Analysis/Eigene Zusammenfassungen/Notiz.md").exists()
    assert not any(tmp_path.iterdir())
    assert core.load_state()["published"] == {}  # nach der Wahl des Zielordners wird alles kopiert


def test_duplicates_are_never_overwritten(client):
    http, _ = client
    _post(http, [("Blatt.pdf", b"eins", "application/pdf")])
    second = _post(http, [("Blatt.pdf", b"zwei", "application/pdf")]).json()["saved"]
    assert second == ["Analysis/Eigene Dateien/Blatt (2).pdf"]
    assert (core.MIRROR_DIR / "Analysis/Eigene Dateien/Blatt.pdf").read_bytes() == b"eins"


def test_rejects_unknown_course_and_needs_token(client):
    http, _ = client
    assert _post(http, [("a.pdf", b"x", "application/pdf")], headers={}).status_code == 403
    response = _post(http, [("a.pdf", b"x", "application/pdf")], course="../../etc")
    assert response.status_code == 400 and "Unbekannter Kurs" in response.json()["detail"]
    assert not any(core.APP_DIR.rglob("a.pdf"))


@pytest.mark.parametrize("name", ["installer.command", "skript.sh", "Programm.app", "makro.docm", ".versteckt.pdf"])
def test_rejects_executable_or_hidden_files(client, name):
    http, _ = client
    response = _post(http, [(name, b"echo hallo", "application/octet-stream")])
    assert response.status_code == 400
    assert not (core.MIRROR_DIR / "Analysis/Eigene Dateien" / name).exists()


def test_path_in_filename_is_stripped(client):
    http, _ = client
    saved = _post(http, [("../../../config.pdf", b"x", "application/pdf")]).json()["saved"]
    assert saved == ["Analysis/Eigene Dateien/config.pdf"]


def test_partial_success_and_limits(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(uploads, "MAX_BYTES", 10)
    response = _post(http, [("klein.txt", b"ok", "text/plain"), ("gross.pdf", b"x" * 50, "application/pdf"),
                            ("leer.pdf", b"", "application/pdf")]).json()
    assert response["saved"] == ["Analysis/Eigene Dateien/klein.txt"]
    assert len(response["errors"]) == 2 and any("100 MB" in e for e in response["errors"])
    assert not list((core.MIRROR_DIR / "Analysis/Eigene Dateien").glob(".*"))  # keine Reste


def test_own_summary_written_and_uploaded_shows_as_topic(client):
    http, target = client
    _post(http, [("Folie.pdf", b"%PDF-1.4", "application/pdf")])  # Material, damit der Kurs Dateien hat
    text = "# Kapitel 3\n- **Barwert**: heutiger Wert\n<script>x</script>"
    r = http.post("/api/summaries", headers=AUTH, json={"kurs": "Analysis", "titel": "Renten", "text": text})
    assert r.json() == {"ok": True, "pfad": "Analysis/Eigene Zusammenfassungen/Renten.md"}
    assert (target / "Analysis/Eigene Zusammenfassungen/Renten.md").read_text(encoding="utf-8") == text
    upload = http.post("/api/upload", data={"course": "Analysis", "art": "zusammenfassung"}, headers=AUTH,
                       files=[("files", ("Notizen.txt", b"Meine Notizen", "text/plain"))])
    assert upload.json()["saved"] == ["Analysis/Eigene Zusammenfassungen/Notizen.txt"]

    details = http.get("/api/studyhub", headers=AUTH).json()["details"]["analysis"]
    eigene = {t["titel"]: t for t in details["themen"] if t.get("eigene")}
    assert set(eigene) == {"Renten", "Notizen"}
    assert eigene["Renten"]["kernidee"] == ("<b>Kapitel 3</b><br>• <b>Barwert</b>: heutiger Wert<br>"
                                            "&lt;script&gt;x&lt;/script&gt;")
    assert eigene["Notizen"]["quelle"] == "Meine Zusammenfassung · Notizen.txt"
    # Lernhilfen, keine Lernplan-Einträge
    eintraege = [e["id"] for k in details["lernplan"]["kapitel"] for e in k["eintraege"]]
    assert eintraege == ["Analysis/Eigene Dateien/Folie.pdf"]

    for bad in ({"kurs": "Analysis", "titel": " ", "text": "x"}, {"kurs": "Analysis", "titel": "T", "text": " "},
                {"kurs": "Gibt es nicht", "titel": "T", "text": "x"}):
        assert http.post("/api/summaries", headers=AUTH, json=bad).status_code == 400
    # Pfadteile im Titel bleiben im Ordner
    sneaky = http.post("/api/summaries", headers=AUTH, json={"kurs": "Analysis", "titel": "../x", "text": "x"})
    assert sneaky.json()["pfad"] == "Analysis/Eigene Zusammenfassungen/x.md"
    assert http.post("/api/upload", data={"course": "Analysis", "art": "system"}, headers=AUTH,
                     files=[("files", ("a.txt", b"x", "text/plain"))]).status_code == 422


def test_upload_by_path_from_native_dialog(client, tmp_path):
    http, target = client
    source = tmp_path / "Downloads" / "Skript Kapitel 2.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-1.4 Kapitel 2")
    (tmp_path / "Downloads" / "start.command").write_text("echo", encoding="utf-8")
    body = {"course": "Analysis", "paths": [str(source), str(tmp_path / "fehlt.pdf"),
                                            str(tmp_path / "Downloads" / "start.command")]}
    r = http.post("/api/upload/paths", json=body, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["saved"] == ["Analysis/Eigene Dateien/Skript Kapitel 2.pdf"]
    assert len(r.json()["errors"]) == 2 and "fehlt.pdf: nicht gefunden" in r.json()["errors"]
    assert (target / "Analysis/Eigene Dateien/Skript Kapitel 2.pdf").read_bytes() == b"%PDF-1.4 Kapitel 2"
    assert source.exists()  # Original bleibt, wo es ist
    nothing = http.post("/api/upload/paths", json={"course": "Analysis", "paths": []}, headers=AUTH)
    assert nothing.status_code == 400
    assert http.post("/api/upload/paths", json=body).status_code == 403
