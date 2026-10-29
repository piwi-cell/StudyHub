"""Bibliotheken: Seite der UB lesen, Messungen speichern, Verlauf je Wochentag/Stunde, Endpunkte."""

import time

import pytest
from fastapi.testclient import TestClient

import libraries
from app import app

AUTH = {"x-app-token": "test-token"}


@pytest.fixture(autouse=True)
def no_real_launchd_job(monkeypatch, tmp_path):
    """Nie den echten launchd-Job sehen: ist die Hintergrundmessung am Mac an, wäre „hintergrund“ sonst True."""
    monkeypatch.setattr(libraries, "PLIST", tmp_path / "LaunchAgents" / f"{libraries.LABEL}.plist")


def _row(percent, seats, ampel, slug, name, info="Öffnungs&shy;zeiten: Mo–Fr 8–18&nbsp;Uhr"):
    return (f'<tr><td class="" title="{percent} % von {seats} Arbeitsplätzen sind belegt"><div class="available-seats-'
            f'table-status"><span class="sr-only">Auslastung</span><span aria-hidden="true">{percent}&nbsp;%</span>'
            f'<span class="t3js-icon icon" data-identifier="{ampel}" aria-hidden="true"><svg></svg></span></div></td>'
            f'<td><h4><a href="/standorte/{slug}/">{name}</a></h4><div><p>{info}</p></div></td>'
            f'<td><a href="http://www2.bib.uni-mannheim.de/3d" class="button">3D-Ansicht</a></td></tr>')


def page(a5=60, stand="26.10.26, 14:06"):
    return ('<html><table><tbody>' + _row(100, 44, "ampel_rot", "ausleihzentrum-schloss-westfluegel",
                                          "Ausleihzentrum Schloss Westflügel")
            + _row(a5, 306, "ampel_gruen", "bb-a5", "Bibliotheks&shy;bereich A5", "Fach&shy;bibliothek für Informatik")
            + f'</tbody></table><p>Stand: {stand}&nbsp;Uhr</p></html>')


def ts(text):  # lokale Zeit wie auf der Seite
    return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M"))


def test_parse_real_structure():
    data = libraries.parse(page())
    assert data["stand"] == ts("2026-10-26 14:06")
    a5 = data["bereiche"][1]
    assert a5 == {"slug": "bb-a5", "name": "Bibliotheksbereich A5", "url": "https://www.bib.uni-mannheim.de/standorte/bb-a5/",
                  "info": "Fachbibliothek für Informatik", "percent": 60, "seats": 306, "level": "gering"}
    assert data["bereiche"][0]["level"] == "hoch"
    with pytest.raises(libraries.LibraryError, match="Aufbau geändert"):
        libraries.parse("<html>Wartungsarbeiten</html>")


def test_store_skips_same_stand_and_builds_history():
    assert libraries.store(libraries.parse(page()), ts("2026-10-26 14:07")) is True
    assert libraries.store(libraries.parse(page()), ts("2026-10-26 14:08")) is False  # gleicher Stand
    libraries.store(libraries.parse(page(a5=70, stand="26.10.26, 14:11")), ts("2026-10-26 14:12"))
    libraries.store(libraries.parse(page(a5=90, stand="26.10.26, 15:01")), ts("2026-10-26 15:02"))

    data = libraries.overview(now=ts("2026-10-26 15:03"))  # ein Montag
    # Takt: 14:06→14:11 zählt, 14:11→15:01 gilt als Pause
    assert (data["messungen"], data["taktMinuten"], data["alterMinuten"]) == (3, 5, 2)
    assert data["jetzt"] == {"wochentag": 0, "stunde": 15}
    a5 = next(b for b in data["bereiche"] if b["slug"] == "bb-a5")
    assert a5["aktuell"] == {"prozent": 90, "plaetze": 306, "frei": 31, "stufe": "gering"}
    montag = a5["woche"][0]
    assert montag[14] == {"stunde": 14, "mittel": 65, "messungen": 2}
    assert montag[15]["mittel"] is None and montag[15]["messungen"] == 1  # eine Messung reicht noch nicht
    assert a5["typischJetzt"] is None and data["hintergrund"] is False


def test_endpoints(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(libraries, "fetch", lambda: libraries.parse(page()))
    first = client.get("/api/libraries", headers=AUTH).json()
    assert first["stand"] is None and first["bereiche"] == []
    refreshed = client.post("/api/libraries/refresh", headers=AUTH).json()
    assert refreshed["neu"] is True and len(refreshed["bereiche"]) == 2

    def offline():
        raise libraries.LibraryError("Seite der UB nicht erreichbar (ConnectError)")

    monkeypatch.setattr(libraries, "fetch", offline)
    monkeypatch.setattr(libraries, "overview", lambda now=None: {"stand": None, "alterMinuten": None})
    assert client.post("/api/libraries/refresh", headers=AUTH).status_code == 502
    assert client.get("/api/libraries").status_code == 403
    # Tests laufen im Demo-Modus: kein launchd-Job
    assert client.patch("/api/libraries/background", headers=AUTH, json={"aktiv": True}).status_code == 400


def test_background_job(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(libraries, "PLIST", tmp_path / "job.plist")
    monkeypatch.setattr(libraries, "_launchctl", lambda *args: calls.append(args) or type("R", (), {"returncode": 0})())
    libraries.background_start()
    assert libraries.PLIST.exists() and libraries.background_active()
    import plistlib
    job = plistlib.loads(libraries.PLIST.read_bytes())
    assert job["StartInterval"] == libraries.INTERVAL and job["ProgramArguments"][-1] == "--sample"
    libraries.background_stop()
    assert not libraries.PLIST.exists() and not libraries.background_active()
    assert calls[-1][0] == "bootout"


# --- Telegram: /bib, Voll/Frei-Meldungen, Bot ----------------------------------------


def connect_telegram(monkeypatch):
    """Telegram als eingerichtet markieren; gesendete Nachrichten landen in der Liste."""
    import core
    import telegram_bot
    config = core.load_config()
    config["telegram"] = True
    core.save_config(config)
    sent = []
    monkeypatch.setattr(telegram_bot, "send", sent.append)
    return sent


def test_status_text_lists_areas_and_filters():
    libraries.store(libraries.parse(page(a5=60, stand="26.10.26, 14:06")), ts("2026-10-26 14:07"))
    text = libraries.status_text(now=ts("2026-10-26 14:08"))
    assert "Stand 14:06 Uhr" in text and "vor" not in text
    # sortiert nach Belegung, Ampel als Symbol, freie Plätze
    a5 = text.index("🟢 <b>A5</b>: 60 %, ca. 122 von 306 frei")
    assert a5 < text.index("🔴 <b>Ausleihzentrum")
    assert "Am leersten: A5" in text
    only = libraries.status_text("a 5", now=ts("2026-10-26 14:08"))
    assert "A5" in only and "Ausleihzentrum" not in only and "Am leersten" not in only
    assert "Keinen Bereich „<x>“" not in libraries.status_text("<x>")  # Eingaben werden maskiert
    assert "Keinen Bereich „&lt;x&gt;“ gefunden" in libraries.status_text("<x>")
    assert libraries.status_text("").startswith("📚")


def test_status_text_without_measurement():
    assert libraries.status_text().startswith("Noch keine Messung")


def test_alerts_with_gap_and_reset(monkeypatch):
    sent = connect_telegram(monkeypatch)
    monkeypatch.setattr(libraries, "fetch", lambda: libraries.parse(page(a5=values.pop(0), stand=stands.pop(0))))
    values = [85, 91, 88, 84, 92]
    stands = [f"26.10.26, 14:{m:02d}" for m in (5, 10, 15, 20, 25)]
    libraries.save_alert_settings(aktiv=True, schwelle=90, bereiche=["bb-a5"])

    libraries.sample()  # 85 %: erste Messung erfasst nur den Zustand
    libraries.sample()  # 91 %: voll
    libraries.sample()  # 88 %: noch voll (Abstand 5 Punkte)
    libraries.sample()  # 84 %: wieder Platz
    footer = "\n\n/bib für alle Bereiche"
    assert sent == ["🔴 <b>A5</b> ist voll: 91 % belegt" + footer,
                    "🟢 <b>A5</b> hat wieder Platz: 84 % belegt, ca. 49 frei" + footer]
    # Ausleihzentrum (100 %) ist nicht ausgewählt: keine Meldung
    libraries.save_alert_settings(schwelle=95)  # neue Schwelle: Zustand neu erfassen
    libraries.sample()  # 92 %: erste Messung nach der Änderung, keine Meldung
    assert len(sent) == 2
    assert libraries.alert_settings() == {"aktiv": True, "schwelle": 95, "bereiche": ["bb-a5"]}


def test_alerts_off_or_without_telegram(monkeypatch):
    sent = connect_telegram(monkeypatch)
    libraries.store(libraries.parse(page(a5=10)), ts("2026-10-26 14:07"))
    assert libraries.alerts(libraries.parse(page(a5=95))["bereiche"]) == []  # Meldungen aus
    import core
    config = core.load_config()
    config["telegram"] = False
    core.save_config(config)
    libraries.save_alert_settings(aktiv=True)
    libraries.send_alerts(libraries.parse(page(a5=10))["bereiche"])
    libraries.send_alerts(libraries.parse(page(a5=95))["bereiche"])
    assert sent == []


def test_alert_failure_does_not_break_sampling(monkeypatch):
    import telegram_bot
    connect_telegram(monkeypatch)
    libraries.save_alert_settings(aktiv=True)

    def broken(_text):
        raise telegram_bot.TelegramError("HTTP 401 Unauthorized")

    monkeypatch.setattr(telegram_bot, "send", broken)
    monkeypatch.setattr(libraries, "alerts", lambda areas: ["voll"])
    monkeypatch.setattr(libraries, "fetch", lambda: libraries.parse(page()))
    assert libraries.sample()["neu"] is True


def test_answer_bib_measures_when_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(libraries, "_last_fetch", 0.0)
    monkeypatch.setattr(libraries, "sample", lambda: calls.append(1) or libraries.store(
        libraries.parse(page()), time.time()))
    assert "<b>A5</b>" in libraries.answer_bib("a5")
    assert calls == [1]
    libraries.answer_bib()  # direkt danach: nicht noch einmal abrufen
    assert calls == [1]


def test_bot_answers_only_own_chat(monkeypatch):
    import integrations
    import telegram_bot
    now = time.time()
    updates = [
        {"update_id": 7, "message": {"chat": {"id": 42}, "date": now, "text": "/bib@MeinBot a5"}},
        {"update_id": 8, "message": {"chat": {"id": 99}, "date": now, "text": "/bib"}},  # fremder Chat
        {"update_id": 9, "message": {"chat": {"id": 42}, "date": now - 3600, "text": "/bib"}},  # zu alt
        {"update_id": 10, "message": {"chat": {"id": 42}, "date": now, "text": "hallo"}},
    ]
    calls = []

    def fake_call(token, method, **params):
        calls.append((method, params))
        return updates if method == "getUpdates" else {}

    monkeypatch.setattr(telegram_bot, "_call", fake_call)
    offset = integrations.poll_commands("1:x", "42", None, {"bib": lambda q: f"Stand {q}"})
    assert offset == 11
    replies = [p["text"] for m, p in calls if m == "sendMessage"]
    assert replies[0] == "Stand a5" and replies[1].startswith("Diesen Befehl kenne ich nicht")
    assert len(replies) == 2 and all(p["chat_id"] == "42" for m, p in calls if m == "sendMessage")


def test_answer_command_variants():
    import integrations
    handlers = {"bib": lambda q: f"[{q}]"}
    assert integrations.answer_command("bib", handlers) == "[]"
    assert integrations.answer_command("/BIB  Ehrenhof ", handlers) == "[Ehrenhof]"
    assert integrations.answer_command("/start", handlers) == integrations.BOT_HELP
    assert integrations.answer_command("", handlers) is None

    def broken(_q):
        raise RuntimeError("kaputt")

    assert integrations.answer_command("/bib", {"bib": broken}).startswith("⚠️")


def test_telegram_endpoints(monkeypatch):
    import telegram_bot
    client = TestClient(app)
    assert client.patch("/api/libraries/alerts", headers=AUTH, json={"aktiv": True}).status_code == 400
    assert client.post("/api/libraries/telegram", headers=AUTH).status_code == 400

    calls = []
    monkeypatch.setattr(telegram_bot, "_call", lambda token, method, **p: calls.append((method, p)) or (
        {"username": "UniBibBot"} if method == "getMe" else {}))
    bad = client.post("/api/telegram/connect", headers=AUTH, json={"token": "kein token"})
    assert bad.status_code == 400 and "Bot-Token" in bad.json()["detail"]
    assert client.post("/api/telegram/connect", headers=AUTH, json={"token": "1:a", "chat": "abc"}).status_code == 400
    ok = client.post("/api/telegram/connect", headers=AUTH, json={"token": "123:AA-b_c", "chat": "42"}).json()
    assert ok == {"ok": True, "bot": "UniBibBot", "who": ""}
    assert calls[-1][0] == "sendMessage" and calls[-1][1]["chat_id"] == "42" and "/bib" in calls[-1][1]["text"]

    status = client.get("/api/libraries", headers=AUTH).json()["telegram"]
    assert status == {"verbunden": True, "bot": "UniBibBot", "alarm": libraries.ALERT_DEFAULT}
    changed = client.patch("/api/libraries/alerts", headers=AUTH,
                           json={"aktiv": True, "schwelle": 85, "bereiche": ["bb-a5"]}).json()
    assert changed["alarm"] == {"aktiv": True, "schwelle": 85, "bereiche": ["bb-a5"]}
    assert client.patch("/api/libraries/alerts", headers=AUTH, json={"schwelle": 20}).status_code == 422

    sent = []
    monkeypatch.setattr(telegram_bot, "send", sent.append)
    assert client.post("/api/libraries/telegram", headers=AUTH).json() == {"ok": True}
    assert sent == ["Noch keine Messung. Die App misst, sobald sie läuft."]
    client.post("/api/telegram/disconnect", headers=AUTH)
    assert client.get("/api/libraries", headers=AUTH).json()["telegram"]["verbunden"] is False


def test_bot_reads_keychain_once_and_stops_when_denied(monkeypatch):
    import threading

    import keyring.errors

    import core
    import integrations
    connect_telegram(monkeypatch)
    stop = threading.Event()
    reads, polls = [], []

    def get_password(service, account):
        reads.append(account)
        return {"Telegram-Token": "1:x", "Telegram-Chat": "42"}[account]

    def poll(token, chat_id, offset, handlers):
        polls.append((token, chat_id))
        if len(polls) == 3:
            stop.set()
        return offset

    monkeypatch.setattr(integrations.keyring, "get_password", get_password)
    monkeypatch.setattr(integrations.telegram_bot, "_call", lambda *a, **k: {})
    monkeypatch.setattr(integrations, "poll_commands", poll)
    integrations.run_telegram_bot(stop, {})
    assert len(polls) == 3 and reads == ["Telegram-Token", "Telegram-Chat"]  # nur einmal gelesen

    def denied(service, account):
        reads.append("abgelehnt")
        raise keyring.errors.KeyringError("User canceled")

    monkeypatch.setattr(integrations.keyring, "get_password", denied)
    integrations.run_telegram_bot(threading.Event(), {})  # kehrt zurück statt erneut zu fragen
    assert reads[-1] == "abgelehnt" and reads.count("abgelehnt") == 1
    assert core.load_config()["telegram"] is True


def test_background_job_refreshed_after_update(monkeypatch):
    import plistlib
    calls = []
    monkeypatch.setattr(libraries, "_launchctl", lambda *args: calls.append(args) or type("R", (), {"returncode": 0})())
    assert libraries.background_refresh() is False  # kein Job: nichts tun
    libraries.PLIST.parent.mkdir(parents=True, exist_ok=True)
    old = {**libraries._job(), "StartInterval": 600}  # eingeschaltet vor dem Wechsel auf 5 Minuten
    libraries.PLIST.write_bytes(plistlib.dumps(old))
    assert libraries.background_refresh() is True
    assert plistlib.loads(libraries.PLIST.read_bytes())["StartInterval"] == libraries.INTERVAL
    assert ("bootstrap", libraries.DOMAIN, str(libraries.PLIST)) in calls
    assert libraries.background_refresh() is False  # schon aktuell


# --- Öffnungszeiten ----------------------------------------------------------------


def test_holidays_baden_wuerttemberg():
    from datetime import date
    h = libraries.holidays(2026)  # Ostern 2026: 5. April
    for d in ((4, 3), (4, 6), (5, 14), (5, 25), (6, 4), (1, 6), (11, 1), (10, 3)):
        assert date(2026, *d) in h
    assert date(2026, 4, 5) not in h and date(2026, 10, 27) not in h
    assert libraries._easter(2027) == date(2027, 3, 28) and libraries._easter(2025) == date(2025, 4, 20)


def test_opening_hours():
    az, a5 = "ausleihzentrum-schloss-westfluegel", "bb-a5"
    assert libraries.is_open(a5, ts("2026-10-27 22:59")) and not libraries.is_open(a5, ts("2026-10-27 23:00"))
    assert not libraries.is_open(a5, ts("2026-10-31 09:30")) and libraries.is_open(a5, ts("2026-10-31 10:00"))  # Sa
    assert libraries.is_open(az, ts("2026-10-27 17:59")) and not libraries.is_open(az, ts("2026-10-27 18:00"))
    assert not libraries.is_open(az, ts("2026-11-01 12:00"))  # Allerheiligen (So) geschlossen
    assert not libraries.is_open(az, ts("2026-04-06 12:00"))  # Ostermontag: Feiertag, geschlossen
    assert libraries.is_open(a5, ts("2026-04-06 12:00"))  # Feiertag: 10–23 Uhr
    assert libraries.is_open("neuer-bereich", ts("2026-10-27 03:00"))  # unbekannt: als offen
    assert libraries.opens_at(a5, ts("2026-10-27 23:30")) == "morgen 8 Uhr"
    assert libraries.opens_at(a5, ts("2026-10-28 06:00")) == "heute 8 Uhr"
    assert libraries.opens_at(a5, ts("2026-10-30 23:30")) == "morgen 10 Uhr"  # Fr → Sa
    assert libraries.opens_at(az, ts("2026-10-30 19:00")) == "Mo 8 Uhr"  # Fr → Mo (Wochenende zu)
    assert libraries.hours_text(az) == "Mo–Fr 8–18 Uhr · Sa, So, Feiertage geschlossen"


def test_closed_hours_do_not_count_and_bib_says_closed():
    # Montag 22:30 (offen) und 23:30 (zu): nur 22:30 zählt; dienstags 7:30 (zu) gar nicht
    for stand, a5 in (("26.10.26, 22:30", 40), ("26.10.26, 22:35", 50), ("26.10.26, 23:30", 99),
                      ("26.10.26, 23:35", 99), ("27.10.26, 07:30", 99), ("27.10.26, 07:35", 99)):
        libraries.store(libraries.parse(page(a5=a5, stand=stand)), ts("2026-10-27 08:00"))
    data = libraries.overview(now=ts("2026-10-27 07:40"))
    a5 = next(b for b in data["bereiche"] if b["slug"] == "bb-a5")
    assert a5["woche"][0][22]["mittel"] == 45 and a5["woche"][0][23]["messungen"] == 0
    assert a5["woche"][1][7]["messungen"] == 0
    assert a5["offen"] is False and a5["oeffnet"] == "heute 8 Uhr" and a5["typischJetzt"] is None
    text = libraries.status_text(now=ts("2026-10-27 07:40"))
    assert "⚫ <b>A5</b>: geschlossen, öffnet heute 8 Uhr" in text and "Am leersten" not in text


def test_no_alerts_while_closed(monkeypatch):
    sent = connect_telegram(monkeypatch)
    libraries.save_alert_settings(aktiv=True, schwelle=90, bereiche=["bb-a5"])
    full = libraries.parse(page(a5=95))["bereiche"]
    low = libraries.parse(page(a5=40))["bereiche"]
    libraries.send_alerts(full, ts("2026-10-27 22:50"))  # erfasst: voll
    libraries.send_alerts(low, ts("2026-10-27 23:10"))  # zu: keine Meldung, Zustand vergessen
    libraries.send_alerts(low, ts("2026-10-28 08:05"))  # offen: neu erfasst, keine Meldung
    assert sent == []
    libraries.send_alerts(full, ts("2026-10-28 09:00"))
    assert sent and "ist voll" in sent[0]
