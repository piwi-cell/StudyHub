"""KI-Schicht ohne echte Modelle: Cache, Abschnitte, Auswahl für Fragen, Fehlerfälle."""

import pytest

import ai
import core


def _doc(relative: str = "Kurs/skript.txt", text: str = "Inhalt " * 100):
    path = core.MIRROR_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, relative


def test_results_are_cached_per_file_content(monkeypatch):
    calls = []

    def fake_claude(pages, path, task, instruction, model):
        calls.append(task)
        return "## Zusammenfassung", {"provider": "claude", "model": model}

    monkeypatch.setattr(ai, "_claude", fake_claude)
    monkeypatch.setattr(ai, "has_profile", lambda: True)
    path, relative = _doc()
    first = ai.run(path, relative, "summary", "claude")
    second = ai.run(path, relative, "summary", "claude")
    assert calls == ["summary"]
    assert first["cached"] is False and second["cached"] is True
    assert ai.all_entries()[0]["path"] == relative

    path.write_text("anderer Inhalt " * 100, encoding="utf-8")  # neuer Inhalt, neuer Cache-Eintrag
    ai.run(path, relative, "summary", "claude")
    assert calls == ["summary", "summary"]


def test_question_requires_text():
    path, relative = _doc()
    with pytest.raises(ai.AIError):
        ai.run(path, relative, "qa", "gemma", question="  ")


def test_unsupported_file_type():
    path, relative = _doc("Kurs/folien.key")
    with pytest.raises(ai.AIError, match="nicht unterstützt"):
        ai.run(path, relative, "summary", "gemma")


def test_scanned_detection():
    assert ai.is_scanned(["", " ", "x"])
    assert not ai.is_scanned(["Text " * 100])


def test_chunks_respect_size_limit():
    pages = ["Seite " * 3000 for _ in range(12)]  # je ca. 18.000 Zeichen
    chunks = ai._chunks(pages)
    assert len(chunks) > 1
    assert all(len(chunk) <= ai.GEMMA_CHUNK_CHARS + 20_000 for chunk in chunks)
    assert sum(chunk.count("[Seite") for chunk in chunks) == 12


def test_relevant_skips_oversized_and_picks_matching_pages():
    pages = [("Elastizität und Steuerlast. " * 300) if i % 3 == 0 else ("Bilanz Aktiva. " * 400) for i in range(30)]
    selected = ai._relevant(ai._chunks(pages), "Wer trägt die Steuerlast?", ai.GEMMA_CHUNK_CHARS)
    parts = selected.split("\n\n")
    assert parts and all("Steuerlast" in part for part in parts)


def test_gemma_picks_largest_installed_model(monkeypatch):
    monkeypatch.delenv("ILIAS_SYNC_GEMMA", raising=False)
    assert ai.gemma_model(["gemma3:270m", "gemma3:4b"]) == "gemma3:4b"
    assert ai.gemma_model(["gemma3:270m"]) == "gemma3:270m"
    assert ai.gemma_model([]) == ai.GEMMA_DEFAULT


def test_tiny_gemma_models_count_as_small(monkeypatch):
    assert ai.gemma_small("gemma3:270m") and ai.gemma_small("gemma3:1b")
    assert not ai.gemma_small("gemma3:4b") and not ai.gemma_small("gemma3:12b")
    monkeypatch.delenv("ILIAS_SYNC_GEMMA", raising=False)
    monkeypatch.setattr(ai, "ollama_models", lambda: ["gemma3:270m"])
    assert ai.providers()["gemma"]["small"] is True
    monkeypatch.setattr(ai, "ollama_models", lambda: ["gemma3:270m", "gemma3:4b"])
    assert ai.providers()["gemma"]["small"] is False  # das größere Modell gewinnt


def test_complete_reports_invalid_json_as_format_error(monkeypatch):
    monkeypatch.setattr(ai, "_gemma_send", lambda *args, **kwargs: '{"questions": [')  # abgeschnitten
    with pytest.raises(ai.AIFormatError):
        ai.complete("gemma", "System", "Prompt", {"type": "object"})


PPTX_SLIDE = ('<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
              'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody>'
              '<a:p><a:r><a:t>{title}</a:t></a:r></a:p><a:p><a:r><a:t>Barwert </a:t></a:r><a:r><a:t>{body}</a:t>'
              '</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _office(path, parts: dict) -> None:
    import zipfile
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in parts.items():
            archive.writestr(name, text)


def test_pptx_one_page_per_slide_in_order(tmp_path):
    path = tmp_path / "Folien.pptx"
    _office(path, {"ppt/slides/slide10.xml": PPTX_SLIDE.format(title="Zehn: nachschüssig", body="&amp; Rente"),
                   "ppt/slides/slide2.xml": PPTX_SLIDE.format(title="Zwei: vorschüssig", body="R · q"),
                   "ppt/slides/_rels/slide2.xml.rels": "<x/>", "ppt/notesSlides/notesSlide1.xml": "<x/>"})
    assert ai.extract_pages(path) == ["Zwei: vorschüssig\nBarwert R · q", "Zehn: nachschüssig\nBarwert & Rente"]
    assert not ai.is_scanned(ai.extract_pages(path), path)  # knappe Folien sind kein Scan
    assert ai.is_scanned(ai.extract_pages(path))  # bei einer PDF wäre das zu wenig Text


def test_docx_pages_split_at_page_breaks(tmp_path):
    path = tmp_path / "Notizen.docx"
    body = (f'<w:document {W}><w:body>'
            '<w:p><w:r><w:t>Kapitel 1</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Soll</w:t><w:tab/><w:t>Haben</w:t></w:r></w:p>'
            '<w:p><w:r><w:br w:type="page"/><w:t>Kapitel 2</w:t></w:r></w:p>'
            '<w:p><w:r><w:lastRenderedPageBreak/><w:t>Kapitel 3</w:t></w:r></w:p>'
            '</w:body></w:document>')
    _office(path, {"word/document.xml": body})
    assert ai.extract_pages(path) == ["Kapitel 1\nSoll\tHaben", "Kapitel 2", "Kapitel 3"]


def test_broken_office_file_is_reported(tmp_path):
    path = tmp_path / "kaputt.docx"
    path.write_bytes(b"kein zip")
    with pytest.raises(ai.AIError, match="nicht lesbar"):
        ai.extract_pages(path)
    _office(path, {"word/document.xml": "<w:document"})
    with pytest.raises(ai.AIError, match="nicht lesbar"):
        ai.extract_pages(path)


def test_cost_uses_list_price_of_the_day():
    import time

    claude = {"provider": "claude", "model": "claude-opus-5-5", "tokens_in": 10_000, "tokens_out": 2_000,
              "cache_read": 100_000, "cache_write": 0, "created": time.time()}
    assert ai.cost(claude) == pytest.approx((10_000 * 4 + 2_000 * 20 + 100_000 * 0.20) / 1e6)
    october = time.mktime((2026, 10, 27, 12, 0, 0, 0, 0, -1))
    january = time.mktime((2027, 1, 2, 12, 0, 0, 0, 0, -1))
    flash = {"provider": "gemini", "model": "gemini-3.8-flash", "tokens_in": 1_000_000, "tokens_out": 0}
    assert ai.cost({**flash, "created": october}) == pytest.approx(0.75)  # Einführungspreis
    assert ai.cost({**flash, "created": january}) == pytest.approx(1.50)
    haiku = {"provider": "claude", "model": "claude-haiku-5-5", "tokens_in": 200_000, "tokens_out": 0}
    assert ai.cost(haiku) == pytest.approx(200_000 * 0.10 * 5 / 1e6)  # lange Eingabe: höherer Preis
    assert ai.cost({"provider": "gemma", "model": "gemma3:4b"}) == 0.0
    assert ai.cost({"provider": "claude-desktop", "model": "Claude (Abo)"}) is None


def test_usage_sums_this_month_and_counts_unpriced(monkeypatch):
    import time

    def fake_claude(pages, path, task, instruction, model):
        return "## Zusammenfassung", {"provider": "claude", "model": "claude-sonnet-5-5", "tokens_in": 1_000_000,
                                      "tokens_out": 0, "cache_read": 0, "cache_write": 0}

    monkeypatch.setattr(ai, "_claude", fake_claude)
    path, relative = _doc()
    result = ai.run(path, relative, "summary", "claude")
    assert result["cost_usd"] == pytest.approx(2.00)
    entry = ai.load_entry(path)
    entry["thema"] = {"provider": "claude-desktop", "model": "Claude (Abo)", "output": {}, "created": time.time()}
    entry["flashcards"] = {"provider": "claude", "model": "claude-opus-5-5", "tokens_in": 1_000_000, "tokens_out": 0,
                           "output": {}, "created": time.time() - 40 * 86400}  # anderer Monat
    ai.save_entry(entry, relative)
    usage = ai.usage()
    assert (usage["ergebnisse"], usage["ohne_preis"], usage["kosten_usd"]) == (2, 1, 2.0)
    assert usage["nach_anbieter"] == {"claude": 2.0}


def test_truncated_claude_json_is_a_readable_error(monkeypatch):
    class Block:
        type, text = "text", '{"cards": [{"front": "Was'

    class Usage:
        input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 10, 10, 0, 0

    class Response:
        content, usage, model, stop_reason = [Block()], Usage(), "claude-opus-5-5", "max_tokens"

    monkeypatch.setattr(ai, "_claude_send", lambda params: Response())
    path, relative = _doc()
    with pytest.raises(ai.AIError, match="Längenlimit"):
        ai.run(path, relative, "flashcards", "claude")
    Response.stop_reason = "end_turn"
    with pytest.raises(ai.AIFormatError, match="kein gültiges JSON"):
        ai.run(path, relative, "flashcards", "claude")
