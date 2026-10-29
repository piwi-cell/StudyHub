"""StudyHub im Browser öffnen (für das Mikrofon): nur StudyHub-Adressen, Token wird mitgegeben."""

from fastapi.testclient import TestClient

import app as app_module
from app import app

AUTH = {"x-app-token": "test-token"}


def _geoeffnet(monkeypatch) -> list[list[str]]:
    aufrufe = []
    monkeypatch.setattr(app_module.subprocess, "run", lambda args, check=False: aufrufe.append(args))
    return aufrufe


def test_open_browser_behaelt_studyhub_adresse(monkeypatch):
    aufrufe = _geoeffnet(monkeypatch)
    antwort = TestClient(app).post("/api/studyhub/open-browser", headers=AUTH,
                                   json={"hash": "#/modul/statistik-i/sprachtutor"})
    assert antwort.status_code == 200
    assert aufrufe == [["open", "http://testserver/ui/studyhub/index.html?t=test-token#/modul/statistik-i/sprachtutor"]]


def test_open_browser_verwirft_fremde_adressen(monkeypatch):
    aufrufe = _geoeffnet(monkeypatch)
    TestClient(app).post("/api/studyhub/open-browser", headers=AUTH, json={"hash": "#/x?y=<script>"})
    assert aufrufe == [["open", "http://testserver/ui/studyhub/index.html?t=test-token"]]


def test_open_browser_braucht_token(monkeypatch):
    aufrufe = _geoeffnet(monkeypatch)
    assert TestClient(app).post("/api/studyhub/open-browser", json={"hash": ""}).status_code == 403
    assert aufrufe == []
