# Study-Tutor einrichten (macOS)

1. **Gehirn wählen:** App › Einstellungen › Study-Tutor › „Gehirn des Tutors“.
   - **Claude** oder **ChatGPT**: verlässliche Bewertung, braucht den jeweiligen Zugang
     (Anthropic-Key oder `ant auth login`; OpenAI-Key).
   - **Gemma**: kostenlos und offline. Ollama installieren (`brew install --cask ollama-app`),
     dann ein Modell laden. Für brauchbare Bewertungen mindestens `ollama pull gemma3:4b`
     (3,3 GB); `gemma3:270m` reicht nur zum Ausprobieren.
   - **Gemma ohne Ollama:** Auf aistudio.google.com einen API-Key anlegen und unter
     Einstellungen › KI › „Gemma (Gemini API)“ speichern. Kostenloses Kontingent bei Google;
     Ollama hat Vorrang, wenn es läuft.
2. **Sprache (optional):** Auf elevenlabs.io einen API-Key anlegen und unter Einstellungen ›
   Study-Tutor › ElevenLabs-API-Key speichern (landet im Schlüsselbund). Eine andere Stimme:
   Voice-ID aus der ElevenLabs-Stimmenbibliothek eintragen.
3. **Fragen entstehen automatisch:** Ist Gemma lokal (Ollama) eingerichtet, erzeugt die App im Hintergrund
   Fragen zu allen Kursdateien (auch zu neuen nach jedem Abgleich). Fortschritt: Übersicht ›
   Karte „Study-Tutor“. Abschalten: Einstellungen › Study-Tutor › „Fragen automatisch vorbereiten“.
   Mit Gemma über die Gemini API läuft das bewusst nicht automatisch (das würde das kostenlose
   Kontingent auf einmal aufbrauchen); dann „Material vorbereiten“ pro Kurs von Hand.
4. **Gesprächsmodus (optional, ElevenLabs Agent):** siehe Abschnitt unten.
5. **Material von Hand vorbereiten (ohne Gemma oder mit anderem Gehirn):** Tutor › Material › Kurs wählen › „Fragen erzeugen“. Pro Datei entstehen 6 Fragen.
6. **Lernen:** Übersicht › „Tutor starten“ oder links „Tutor“.
   - **Gespräch** (Umschalter oben bzw. in StudyHub „Lerngespräch“): Der Tutor redet frei mit dir,
     stellt eigene Fragen aus den Folien, gibt bei falschen Antworten erst einen Hinweis,
     beantwortet Fragen wie „Erklär mir die goldene Bilanzregel“ und wechselt mit „Lass uns
     Statistik machen“ das Thema. Am besten mit Claude oder ChatGPT als Gehirn.
   - **Abfrage**: wie bisher Frage für Frage aus dem Fragenpool.
   - Im App-Fenster: Antwort tippen, Feedback lesen (und hören, wenn „Vorlesen“ an ist).
   - Mit Mikrofon: „Mit Sprache im Browser öffnen“. Im Browser den Mikrofonzugriff erlauben,
     dann den Knopf oder die Leertaste gedrückt halten, sprechen, loslassen.

**Schnell testen ohne eigenes Material:** `./"ILIAS-Sync starten.command" --demo` legt 10 feste
Demo-Fragen an (Financial Accounting, Mikroökonomik A, Statistik I). Der Tutor fragt sofort ab,
ohne dass ein Gehirn erst Fragen erzeugt.

## Gesprächsmodus mit ElevenLabs Agent einrichten

Im Gesprächsmodus führt ein ElevenLabs Agent ein freies Gespräch (mit Unterbrechen). Er holt
sich Frage und Musterlösung aus der App, bewertet selbst und speichert das Ergebnis in der App.
Kosten entstehen bei ElevenLabs pro Gesprächsminute, je nach Tarif.

> Die Bezeichnungen im ElevenLabs-Dashboard können sich ändern. Diese Anleitung wurde
> ohne Zugriff auf die ElevenLabs-Webseite geschrieben (nur anhand des offiziellen SDKs);
> beim ersten Einrichten bitte Abweichungen hier korrigieren.

1. **Agent anlegen:** elevenlabs.io › Agents › neuen, leeren Agent anlegen. Sprache Deutsch,
   Stimme nach Wahl. Prompt und erste Nachricht können leer bleiben, die App schickt beides mit.
2. **Authentifizierung einschalten:** Der Agent soll nur mit Signed URL erreichbar sein
   (Einstellung zur Authentifizierung bzw. „private agent“). Die App holt die Signed URL lokal
   mit dem ElevenLabs-API-Key.
3. **Overrides erlauben** (Sicherheits-Einstellungen des Agents): **System-Prompt**,
   **erste Nachricht** und **Sprache**. Ohne diese Freigaben bricht das Gespräch beim Start ab.
4. **Zwei Client-Tools anlegen** (Tools › Client-Tool), Namen exakt so:

   | Name | Beschreibung | Parameter | „Auf Antwort warten“ |
   |---|---|---|---|
   | `get_next_question` | Holt die nächste Prüfungsfrage mit Musterlösung und Quelle. | keine | an |
   | `record_result` | Speichert die Bewertung der letzten Antwort. | `answer` (String, Antwort in Stichworten), `verdict` (String: `correct`, `partial` oder `wrong`), `feedback` (String, 1–2 Sätze) | an |

5. **Agent-ID eintragen:** Die ID (`agent_…`) aus dem Dashboard kopieren und in der App unter
   Einstellungen › Study-Tutor › „ElevenLabs Agent-ID“ speichern. Der ElevenLabs-API-Key muss
   ebenfalls hinterlegt sein.
6. **Testen:** Tutor im Browser öffnen („Mit Sprache im Browser öffnen“) › „🗣 Gespräch starten“ ›
   Mikrofon erlauben. Oben zeigt ein Kreis „Tutor spricht“ bzw. „Tutor hört zu“; Bewertungen
   erscheinen wie gewohnt als ✓ / 💡 / ✗.

**Fehlersuche:** Die Tutor-Ansicht zeigt, ob das Gehirn bereit ist; Fehlermeldungen von
Ollama, Claude, OpenAI und ElevenLabs erscheinen als Hinweis unten im Fenster.
Gesprächsmodus: „Agent nicht gefunden“ → Agent-ID prüfen; Gespräch bricht direkt ab → Overrides
(Schritt 3) freigeben; Agent stellt keine Fragen → Tool-Namen (Schritt 4) exakt prüfen.
