# CLAUDE.md – Projektregeln

Diese Datei liest Claude Code zu Beginn jeder Sitzung.
Änderungen an dieser Datei nur per Pull Request.

## Projektziel

Mac-App „StudyHub“ aus dem bestehenden ILIAS-Sync-Skript: lädt Kursdateien der Uni
Mannheim automatisch, sortiert sie und macht daraus mit KI (Claude, Gemma lokal, später
ChatGPT) Zusammenfassungen, Lernkarten und Antworten. Weitergabe an Telegram und reMarkable.

Heute gilt: **nur macOS**, bestehende Ordnerstruktur, lauffähige Demo vor Vollständigkeit.
Die ursprüngliche Roadmap (Windows, `src/`-Struktur, MCP) steht in `ISSUES.md` unter
„Nach dem Hackathon“.

## Architektur (verbindlich)

- `core/` – Kern des Skripts (ILIAS-Abgleich über PFERD, Kurse, Zielordner, Telegram,
  GoodNotes, Notion, launchd). Nur gezielte, kleine Änderungen; Verhalten wie im Original.
- `server/app.py` – lokale API (FastAPI). Ruft nur Funktionen aus `core/`, `ai.py` und
  `integrations.py` auf, enthält keine eigene Fachlogik.
- `server/ai.py` – KI-Anbieter hinter einer Schnittstelle (`run()`), Ergebnis-Cache pro Dateiinhalt.
- `server/integrations.py` – Weitergabe (Telegram, reMarkable, Text→PDF).
- `ui/` – Oberfläche: HTML/CSS/JS ohne Framework und ohne Build-Schritt, macOS-Optik, Dark Mode.
- `main.py` – startet Server und natives Fenster (pywebview).
- `legacy/` – Originalskript. **Nie verändern.**
- `tests/` – pytest.

## Code-Regeln

- Python 3.13 oder 3.14 (Installation und CI: 3.14; `requires-python` begrenzt nach oben), Abhängigkeiten nur über `pyproject.toml` und `uv.lock` (`uv add …`).
- **Keine neuen Abhängigkeiten ohne Rückfrage.**
- Secrets (Uni-Passwort, API-Keys, Bot-Token) nur über `keyring`. Nie in Dateien, Logs,
  API-Antworten oder Commits.
- Die API bindet nur an `127.0.0.1` und prüft bei jedem Endpunkt den Sitzungs-Token (`api`-Dependency).
- Dateipfade aus Anfragen immer über `mirror_path()` auflösen (verhindert Zugriff außerhalb des Spiegels).
- Dateien immer mit `encoding="utf-8"` lesen und schreiben.
- Protokoll über `core.log()`, nicht `print`.
- Bezeichner Englisch, Kommentare und Texte in der Oberfläche Deutsch (wie im bestehenden Code).
- Claude-Modelle: Standard `claude-opus-5-5`, wählbar Sonnet 5.5 und Haiku 5.5. Modellnamen
  und SDK-Aufrufe nur nach aktueller Dokumentation, nie raten.

## Tests

- Vor jedem Push: `.tools/uv run pytest` und `.tools/uv run ruff check .` (beides läuft auch in der CI).
- Neue Funktionen in `core/`, `server/ai.py` und neue API-Endpunkte bekommen mindestens einen Test.
- Tests nutzen den temporären Datenordner aus `tests/conftest.py` und den Schlüsselbund im
  Speicher, nie echte Daten, echte Zugangsdaten oder echte KI-Aufrufe (Anbieter per `monkeypatch` ersetzen).
- Entwicklung mit Beispieldaten: `--demo` bzw. `ILIAS_SYNC_HOME=<Ordner>`.

## Git-Workflow

- Nie direkt auf `main` arbeiten oder pushen.
- Ein Branch pro Aufgabe, Name nach Bereich: `core/…`, `ki/…`, `ui/…`, `int/…`, z. B. `ki/chatgpt`.
- Kleine Commits, ein Pull Request pro Aufgabe; gemergt wird nach dem Test am Mac.
- Jeder Pull Request verweist auf sein Issue aus `ISSUES.md` (`H<nr>`) und füllt die PR-Vorlage aus.
- Vor jedem Pull Request einmal `./"ILIAS-Sync starten.command" --demo` starten: `main` muss immer laufen.

## Arbeitsweise mit Claude Code

1. Neue Sitzung pro Aufgabe bzw. Branch.
2. Bei Änderungen über mehrere Dateien zuerst einen Plan vorlegen.
3. Abnahmekriterien des Issues am Ende einzeln prüfen und im PR abhaken.
