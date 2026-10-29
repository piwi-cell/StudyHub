"""Kern: Kursnamen, Einstellungen, Kopieren in den Zielordner, Statuszeile."""

import os
import unicodedata

import cli
import core
import courses
import sync


def test_short_name_strips_codes_and_semester():
    assert courses.short_name("ACC 300 Introduction to Financial Accounting [V] (HWS 2026)") == \
        "Introduction to Financial Accounting"
    assert courses.short_name("[V]") == "[V]"  # nichts übrig: Originaltitel behalten


def test_suggest_groups_duplicates_and_exclusions():
    entries = [
        {"title": "MAN 301 Marketing [V] (HWS 2026)", "url": "https://x/crs/1"},
        {"title": "MAN 301 Marketing [1. PG] (HWS 2026)", "url": "https://x/grp/2"},
        {"title": "License Information", "url": "https://x/crs/3"},
    ]
    known = {"Alt": {"name": "Marketing", "sync": True, "url": "", "group": False}}
    new = courses.suggest(entries, known)
    assert new["MAN 301 Marketing [V] (HWS 2026)"]["name"] == "Marketing (2)"  # "Marketing" ist belegt
    assert new["MAN 301 Marketing [1. PG] (HWS 2026)"]["group"] is True
    assert new["License Information"]["sync"] is False


def test_safe_folder_name():
    assert courses.safe_folder_name("  A/B   C ") == "A-B C"
    assert courses.safe_folder_name("   ") == "Kurs"


def test_config_roundtrip_keeps_defaults():
    core.save_config({"uni_id": "mmuster"})
    config = core.load_config()
    assert config["uni_id"] == "mmuster"
    assert config["interval_minutes"] == 30


def test_nfc_normalizes_macos_filenames():
    decomposed = unicodedata.normalize("NFD", "Übung")
    assert decomposed != "Übung"
    assert core.nfc(decomposed) == "Übung"


def _mirror_file(relative: str, text: str = "x"):
    path = core.MIRROR_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_publish_copies_new_keeps_existing_and_versions_updates(tmp_path):
    target = tmp_path / "Ziel"
    config, state = {"target_dir": str(target)}, {"published": {}}
    _mirror_file("Kurs/neu.pdf")
    (target / "Kurs").mkdir(parents=True)
    (target / "Kurs/selbst.pdf").write_text("eigene Notizen", encoding="utf-8")
    _mirror_file("Kurs/selbst.pdf", "von ILIAS")

    copied = sync.publish(config, state)
    assert ("Kurs/neu.pdf", False) in copied
    assert (target / "Kurs/selbst.pdf").read_text(encoding="utf-8") == "eigene Notizen"  # nie überschreiben

    changed = _mirror_file("Kurs/neu.pdf", "neue Fassung")
    os.utime(changed, (changed.stat().st_mtime + 100, changed.stat().st_mtime + 100))
    copied = sync.publish(config, state)
    assert copied == [("Kurs/neu.pdf", True)]
    assert any("aktualisiert" in p.name for p in (target / "Kurs").iterdir())


def test_last_sync_line_shows_message():
    core.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    core.LOG_FILE.write_text("2026-10-24 09:55:13  ILIAS: abgeglichen, 2 neu, 0 geändert\n", encoding="utf-8")
    assert cli.last_sync_line() == "2026-10-24 09:55 · abgeglichen, 2 neu, 0 geändert"


def _schedule_env(monkeypatch, tmp_path, active=True):
    import schedule

    calls = []
    monkeypatch.setattr(schedule, "PLIST", tmp_path / f"{schedule.LABEL}.plist")
    monkeypatch.setattr(schedule, "_launchctl", lambda *args: calls.append(args) or
                        type("R", (), {"returncode": 0 if active else 113})())
    return schedule, calls


def test_schedule_refresh_moves_app_job_to_this_installation(monkeypatch, tmp_path):
    import plistlib

    schedule, calls = _schedule_env(monkeypatch, tmp_path)
    assert schedule.refresh(30) is False  # kein Job: nichts tun
    old = {**schedule._job(30), "ProgramArguments": ["/alt/.venv/bin/python", "/alt/core/sync.py", "--scheduled"]}
    schedule.PLIST.write_bytes(plistlib.dumps(old))
    assert schedule.refresh(30) is True
    assert plistlib.loads(schedule.PLIST.read_bytes()) == schedule._job(30)
    assert ("bootstrap", schedule.DOMAIN, str(schedule.PLIST)) in calls
    assert not any(call[0] == "enable" for call in calls)
    assert schedule.refresh(30) is False  # schon aktuell


def test_schedule_refresh_keeps_paused_and_terminal_jobs(monkeypatch, tmp_path):
    import plistlib

    schedule, calls = _schedule_env(monkeypatch, tmp_path, active=False)
    old = {**schedule._job(60), "ProgramArguments": ["/alt/.venv/bin/python", "/alt/core/sync.py", "--scheduled"]}
    schedule.PLIST.write_bytes(plistlib.dumps(old))
    assert schedule.refresh(60) is True
    assert not any(call[0] == "bootstrap" for call in calls)  # angehalten bleibt angehalten

    terminal = {**schedule._job(30), "ProgramArguments": ["/x/venv/bin/python", "/x/ILIAS-Sync/app/sync.py"]}
    schedule.PLIST.write_bytes(plistlib.dumps(terminal))
    assert schedule.refresh(30) is False
    assert plistlib.loads(schedule.PLIST.read_bytes()) == terminal


def test_sync_messages_point_to_the_app_not_the_terminal(monkeypatch, capsys):
    """Der Abgleich läuft aus der App und ihrem Hintergrund-Job: kein Verweis auf „ilias-sync …“."""
    messages = []
    monkeypatch.setattr(sync, "notify_once_a_day", lambda key, title, text, details="": messages.append(text))
    monkeypatch.setattr(sync, "notify", lambda title, text, details="", icon="": messages.append(text))

    core.save_config({**core.DEFAULT_CONFIG, "uni_id": "", "target_dir": ""})
    sync.run()
    assert "in StudyHub mit der Uni-ID anmelden" in capsys.readouterr().out  # core.log schreibt auf stdout

    def login_failed(config, list_only=False):
        raise sync.CrawlFailed("Error Login", login=True)

    core.save_config({**core.DEFAULT_CONFIG, "uni_id": "ab123", "target_dir": "/tmp/ziel"})
    monkeypatch.setattr(sync, "run_pferd", login_failed)
    sync.run()

    def new_course(config, list_only=False):
        return {"added": set(), "changed": set(), "entries": [], "new": {"X": {"name": "Statistik", "sync": True}}}

    monkeypatch.setattr(sync, "run_pferd", new_course)
    monkeypatch.setattr(sync, "publish", lambda config, state: [])
    sync.run()
    assert len(messages) == 2 and "Einstellungen › ILIAS-Zugang" in messages[0] and "unter Kurse" in messages[1]
    assert not any("ilias-sync" in text or "Terminal" in text for text in messages)


def test_sync_progress_exists_only_while_running(monkeypatch):
    seen = {}

    def fake_pferd(config, list_only=False):
        seen["progress"] = sync.read_progress()
        return {"added": set(), "changed": set(), "entries": [], "new": {}}

    core.save_config({**core.DEFAULT_CONFIG, "uni_id": "ab123", "target_dir": "/tmp/ziel"})
    monkeypatch.setattr(sync, "run_pferd", fake_pferd)
    monkeypatch.setattr(sync, "publish", lambda config, state: [])
    sync.run()
    assert seen["progress"]["phase"] == "anmelden" and seen["progress"]["text"].startswith("Anmeldung bei ILIAS · 0:0")
    assert not sync.PROGRESS_FILE.exists() and sync.read_progress() is None


def test_sync_progress_text_counts_courses_and_time(monkeypatch):
    import time

    core.save_json(sync.PROGRESS_FILE, {"phase": "kurse", "total": 8, "done": 3, "started": time.time() - 80.5})
    assert sync.read_progress()["text"] == "3 von 8 Kursen fertig · 1:20"
    sync.PROGRESS_FILE.write_text("kaputt", encoding="utf-8")
    assert sync.read_progress() is None


def test_pferd_runner_counts_finished_courses(monkeypatch, tmp_path):
    """Kursübersicht → Anzahl gewählter Kurse; Ende einer Kursseite → ein Kurs fertig (ohne Netz, ohne PFERD-Lauf)."""
    import asyncio
    import dataclasses
    import importlib
    import json
    import sys

    import PFERD.__main__
    from PFERD.auth.keyring import KeyringAuthenticator
    from PFERD.auth.tfa import TfaAuthenticator
    from PFERD.crawl import http_crawler
    from PFERD.crawl.ilias import ilias_web_crawler, shibboleth_login
    from PFERD.crawl.ilias.kit_ilias_html import IliasPage

    # Der Runner patcht PFERD beim Import: alles nach dem Test zurücksetzen
    for owner, name in [(shibboleth_login.ShibbolethLogin, "login"), (shibboleth_login, "_post"),
                        (ilias_web_crawler.IliasWebCrawler, "_crawl_url"),
                        (ilias_web_crawler.IliasWebCrawler, "_crawl_ilias_page"), (IliasPage, "get_child_elements"),
                        (http_crawler.HttpCrawler, "__init__"), (KeyringAuthenticator, "credentials"),
                        (TfaAuthenticator, "password")]:
        monkeypatch.setattr(owner, name, getattr(owner, name))
    progress = tmp_path / "fortschritt.json"
    selection = tmp_path / "auswahl.json"
    selection.write_text(json.dumps({
        "courses": {"STA 100 Statistik I": {"name": "Statistik I", "sync": True},
                    "MIK 100 Mikro": {"name": "Mikro", "sync": False}},
        "include_new": False, "list_only": False, "discovered": str(tmp_path / "gefunden.json"),
        "progress": str(progress),
    }), encoding="utf-8")
    monkeypatch.setenv("ILIAS_SYNC_SELECTION", str(selection))
    monkeypatch.setattr(PFERD.__main__, "main", lambda: None)
    monkeypatch.delitem(sys.modules, "pferd_runner", raising=False)
    runner = importlib.import_module("pferd_runner")

    @dataclasses.dataclass
    class Element:
        name: str
        url: str

    class Overview:
        def _is_course_overview_page(self):
            return True

    elements = [Element("STA 100 Statistik I", "https://x/crs_1"), Element("MIK 100 Mikro", "https://x/crs_2")]
    monkeypatch.setattr(runner, "_original_children", lambda _page: elements)
    chosen = runner._children_with_course_selection(Overview())
    assert [e.name for e in chosen] == ["Statistik I"]
    assert json.loads(progress.read_text(encoding="utf-8")) == {"phase": "kurse", "total": 1, "done": 0}

    async def crawled(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner, "_original_crawl_page", crawled)
    asyncio.run(runner._crawl_page_counting_courses(None, "https://x/ordner", Element("Ordner", "https://x/f")))
    assert json.loads(progress.read_text(encoding="utf-8"))["done"] == 0  # Unterordner zählt nicht
    for _ in range(2):  # wiederholte Seite zählt nur einmal
        asyncio.run(runner._crawl_page_counting_courses(None, "https://x/crs_1", chosen[0], None))
    assert json.loads(progress.read_text(encoding="utf-8"))["done"] == 1


def test_sync_keeps_settings_changed_while_it_runs(monkeypatch):
    """Regression: _run speicherte bei neuen Kursen die Konfiguration vom Start des Abgleichs und überschrieb so,
    was zwischendurch in der App geändert wurde (Abgleich dauert Minuten)."""
    core.save_config({**core.DEFAULT_CONFIG, "uni_id": "ab123", "target_dir": "/tmp/ziel",
                      "courses": {"A": {"name": "Analysis", "sync": True}}})

    def slow_pferd(config, list_only=False):
        changed = core.load_config()  # Nutzer ändert in der App Zielordner und Kurs A
        changed["target_dir"] = "/tmp/neu"
        changed["courses"]["A"]["sync"] = False
        core.save_config(changed)
        return {"added": set(), "changed": set(), "entries": [], "new": {"X": {"name": "Statistik", "sync": True}}}

    published = {}

    def fake_publish(config, state):
        published["target"] = config["target_dir"]
        return []

    monkeypatch.setattr(sync, "run_pferd", slow_pferd)
    monkeypatch.setattr(sync, "publish", fake_publish)
    monkeypatch.setattr(sync, "notify", lambda *args, **kwargs: None)
    sync.run()
    config = core.load_config()
    assert config["target_dir"] == "/tmp/neu" and config["courses"]["A"]["sync"] is False
    assert config["courses"]["X"] == {"name": "Statistik", "sync": True}  # neuer Kurs trotzdem gespeichert
    assert published["target"] == "/tmp/neu"  # Dateien gehen in den neuen Zielordner
