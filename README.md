# StudyHub

Mac-App (bis Version 1.0: ILIAS-Lerner) auf Basis des ILIAS-Sync-Skripts: lädt die Dateien deiner ILIAS-Kurse (Uni Mannheim)
automatisch, sortiert sie in Kursordner und macht daraus mit KI Zusammenfassungen,
Lernkarten und Antworten auf Fragen. Ergebnisse gehen per Telegram aufs Handy oder als PDF
aufs reMarkable.

**Für Nutzer:** [Anleitung](docs/anleitung.md) (Installation, was StudyHub kann, Datenschutz, Kosten, häufige Fragen).
Lizenz: Alle Rechte vorbehalten, Julius Piwaronas ([LICENSE](LICENSE)); Drittsoftware siehe
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Installieren (für Nutzer)

Voraussetzungen: macOS 13 oder neuer, Internet, ca. 300 MB. Keine Admin-Rechte, kein Xcode, kein git.
Im Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/piwi-cell/StudyHub/main/scripts/install.sh | bash
```

Alternativ aus einem heruntergeladenen und entpackten Projekt (oder Klon): `bash scripts/install.sh`.

Das Skript legt das Programm unter `~/Library/Application Support/StudyHub/app` ab und die App
unter `~/Applications/StudyHub.app` und öffnet sie. Beim ersten Start führt die Einrichtung durch
Uni-Login, Kurse und Zielordner. Protokoll: `~/Library/Logs/StudyHub.log`.

- **Aktualisieren:** App beenden und den Installationsbefehl erneut ausführen.
  Einstellungen, Dateien, Lernstand und Zugangsdaten bleiben; die Hintergrund-Jobs stellt die App beim
  nächsten Start auf die neue Fassung um. Die Version steht unter Einstellungen › Über die App.
- **Entfernen:** `bash "$HOME/Library/Application Support/StudyHub/app/scripts/uninstall.sh"` entfernt
  App, Programm und Hintergrund-Jobs. Mit `--alles` (nach Rückfrage) auch Einstellungen, geladene Dateien,
  KI-Ergebnisse und die Einträge im Schlüsselbund. Der Zielordner mit deinen Kursdateien bleibt immer.

Wo was liegt:

| Was | Ort |
|---|---|
| App | `~/Applications/StudyHub.app` |
| Programm und Python | `~/Library/Application Support/StudyHub/app` |
| Einstellungen, Spiegel der Kursdateien, KI-Ergebnisse, Lernstand | `~/Library/Application Support/ILIAS-Sync` |
| Uni-Passwort, API-Keys, Telegram-Token | Schlüsselbund, Dienst „ILIAS-Sync“ |
| Hintergrund-Jobs | `~/Library/LaunchAgents/local.ilias-sync.plist`, `local.ilias-lerner.bibliothek.plist` |
| Protokolle | `~/Library/Logs/StudyHub.log`, `ILIAS-Sync.log` |

### Umstieg von der Terminal-Version (`ilias-sync`)

Die App nutzt dieselben Daten, Zugangsdaten und denselben Hintergrund-Job (`local.ilias-sync`) wie
die Terminal-Version. Deshalb **nicht** `ilias-sync deinstallieren` ausführen: Das löscht den
gemeinsamen Datenordner (Spiegel, KI-Ergebnisse, Lernstand) und die Zugangsdaten im Schlüsselbund.
Auch `ilias-sync stop` hält den Abgleich der App an. So wird die Terminal-Version stillgelegt:

1. In der App unter Einstellungen „Automatisch abgleichen“ aus- und wieder einschalten: Der
   Hintergrund-Job läuft danach mit dem Code der App.
2. Nur den Befehl entfernen: `rm ~/.local/bin/ilias-sync`. Das alte Programm (`app/`, `venv/` im
   Datenordner) kann bleiben oder von Hand gelöscht werden.

## Als Mac-App aus dem Projektordner (Entwicklung)

```bash
bash scripts/make_app.sh
```

Erzeugt `StudyHub.app` im Projektordner; sie startet den Code aus dem Projektordner (nach einem
Umzug des Ordners neu bauen). Das Symbol liegt fertig in `assets/AppIcon.icns`; nach einer Änderung an
`assets/icon.svg` mit `bash scripts/make_icon.sh` neu erzeugen (braucht die Xcode Command Line Tools).
Hintergrund-Jobs nutzen immer den Code der zuletzt gestarteten App (installiert oder Projektordner).

## Starten (Entwicklung)

```bash
./"ILIAS-Sync starten.command"            # App öffnen (gleiche Daten wie „ilias-sync“ im Terminal)
./"ILIAS-Sync starten.command" --demo     # Vorführung (z. B. Pitch): Beispieldaten, ohne ILIAS, als „DEMO“ markiert
.venv/bin/python main.py --browser        # nur Server, Oberfläche im Browser (Entwicklung)
```

Einmalige Einrichtung (lädt uv, Python 3.13 und alle Abhängigkeiten nach `uv.lock`):

```bash
bash scripts/setup.sh
```

Tests und Lint (laufen auch in der CI):

```bash
.tools/uv run pytest
.tools/uv run ruff check .
```

## Aufbau

| Ordner | Inhalt |
|---|---|
| `legacy/` | Originalskript, unverändert (Referenz) |
| `core/` | Kern des Skripts (Abgleich, PFERD, Kurse, Telegram, GoodNotes, Notion, launchd) mit minimalen Änderungen |
| `server/app.py` | lokale API (FastAPI, nur 127.0.0.1, Sitzungs-Token), ruft nur Kernfunktionen auf |
| `server/ai.py` | KI-Schicht: Claude, ChatGPT, Gemini und Gemma hinter einer Schnittstelle, Ergebnis-Cache |
| `server/tutor.py`, `server/voice.py` | Study-Tutor: Fragen, Bewertung, Volltextsuche; Sprache über ElevenLabs (siehe `docs/tutor/`) |
| `server/studyhub.py` | Daten für die neue Oberfläche StudyHub im Format der Mock-Daten (siehe `docs/studyhub-api.md`) |
| `server/uploads.py` | Eigene Dateien hochladen (StudyHub › Dokumente), Ablage unter `<Kurs>/Eigene Dateien/` |
| `server/integrations.py` | Telegram-Versand, reMarkable (USB oder Desktop-App), Text→PDF |
| `ui/studyhub/` | Oberfläche StudyHub (HTML/CSS/JS ohne Framework, Dark Mode); `ui/vendor/` ElevenLabs-Client |
| `main.py` | startet Server und natives Fenster (pywebview/WebKit) |
| `scripts/demo_data.py` | Beispielkurse und -PDFs für die Demo |
| `scripts/setup.sh` | Entwicklungsumgebung einrichten (`--app`: ohne Test-Werkzeuge) |
| `scripts/install.sh`, `scripts/uninstall.sh` | Installieren/Aktualisieren und Entfernen für Nutzer |
| `tests/` | pytest-Tests (ohne Netz, ohne echten Schlüsselbund) |

Konfiguration, Zustand und Passwörter teilt sich die App mit der Terminal-Version
(`~/Library/Application Support/ILIAS-Sync`, Schlüsselbund „ILIAS-Sync“). Mit `--demo` oder
`ILIAS_SYNC_HOME=<Ordner>` arbeitet sie in einem eigenen Datenordner.

## KI: effizient eingesetzt

- **Ein Ergebnis pro Dateiinhalt:** Zusammenfassung und Karten werden pro SHA-256 der Datei
  gespeichert und nie doppelt erzeugt (`<Datenordner>/KI/`).
- **Text statt PDF, wo möglich:** Hat die PDF echten Text, bekommt Claude nur den Text
  (deutlich weniger Tokens). Nur gescannte Folien gehen als PDF (Bilderkennung) raus.
- **Prompt-Caching:** Das Dokument steht vorn im Prompt und ist gecacht. Folgefragen zum
  selben Dokument lesen es aus dem Cache (gemessen: 1.138 von 1.192 Tokens aus dem Cache).
- **Kosten:** Jedes Ergebnis bekommt beim Erzeugen eine Kostenschätzung nach dem Listenpreis des Tages
  (`PRICES` in `server/ai.py`, Stand 27.10.2026); Einstellungen › KI zeigt die Summe des Monats.
  Gespräche im Sprachtutor und über Claude Desktop sind nicht enthalten. Preise ändern sich: Tabelle pflegen.
- **Modellwahl:** Claude Opus 5.5 (Standard), Sonnet 5.5 oder Haiku 5.5 in den Einstellungen.
  Bei Opus und Sonnet springt bei einer Ablehnung serverseitig ein anderes Modell ein (`fallbacks: "default"`).
- **ChatGPT (OpenAI):** GPT-6 Astra, GPT-6.1 Sol (Standard) oder GPT-6 Luna, direkt über die
  Responses API ohne zusätzliches Paket. `store: false`, OpenAI speichert die Inhalte nicht;
  der Dokument-Anfang wird von OpenAI automatisch gecacht. Braucht einen API-Key von
  platform.openai.com (ein ChatGPT-Plus-Abo reicht nicht).
- **Gemini (Google):** Gemini 4 Argon (nur mit Abrechnung), Gemini 3.8 Flash (Standard) oder
  Gemini 3.5 Flash-Lite, direkt über die Gemini API ohne zusätzliches Paket. Gescannte Folien gehen als
  PDF mit (bis 20 MB). Lernkarten kommen im JSON-Modus und werden vor dem Speichern geprüft. Braucht
  einen API-Key von aistudio.google.com (derselbe Key wie für Gemma über die Gemini API).
- **Gemma 3 lokal über Ollama:** kostenlos und offline. Lange Dokumente werden abschnittsweise
  verdichtet (Map-Reduce), bei Fragen gehen nur die passendsten Abschnitte ins Modell.
  Ohne Ollama läuft Gemma 4 über die Gemini API mit einem kostenlosen Key aus Google AI Studio
  (gleiches Vorgehen, `gemma-4-26b-a4b-it` oder `gemma-4-31b-it`). Läuft Ollama, hat es Vorrang.

Zugang zu Claude: API-Key in den Einstellungen (landet im Schlüsselbund) oder `ant auth login`.
Gemma: Ollama-App von ollama.com/download installieren, dann im Terminal `ollama pull gemma3:4b`, oder einen API-Key von
aistudio.google.com unter Einstellungen › KI › Gemma (Gemini API) speichern (Schlüsselbund).

## Bekannte Grenzen

- GoodNotes-Import braucht Goodnotes für Mac ab macOS 15.7.
- reMarkable hat keine offizielle Schnittstelle: Upload per USB-Webinterface (10.11.99.1)
  oder Übergabe an die reMarkable-App für macOS.
- Fragen gehen an ein Dokument, nicht an alle Kurse zugleich (dafür wäre eine Vektor-Suche nötig).
- Notion-Einrichtung nur in der Terminal-Version (`ilias-sync module`); die App zeigt Notion nur, wenn eingerichtet.
- Nur macOS (launchd, Schlüsselbund, osascript).
- Getestet auf Apple-Silicon-Macs mit macOS 14; macOS 13 und Intel-Macs sind ungeprüft.

## Änderungen am Kern gegenüber `legacy/`

- `core.py`: Datenordner über `ILIAS_SYNC_HOME` umschaltbar, Python-Pfad über
  `ILIAS_SYNC_PYTHON`, Protokoll auch aus der App heraus (`ILIAS_SYNC_APP`).
- `cli.py`: Fehler in `last_sync_line()` behoben (Logzeile an falscher Stelle abgeschnitten).
- `pferd_runner.py`: `KeyError` behoben, wenn ein bekannter Kurs leere Einstellungen hat.
- `core.update_config()`: Abgleich (neue Kurse) und Notion speichern nur ihre Änderung in die frisch geladene
  Konfiguration, statt die Kopie vom Start des Abgleichs zurückzuschreiben (Einstellungen gingen sonst verloren).
- `core.moved_path()`: Hilfe für das Umbenennen von Kursen (StudyHub zieht Lernstand und KI-Ergebnisse mit).
- Mitteilungen und Telegram-Texte heißen StudyHub statt ILIAS-Sync.
