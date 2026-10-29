# StudyHub – Design-Prototyp (Soft Glass)

Klickbarer Prototyp für das Demo-Video. Läuft komplett mit Beispieldaten,
ohne Server und ohne Build-Schritt.

## Öffnen

- **Nur Design (Beispieldaten):** Doppelklick auf `index.html`.
- **Mit echten Daten:** App starten (`.venv/bin/python main.py --demo --browser` oder ohne `--demo`),
  dann in der klassischen Ansicht links unten auf **„✦ Neue Oberfläche: StudyHub“** klicken.
  StudyHub läuft dann unter `/ui/studyhub/index.html?t=<Sitzungs-Token>`.

## Echte Daten (`js/live.js`)

Mit Sitzungs-Token holt StudyHub alles aus der lokalen API (`server/app.py`, Format: `docs/studyhub-api.md`):

| Bereich | Quelle |
|---|---|
| Register, Module, Startseite, alle Tabs | `GET /api/studyhub` (ersetzt `DATEN` und `MODUL_DETAILS`) |
| Lernplan-Status und Notizen: bei echten Kursen im Tab „Dokumente“ (Haken = erledigt, Chip für „in Arbeit“ / „nochmal üben“); ein eigener Tab „Lernplan“ nur im Beispielmodul | `PATCH /api/studyhub/lernplan` (gespeichert auf dem Server) |
| Top-Bar: Synchronisieren | `/api/sync`, danach `/api/status` bis fertig (im Demo-Modus nur simuliert) |
| Dokumente öffnen | `/api/open` |
| Lernthema (Kernidee, Formeln, Klausurfalle, Einfacher erklären) | `/api/ai/run` mit `task: "thema"` |
| Karteikarten erstellen | `/api/ai/run` mit `task: "flashcards"` |
| Sprachtutor „Frage für Frage“ | `/api/tutor/*` inkl. ElevenLabs (Vorlesen, Push-to-Talk) |
| Sprachtutor „Gespräch mit dem Tutor“ | ElevenLabs Agent über `/api/tutor/agent-session` und das SDK in `ui/vendor/`, Client-Tools `get_next_question` / `record_result` wie in `ui/tutor.js` |
| Top-Bar: „✦ Claude“ (Lerncoach in Claude Desktop über den MCP-Server) | `POST /api/claude/open` |
| Karteikarten mit Lernstand (SM-2), Anki, Textdateien | `/api/cards/*`, `/api/anki/*` |
| Klausurtermin im Modulkopf | `PATCH /api/studyhub/klausur` |
| Seite „Bibliotheken“ (`js/bibliotheken.js`): Auslastung der UB, Verlauf je Wochentag, Telegram-Bot (`/bib`, Meldungen voll/wieder Platz) | `/api/libraries*`, `/api/telegram/connect` |
| Eigene Zusammenfassungen (schreiben, hochladen) | `POST /api/summaries`, `POST /api/upload` mit `art=zusammenfassung` |
| Mikrofon aus dem App-Fenster | `POST /api/studyhub/open-browser` öffnet StudyHub an derselben Stelle im Browser |
| Seiten „Kurse“ und „Einstellungen“ (`js/einstellungen.js`) | `/api/courses`, `/api/settings`, `/api/account`, `/api/ai/providers`, `/api/telegram/*` |

Finanzmathematik bleibt nur im Demo-Modus (`--demo`) als **Beispielmodul** sichtbar, mit echten Daten nicht.
Karten-Bewertungen speichert der Server (SM-2): geübt werden fällige und neue Karten; „Nochmal“ markiert zusätzlich den Lernplan.
Das Mikrofon geht nur im Browser, nicht im nativen App-Fenster.

## Was drin ist

- **Top-Bar:** Suche (⌘K), ILIAS-Status, simuliertes „Synchronisieren“
- **Register links:** Semester, Module mit Lernstand, „+ Modul aus ILIAS hinzufügen“
- **Startseite:** Begrüßung, nächste Klausur, „Heute dran“, Modul-Kacheln
- **Modul Finanzmathematik** mit Tabbar `Übersicht │ Dokumente Lernplan ┃ Zusammenfassung Karteikarten Sprachtutor +`
  - **Übersicht:** Widgets für Lernplan, Karteikarten, Zusammenfassung, Dokumente
  - **Dokumente:** gruppiert nach Vorlesung, Tutorium, Übung & Zusatz, mit „neu“-Badge
  - **Lernplan:** Gesamtfortschritt, Filter, Status antippen (offen → in Arbeit → erledigt → nochmal üben),
    Notizen, Tutorien/Übungen aufklappbar mit Mini-Balken
  - **Zusammenfassung:** Themenliste mit Ampel, Kernidee, Formeln, Klausurfalle, Quelle;
    Aktionen Karten erstellen, Abfragen lassen, Einfacher erklären, Vorlesen
  - **Karteikarten:** Themen-Filter, Antwort zeigen, Nochmal / Schwer / Gewusst
    (Tastatur: Leertaste, 1, 2, 3). „Nochmal“ markiert den Eintrag im Lernplan.
  - **Sprachtutor:** Demo-Gespräch mit Mikrofon-Knopf, Stimme vorerst vom Browser
  - **+ Skill hinzufügen:** Probeklausur, Formelsammlung, Mindmap, Glossar, Übungsaufgaben.
    Hinzugefügte Skills erscheinen als eigener Tab. Ohne Zusammenfassung sind abhängige Skills ausgegraut
    (zum Zeigen: Knopf „Ansicht ohne Zusammenfassung“).

## Dateien

| Datei | Inhalt |
|---|---|
| `css/styles.css` | Alle Design-Tokens als CSS-Variablen ganz oben, danach die Komponenten |
| `js/daten.js` | Mock-Daten (Semester, Module, Finanzmathematik mit Lernplan, Themen, Karten, Tutor) |
| `js/icons.js` | Linien-Icons als SVG |
| `js/live.js` | Anbindung an die echte App (`/api/studyhub`, KI, Sprachtutor, Lernplan speichern) |
| `js/einstellungen.js` | Seiten „Kurse“ und „Einstellungen“ im StudyHub-Design |
| `js/app.js` | Seiten, Tabs, Navigation (`#/modul/fima/uebersicht`) und Klicks |

Bereich: Oberfläche. In der klassischen Oberfläche kommt nur der Link zu StudyHub dazu
(`ui/index.html`, `ui/app.js`, `ui/style.css`). Server und Kern bleiben unverändert.
