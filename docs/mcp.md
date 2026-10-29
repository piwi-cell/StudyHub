# StudyHub in Claude Desktop (MCP)

Mit dem MCP-Server übernimmt **Claude Desktop** die KI-Arbeit der App. Es zählt dein normales
Claude-Abo (Pro oder Max), in der App ist **kein API-Key** nötig und es entstehen keine API-Kosten.

So funktioniert es: Claude Desktop startet `server/mcp_server.py` selbst im Hintergrund und
spricht über stdin/stdout mit ihm. Claude kann damit deine Kursunterlagen lesen und fertige
Lernthemen und Lernkarten in der App speichern. StudyHub zeigt sie danach wie selbst erzeugte
Ergebnisse an.

## Werkzeuge

| Werkzeug | Was es tut |
|---|---|
| `list_courses` | Kurse mit Anzahl der Dateien, Lernthemen und Lernkarten |
| `list_files` | Dateien mit KI-Status (wie `/api/files`) und Zahl der Tutor-Fragen (`tutor_fragen`), Filter nach Kurs oder Namensteil, höchstens 500 |
| `read_file` | Text einer PDF- oder Textdatei mit `[Seite n]`; lange Dokumente in Teilen (`start_page`) |
| `view_pages` | Seiten einer PDF als Bilder (höchstens 4 pro Aufruf), für Inhalte ohne Text: gescannte Folien, Grafiken, Kästen als Bild; nur in der Mac-App |
| `read_ai_results` | schon gespeicherte Ergebnisse einer Datei (Lernthema, Lernkarten, Zusammenfassung) |
| `studyhub_overview` | Lernplan mit Status, vorhandene Lernthemen, Dateien ohne Lernthema |
| `save_thema` | speichert ein Lernthema (Felder wie `THEMA_SCHEMA` in `server/ai.py`), dazu eine Markdown-Zusammenfassung daraus (siehe unten) |
| `save_summary` | speichert eine eigene Markdown-Zusammenfassung (Abschnitte „Worum es geht“, „Kernaussagen“, „Wichtige Begriffe“, „Prüfungsrelevant“, weitere erlaubt; höchstens 30.000 Zeichen); ersetzt eine aus dem Lernthema erzeugte, eine eigene nur mit `overwrite` |
| `save_flashcards` | speichert Lernkarten (wie `FLASHCARD_SCHEMA`, 1–40 Karten) |
| `save_tutor_questions` | speichert Prüfungsfragen mit Musterlösung und Seite für den Sprachtutor (`tutor.sqlite3`), 1–20 pro Aufruf |

**Zusammenfassung zum Lernthema:** `save_thema` legt aus dem Lernthema zusätzlich eine Markdown-
Zusammenfassung an (Abschnitte „Worum es geht“, „Kernaussagen“, „Wichtige Begriffe“, „Prüfungsrelevant“).
Eine vorhandene Zusammenfassung von Claude, ChatGPT oder Gemma bleibt dabei unangetastet.

Grenzen, die der Server selbst durchsetzt:

- Lesen nur aus dem Spiegel-Ordner, Pfade laufen über `mirror_path()` (kein `../`, keine Dateien außerhalb).
- Schreiben nur in den KI-Cache der jeweiligen Datei. Ein vorhandenes Ergebnis wird nur mit
  `overwrite=true` ersetzt.
- Tutor-Fragen werden nie gelöscht oder ersetzt: Hat eine Datei schon Fragen, kommen neue nur
  mit `add=true` dazu. Bisherige Antworten und Bewertungen bleiben erhalten.
- Keine Werkzeuge zum Löschen, Senden (Telegram, reMarkable), für Einstellungen oder Zugangsdaten.
  Rückgaben enthalten keine Secrets.
- Claude Desktop fragt vor jedem Werkzeugaufruf nach deiner Erlaubnis (lässt sich pro Werkzeug freigeben).

## Einrichtung

1. Claude Desktop installieren (claude.com/download) und anmelden. Es zählt dein Claude-Abo.
2. In StudyHub unter **Einstellungen › KI › Claude Desktop** auf **Einrichten** klicken. Die App
   trägt den Server „studyhub“ in `~/Library/Application Support/Claude/claude_desktop_config.json`
   ein. Andere Einträge dort bleiben unverändert; eine unlesbare Datei überschreibt die App nicht.
3. Claude Desktop komplett beenden (⌘Q) und neu öffnen. Im Chat-Eingabefeld zeigt das
   Werkzeug-Menü jetzt „studyhub“ mit zehn Werkzeugen.

Steht dort „Aktualisieren“, gehört der Eintrag zu einem anderen Programmordner (z. B. dem Projektordner
oder einer früheren Installation). Ein Klick stellt ihn auf die gerade laufende App um. Die Demo
(`--demo`) trägt den Server mit Beispieldaten ein.

### Von Hand (Entwicklung)

Ohne App, z. B. für einen Projektordner: In Claude Desktop **Einstellungen › Entwickler › Konfiguration
bearbeiten** öffnen und unter `mcpServers` eintragen (vorhandene Einträge behalten). `PROJEKT` ist der
absolute Pfad zum Projektordner (`pwd` darin), bei einer Installation mit `scripts/install.sh`
`/Users/<Name>/Library/Application Support/StudyHub/app` (steht auch unter Einstellungen › Über die App).

```json
{
  "mcpServers": {
    "studyhub": {
      "command": "PROJEKT/.venv/bin/python",
      "args": ["PROJEKT/server/mcp_server.py"]
    }
  }
}
```

Für die Beispieldaten `"--demo"` als zweites Element in `args` anhängen. In beiden Feldern absolute
Pfade, kein `~`: Claude Desktop startet den Server nicht im Projektordner.

Echte Daten und Demo-Daten nutzen dieselben Ordner wie die App: ohne `--demo`
`~/Library/Application Support/ILIAS-Sync`, mit `--demo` `./demo-data`.

## Ausprobieren

In Claude Desktop zum Beispiel schreiben:

> Erstelle für Statistik I ein Lernthema aus 07 Hypothesentests.pdf und speichere es.

Claude sucht die Datei (`list_files`), liest sie (`read_file`) und speichert das Ergebnis
(`save_thema`). Danach StudyHub neu laden (⌘R): Unter **Statistik I › Zusammenfassung** steht das
neue Thema.

Weitere Beispiele:

> Welche Dateien in Financial Accounting haben noch kein Lernthema? Erstelle für alle eins.

> Mach mir 15 Lernkarten aus der Mikroökonomik-Vorlesung 05 und speichere sie.

### Fragen für den Sprachtutor

Der Study-Tutor (Abfragen per Text oder Sprache und der Gesprächsmodus mit dem ElevenLabs Agent)
fragt aus einem Pool von Prüfungsfragen ab. Ohne Gemma, Claude-API-Key oder ChatGPT-Key kann die
App diese Fragen nicht selbst erzeugen („0 neue Fragen vorbereitet“). Claude Desktop übernimmt das:

> Bereite für alle Dateien in Statistik I je 6 Tutor-Fragen vor und speichere sie mit save_tutor_questions.

Danach StudyHub neu laden: Unter **Sprachtutor** zählt der Kurs die neuen Fragen, und auch der
ElevenLabs Agent holt sich seine Fragen und Musterlösungen aus diesem Pool (`get_next_question`).

**Gescannte Folien und Inhalte als Bild** (z. B. ausgedruckte Webseiten, bei denen der Text nur
Kopf- und Fußzeilen enthält): `read_file` meldet „kaum Text gefunden“, oder der Text passt erkennbar
nicht zum Dateinamen. Dann sieht Claude die Seiten mit `view_pages` als Bilder an (gerendert mit
Quartz von macOS, längste Kante 1568 Pixel) und speichert das Ergebnis wie gewohnt mit `save_thema`.

### Lerncoach direkt aus der App

In StudyHub oben rechts auf **✦ Claude** klicken. Die App öffnet Claude Desktop über den offiziellen
Link `claude://claude.ai/new?q=…` mit einem neuen Chat, in dem der Auftrag schon im Eingabefeld
steht (abschicken mit ↩). Der Auftrag sagt Claude, woher die Unterlagen kommen (App StudyHub,
MCP-Server `studyhub` auf diesem Mac), welche Werkzeuge es gibt und dass es als Coach arbeiten
soll: erst Überblick mit `studyhub_overview`, dann eine Frage auf einmal, Hinweis vor Lösung,
Speichern nur nach Rückfrage. Auf einer Modulseite steht der Kurs gleich mit drin.

Ist der Server noch nicht in `claude_desktop_config.json` eingetragen, öffnet sich Claude trotzdem
und StudyHub meldet „MCP-Server „studyhub“ fehlt noch“. Denselben Auftrag gibt es in Claude
Desktop auch ohne die App: **+ › studyhub › Lerncoach** (MCP-Prompt `lerncoach`, Kurs optional).

## Testen ohne Claude Desktop

Mit dem MCP Inspector (braucht Node.js) die Werkzeuge im Browser aufrufen:

```bash
npx @modelcontextprotocol/inspector "$PWD/.venv/bin/python" "$PWD/server/mcp_server.py" --demo
```

Im Projektordner ausführen. Im Inspector **Connect**, dann **Tools › List Tools**.

Automatische Tests: `tests/test_mcp_server.py` (läuft mit `.tools/uv run pytest`, startet den
Server dabei auch einmal über stdio wie Claude Desktop).

## Wenn es nicht klappt

| Problem | Lösung |
|---|---|
| „studyhub“ taucht nicht auf | Einstellungen › KI › Claude Desktop prüfen (muss „bereit“ zeigen), Claude Desktop mit ⌘Q beenden und neu starten |
| Server startet nicht | Protokoll: `~/Library/Logs/Claude/mcp-server-studyhub.log`; meist stimmt ein Pfad nicht (in der App „Aktualisieren“) oder im Projektordner fehlt `.tools/uv sync` |
| „Datei nicht gefunden“ | Pfad genau wie in `list_files` angeben (mit Kurs- und Ordnername) |
| „gibt es schon ein Ergebnis“ | Claude bitten, mit `overwrite` zu ersetzen |
| „hat schon … Tutor-Fragen“ | Claude bitten, mit `add` weitere Fragen dazuzunehmen |
| Thema fehlt in StudyHub | StudyHub neu laden (⌘R); App und Claude Desktop müssen denselben Datenordner nutzen (beide mit oder beide ohne Demo) |
