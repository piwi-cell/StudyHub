# Study-Tutor: nächste Schritte

## Offen aus dem ursprünglichen Prompt

- **Live-Test ElevenLabs:** Speech-to-Text, Text-to-Speech und der Gesprächsmodus sind nur mit
  nachgebauten Antworten getestet. Beim ersten echten Test die Dashboard-Schritte in SETUP.md
  prüfen (Bezeichnungen, Overrides, Tool-Einstellungen).

## Ideen für das Lerngespräch

- Gespräche speichern (Tabelle `tutor_sessions`), damit sie ein Neuladen überstehen.
- Antwort satzweise streamen und vorlesen, damit der Tutor schneller anfängt zu sprechen.
- Mit echtem Gemma testen; falls es das JSON-Format nicht hält, für das Gespräch ein größeres
  Modell (gemma3:12b) empfehlen.

## Ideen für die Automatik

- Tutor auch in die neue StudyHub-Oberfläche einbauen.
- Vorbereitung direkt im Hintergrund-Abgleich (`core/sync.py`), damit sie auch ohne offene App läuft.
- Fragen pro Kurs über mehrere Dateien statt nur pro Datei.

## Ideen für den Gesprächsmodus

- Client-Tool `search_material` (→ Volltextsuche), damit der Agent Rückfragen aus dem Material
  statt nur aus der Musterlösung beantwortet.
- Minutenlimit pro Monat, damit der Gesprächsmodus nicht unbemerkt Kosten verursacht.
- WebRTC statt WebSocket (`conversationToken` statt Signed URL), laut SDK möglich.

## Ideen

- Mikrofon im App-Fenster: pywebview müsste WebKit die Medienaufnahme freigeben
  (WKUIDelegate-Methode für Mikrofonanfragen); alternativ Aufnahme nativ in Python.
- Vektorsuche statt nur Volltextsuche für Rückfragen.
- Spaced Repetition (Fragen nach Abständen wiederholen statt nur gewichtet zufällig).
- Kostenübersicht pro Lernsitzung (Tokens und ElevenLabs-Zeichen).
- Fragen über mehrere Dateien eines Kurses hinweg.

## Getroffene Annahmen

- Standardstimme `JBFqnCBsd6RMkjVDRZzb` stammt aus den Beispielen der ElevenLabs-Doku.
- Deutsch als Sprache für Speech-to-Text (`language_code=de`).
- 6 Fragen pro Datei, höchstens ca. 40.000 Zeichen Material pro Datei.
- Gesprächsmodus: ElevenLabs ersetzt `{{course}}` im per Override geschickten Prompt durch die
  Dynamic Variable (laut SDK-Typen unterstützt, live nicht geprüft).
- Demo-Fragen verweisen alle auf Seite 1 (die Demo-PDFs sind einseitig).
