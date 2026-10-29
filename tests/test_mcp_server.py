"""MCP-Server für Claude Desktop: Werkzeuge, Pfadschutz, Speichern in den KI-Cache, StudyHub, stdio."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError

import ai
import core
import integrations
import mcp_server
import tutor
from app import app

ROOT = Path(__file__).resolve().parent.parent
HOME = core.APP_DIR  # temporärer Datenordner aus conftest.py
AUTH = {"x-app-token": "test-token"}
PATH = "Statistik I/Vorlesung/07 Hypothesentests.txt"
THEMA = {
    "path": PATH, "titel": "Hypothesentests", "kernidee": "Man prüft eine Annahme mit Daten.",
    "einfacher": "Wie ein Gericht: unschuldig bis zum Beweis.",
    "formeln": [{"name": "Teststatistik", "text": "z = (x̄ − μ_0) / (σ/√n)"}], "falle": "p-Wert ≠ P(H0)", "seite": 2,
}


def _mirror(path: str = PATH, text: str = "Nullhypothese H0 und Alternative H1. " * 20) -> None:
    file = core.MIRROR_DIR / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


def _call(name: str, arguments: dict) -> dict:
    """Ruft ein Werkzeug über die MCP-Schicht auf (mit Prüfung der Argumente); ToolError bei Fehlern."""
    result = asyncio.run(mcp_server.mcp.call_tool(name, arguments))
    return json.loads(result.content[0].text)


def test_tools_are_listed_without_delete_or_send():
    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert set(tools) == {"list_courses", "list_files", "read_file", "view_pages", "read_ai_results",
                          "studyhub_overview", "save_thema", "save_summary", "save_flashcards",
                          "save_tutor_questions"}
    writers = {name for name, t in tools.items() if not t.annotations.read_only_hint}
    assert writers == {"save_thema", "save_summary", "save_flashcards", "save_tutor_questions"}
    assert all(not t.annotations.destructive_hint for t in tools.values())
    assert tools["save_thema"].input_schema["properties"]["formeln"]["maxItems"] == 5


def test_lerncoach_prompt_matches_studyhub_button():
    prompts = asyncio.run(mcp_server.mcp.list_prompts())
    assert [p.name for p in prompts] == ["lerncoach"] and prompts[0].arguments[0].required is False
    text = asyncio.run(mcp_server.mcp.get_prompt("lerncoach", {"kurs": " Statistik I "})).messages[0].content.text
    assert text == integrations.coach_prompt("Statistik I")
    assert asyncio.run(mcp_server.mcp.get_prompt("lerncoach", {})).messages[0].content.text == \
        integrations.coach_prompt()


def test_list_and_read_files(monkeypatch):
    _mirror()
    _mirror("Mathe/Skript.txt", "Ableitungen")
    _mirror("Mathe/.versteckt.txt", "geheim")
    assert [c["kurs"] for c in mcp_server.list_courses()["kurse"]] == ["Mathe", "Statistik I"]
    result = mcp_server.list_files(course="statistik i")
    assert result["gesamt"] == 1 and result["dateien"][0]["path"] == PATH
    assert result["dateien"][0]["ai"] == {"summary": False, "flashcards": False, "qa": 0, "thema": False}
    assert mcp_server.list_files(limit=1) | {"dateien": None} == {"dateien": None, "gesamt": 2, "gekuerzt": True}
    assert mcp_server.list_files(query="SKRIPT")["dateien"][0]["path"] == "Mathe/Skript.txt"

    text = mcp_server.read_file(PATH)
    assert text["text"].startswith("[Seite 1]\nNullhypothese") and text["weiter_ab_seite"] is None

    monkeypatch.setattr(ai, "extract_pages", lambda _path: ["eins " * 10, "", "drei " * 10])
    monkeypatch.setattr(mcp_server, "MAX_CHARS", 60)
    first = mcp_server.read_file(PATH)
    assert first["seiten"] == 3 and first["weiter_ab_seite"] == 3 and "[Seite 3]" not in first["text"]
    assert mcp_server.read_file(PATH, start_page=3)["text"].startswith("[Seite 3]")


@pytest.mark.parametrize("bad", ["../config.json", "/etc/passwd", "Mathe", "Mathe/fehlt.txt", "Mathe/../../KI"])
def test_paths_outside_mirror_are_refused(bad):
    _mirror("Mathe/Skript.txt", "x")
    (HOME / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ToolError, match="nicht gefunden"):
        mcp_server.read_file(bad)
    with pytest.raises(ToolError):
        _call("save_thema", {**THEMA, "path": bad})


def test_save_thema_appears_in_studyhub():
    _mirror()
    core.save_config({"uni_id": "demo", "target_dir": "", "courses": {}})
    assert _call("save_thema", THEMA)["gespeichert"] is True

    entry = ai.load_entry(core.MIRROR_DIR / PATH)
    assert entry["path"] == PATH and entry["thema"]["provider"] == "claude-desktop"
    assert entry["thema"]["output"] == {k: v for k, v in THEMA.items() if k != "path"}
    assert set(entry["thema"]["output"]) == set(ai.THEMA_SCHEMA["properties"])

    # Die heutige StudyHub-Oberfläche liest die Markdown-Zusammenfassung aus /api/learn
    learn = TestClient(app).get("/api/learn", headers=AUTH).json()["items"][0]
    assert learn["path"] == PATH and learn["summary"]["from_thema"] is True
    markdown = learn["summary"]["output"]
    assert markdown.startswith("## Worum es geht\nMan prüft eine Annahme mit Daten.")
    assert "- **Teststatistik**: z = (x̄ − μ_0) / (σ/√n)" in markdown and "Klausurfalle: p-Wert" in markdown

    data = TestClient(app).get("/api/studyhub", headers=AUTH).json()
    thema = data["details"]["statistik-i"]["themen"][0]
    assert thema["titel"] == "Hypothesentests" and thema["strukturiert"] and thema["quelle"].endswith("S. 2")
    assert thema["formeln"][0]["text"] == "z = (x̄ − μ<sub>0</sub>) / (σ/√n)"
    overview = mcp_server.studyhub_overview("Statistik I")["kurse"][0]
    assert overview["lernthemen"][0]["titel"] == "Hypothesentests" and overview["ohne_lernthema"] == []

    # Vorhandenes Ergebnis nur mit overwrite ersetzen
    with pytest.raises(ToolError, match="overwrite"):
        _call("save_thema", {**THEMA, "titel": "Neu"})
    assert _call("save_thema", {**THEMA, "titel": "Neu", "overwrite": True})["gespeichert"]
    assert mcp_server.read_ai_results(PATH)["thema"]["output"]["titel"] == "Neu"


def test_save_thema_keeps_existing_summary():
    _mirror()
    entry = ai.load_entry(core.MIRROR_DIR / PATH)
    entry["summary"] = {"provider": "gemma", "model": "gemma3:4b", "output": "## Worum es geht\nEigene", "created": 1}
    ai.save_entry(entry, PATH)
    assert _call("save_thema", THEMA)["zusammenfassung"] == "vorhandene Zusammenfassung behalten"
    assert ai.load_entry(core.MIRROR_DIR / PATH)["summary"]["output"] == "## Worum es geht\nEigene"


def test_descriptions_name_nested_fields_and_limits():
    """Claude sieht verschachtelte Felder nur über $defs: Beschreibung nennt sie samt Grenzen und Beispiel."""
    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    thema, karten, fragen = (tools[n].description for n in ("save_thema", "save_flashcards", "save_tutor_questions"))
    assert '{"name", "text"}' in thema and "0–5" in thema and "≤ 3000" in thema and "save_summary" in thema
    assert '{"front", "back"}' in karten and '"front": "Was ist ein Mindestpreis?"' in karten
    assert '{"question", "answer", "page"}' in fragen
    assert "## Worum es geht" in tools["save_summary"].description
    defs = tools["save_thema"].input_schema["$defs"]["Formel"]["properties"]
    assert defs["name"]["description"] and defs["text"]["description"]


def test_save_summary_shows_in_studyhub_and_survives_save_thema():
    _mirror()
    markdown = ("## Worum es geht\nMindest- und Höchstpreise.\n\n## Kernaussagen\n- Mindestpreis über Gleichgewicht\n\n"
                "## Wichtige Begriffe\n- **Mindestpreis**: darf nicht unterschritten werden\n\n"
                "## Prüfungsrelevant\n- Angebotsüberschuss erklären\n\n## Beispiel\nAgrarmarkt")
    assert _call("save_summary", {"path": PATH, "markdown": markdown})["gespeichert"]
    thema = TestClient(app).get("/api/studyhub", headers=AUTH).json()["details"]["statistik-i"]["themen"][0]
    assert "Mindest- und Höchstpreise." in thema["kernidee"] and thema["formeln"][0]["name"] == "Mindestpreis"
    with pytest.raises(ToolError, match="overwrite"):
        _call("save_summary", {"path": PATH, "markdown": "## Worum es geht\nNeu"})
    assert _call("save_thema", THEMA)["zusammenfassung"] == "vorhandene Zusammenfassung behalten"
    assert ai.load_entry(core.MIRROR_DIR / PATH)["summary"]["output"] == markdown  # nicht vom Lernthema ersetzt
    for bad in ("", "x" * (mcp_server.MAX_SUMMARY + 1)):
        with pytest.raises(ToolError):
            _call("save_summary", {"path": PATH, "markdown": bad, "overwrite": True})


def test_save_summary_replaces_one_derived_from_thema_without_overwrite():
    _mirror()
    assert _call("save_thema", THEMA)["zusammenfassung"] == "aus dem Lernthema mitgespeichert"
    assert _call("save_summary", {"path": PATH, "markdown": "## Worum es geht\nAusführlich"})["gespeichert"]
    summary = ai.load_entry(core.MIRROR_DIR / PATH)["summary"]
    assert summary["output"] == "## Worum es geht\nAusführlich" and not summary.get("from_thema")


def test_save_thema_rejects_wrong_fields():
    _mirror()
    too_many = [{"name": f"F{i}", "text": "a = b"} for i in range(6)]
    for bad in ({**THEMA, "formeln": too_many}, {**THEMA, "formeln": [{"name": "x", "text": "y", "extra": 1}]},
                {**THEMA, "titel": ""}, {k: v for k, v in THEMA.items() if k != "falle"}, {**THEMA, "seite": -1}):
        with pytest.raises(ToolError):
            _call("save_thema", bad)
    assert ai.load_entry(core.MIRROR_DIR / PATH)["thema"] is None


def test_save_flashcards_appear_in_studyhub():
    _mirror()
    cards = [{"front": "Was ist H0?", "back": "Die Nullhypothese."}, {"front": "α?", "back": "Fehler 1. Art"}]
    for bad in ([], [{"front": "x"}], [{"front": "x", "back": "y", "extra": "z"}]):
        with pytest.raises(ToolError):
            _call("save_flashcards", {"path": PATH, "cards": bad})
    assert _call("save_flashcards", {"path": PATH, "cards": cards})["gespeichert"]
    assert ai.load_entry(core.MIRROR_DIR / PATH)["flashcards"]["output"] == {"cards": cards}
    data = TestClient(app).get("/api/studyhub", headers=AUTH).json()
    assert [k["frage"] for k in data["details"]["statistik-i"]["karten"]["liste"]] == ["Was ist H0?", "α?"]
    assert mcp_server.list_courses()["kurse"][0]["lernkarten"] == 1


def test_save_tutor_questions_feed_the_tutor():
    _mirror()
    _mirror("Mathe/Handout.zip", "kein Text")
    questions = [{"question": "Was ist H0?", "answer": "Die Nullhypothese.", "page": 1},
                 {"question": "Was ist α?", "answer": "Die Wahrscheinlichkeit für den Fehler 1. Art.", "page": 9}]
    for bad in ([], [{"question": "x", "answer": "y"}], [{"question": "x", "answer": "y", "page": 0}],
                [{"question": "x", "answer": "y", "page": 1, "extra": 1}]):
        with pytest.raises(ToolError):
            _call("save_tutor_questions", {"path": PATH, "questions": bad})
    with pytest.raises(ToolError, match="nur"):
        _call("save_tutor_questions", {"path": "Mathe/Handout.zip", "questions": questions})

    saved = _call("save_tutor_questions", {"path": PATH, "questions": questions})
    assert saved["neu"] == 2 and saved["fragen_gesamt"] == 2
    assert tutor.stats("Statistik I") | {"courses": None} == {
        "files": 1, "questions": 2, "answered": 0, "correct": 0, "partial": 0, "wrong": 0, "courses": None}
    question = tutor.next_question("Statistik I", with_solution=True)
    assert question["question"] in {"Was ist H0?", "Was ist α?"} and question["source"].endswith("S. 1")
    assert mcp_server.list_files(course="Statistik I")["dateien"][0]["tutor_fragen"] == 2

    # Nie etwas löschen: zweiter Aufruf nur mit add, dann kommen die Fragen dazu
    with pytest.raises(ToolError, match="add=true"):
        _call("save_tutor_questions", {"path": PATH, "questions": questions[:1]})
    assert _call("save_tutor_questions", {"path": PATH, "questions": questions[:1], "add": True})["fragen_gesamt"] == 3


def _pdf(path: str, pages: int) -> Path:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    file = core.MIRROR_DIR / path
    file.parent.mkdir(parents=True, exist_ok=True)
    with open(file, "wb") as out:
        writer.write(out)
    return file


def test_read_file_points_to_view_pages_for_pdfs_without_text():
    _pdf("VWL/Eigene Dateien/Mindestpreis.pdf", 2)
    assert "view_pages" in _call("read_file", {"path": "VWL/Eigene Dateien/Mindestpreis.pdf"})["hinweis"]


def test_view_pages_returns_page_images(monkeypatch):
    _pdf("VWL/Eigene Dateien/Mindestpreis.pdf", 6)
    calls = []

    def fake_render(file, start, count):
        calls.append((file.name, start, count))
        return 6, [b"\xff\xd8bild"] * min(count, 6 - start + 1)

    monkeypatch.setattr(mcp_server, "render_pdf_pages", fake_render)
    result = asyncio.run(mcp_server.mcp.call_tool("view_pages", {"path": "VWL/Eigene Dateien/Mindestpreis.pdf",
                                                                 "start_page": 5, "count": 4}))
    assert not result.is_error and calls == [("Mindestpreis.pdf", 5, 4)]
    assert result.content[0].text == "VWL/Eigene Dateien/Mindestpreis.pdf: Seite 5–6 von 6."
    images = result.content[1:]
    assert [i.type for i in images] == ["image", "image"] and images[0].mime_type == "image/jpeg"

    first = asyncio.run(mcp_server.mcp.call_tool("view_pages", {"path": "VWL/Eigene Dateien/Mindestpreis.pdf"}))
    assert first.content[0].text.endswith("Seite 1–3 von 6. Weiter mit start_page=4.")
    with pytest.raises(ToolError, match="nur 6 Seiten"):
        asyncio.run(mcp_server.mcp.call_tool("view_pages", {"path": "VWL/Eigene Dateien/Mindestpreis.pdf",
                                                            "start_page": 7}))
    with pytest.raises(ToolError):  # höchstens 4 Seiten pro Aufruf
        asyncio.run(mcp_server.mcp.call_tool("view_pages", {"path": "VWL/Eigene Dateien/Mindestpreis.pdf",
                                                            "count": 5}))


def test_view_pages_only_for_pdfs_and_only_on_the_mac(monkeypatch):
    _mirror()
    with pytest.raises(ToolError, match="nur PDF"):
        asyncio.run(mcp_server.mcp.call_tool("view_pages", {"path": PATH}))
    _pdf("VWL/folien.pdf", 1)
    monkeypatch.setitem(sys.modules, "Quartz", None)  # wie ohne macOS: Import scheitert
    with pytest.raises(ToolError, match="nur in der Mac-App"):
        asyncio.run(mcp_server.mcp.call_tool("view_pages", {"path": "VWL/folien.pdf"}))


@pytest.mark.skipif(sys.platform != "darwin", reason="Quartz (CoreGraphics) gibt es nur auf macOS")
def test_render_pdf_pages_with_quartz_on_the_mac():
    file = _pdf("VWL/quer.pdf", 2)
    total, images = mcp_server.render_pdf_pages(file, 2, 4)
    assert total == 2 and len(images) == 1 and images[0][:2] == b"\xff\xd8"  # JPEG


def test_stdio_roundtrip_like_claude_desktop():
    """Startet den Server als eigenen Prozess wie Claude Desktop (initialize-Handshake über stdio)."""
    _mirror()
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "server/mcp_server.py")],
        env={"ILIAS_SYNC_HOME": str(HOME), "PATH": os.environ.get("PATH", "")},
    )

    async def session():
        async with Client(params, mode="legacy", read_timeout_seconds=30) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            saved = await client.call_tool("save_thema", THEMA)  # schreibt ins Protokoll; stdout bleibt sauber
            files = await client.call_tool("list_files", {})
            return names, saved, files

    names, saved, files = asyncio.run(session())
    assert "save_thema" in names and not saved.is_error
    assert json.loads(files.content[0].text)["dateien"][0]["ai"]["thema"] is True
