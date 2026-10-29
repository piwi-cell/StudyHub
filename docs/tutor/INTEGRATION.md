# Study-Tutor: Integration

Basisversion des „Sprechenden Study-Tutors“ aus `docs/voice-tutor-prompt.md`, angepasst an
den Hackathon-Stand (macOS, `core/` + `server/` + `ui/` statt `src/`).

## Was das Feature tut

1. **Material vorbereiten:** Text pro Seite in eine SQLite-Volltextsuche (FTS5). Das Gehirn
   erzeugt pro Datei 6 Fragen mit Musterlösung und Seitenzahl. Unveränderte Dateien werden
   nicht erneut verarbeitet.
2. **Abfragen:** Der Code wählt die nächste Frage zufällig. Neue Fragen kommen dreimal so oft,
   falsch oder halb beantwortete doppelt so oft wie richtig beantwortete.
3. **Bewerten:** Das Gehirn vergleicht mit der Musterlösung → `correct | partial | wrong` und
   1–2 Sätze Feedback (✓ / 💡 / ✗). Das Ergebnis landet in `results`.
4. **Rückfragen:** Antwort nur aus der Quellseite und den passendsten Treffern der Volltextsuche,
   mit Quelle („Datei, S. n“).
5. **Sprache (ElevenLabs):** Push-to-Talk → Speech-to-Text (`scribe_v2`); Fragen und Feedback
   per Text-to-Speech (`eleven_multilingual_v2`, MP3). Der Key bleibt auf dem lokalen Server.
6. **Gesprächsmodus (ElevenLabs Agent):** Der Server holt eine Signed URL, der Browser startet
   mit dem offiziellen JavaScript-SDK das Gespräch. System-Prompt (`tutor.AGENT_PROMPT`) und erste
   Nachricht gehen als Override mit, der Kurs als Dynamic Variable `{{course}}`. Der Agent bewertet
   selbst gegen die Musterlösung; die Client-Tools `get_next_question` und `record_result` rufen
   im Browser `/api/tutor/next?solution=true` und `/api/tutor/record` auf. Keine Webhooks.
7. **Demo-Fragen:** `--demo` legt 10 feste Fragen zu den Demo-PDFs an (`tutor.add_fixed_questions`).
8. **Freies Lerngespräch (Push-to-Talk):** `POST /api/tutor/chat` mit `tutor.converse()`. Der
   Browser hält den Verlauf und schickt ihn bei jedem Beitrag mit (höchstens 60 Beiträge, das
   Gehirn sieht die letzten 12). Der Code sucht passende Folienstellen (Volltextsuche, sonst
   zufällige Seiten des Kurses) und bis zu 3 noch nicht gekonnte Pool-Fragen; das eingestellte
   Gehirn antwortet als JSON (`say`, `kind`, `verdict`, `question`, `solution`, `ref`, `course`).
   Eigene Fragen des Tutors landen im Pool (`brain = "chat"`), Bewertungen über `record()` in
   `results`. Bei falscher Antwort gibt der Tutor erst einen Hinweis (kein Eintrag), dann bewertet
   er. Kurswechsel per Sprache: zweiter Aufruf mit dem Material des neuen Kurses.
   Oberfläche: Umschalter „Abfrage | Gespräch“ in der Tutor-Ansicht, Knopf „Lerngespräch“ im
   StudyHub-Sprachtutor.
9. **Automatische Vorbereitung:** Beim App-Start, alle 10 Minuten und nach jedem Abgleich aus der
   App bereitet ein Hintergrund-Thread alle Kursdateien (PDF, TXT, MD) ohne Fragen vor, immer mit
   Gemma (kostenlos), egal welches Gehirn eingestellt ist. Unbrauchbare Dateien (gescannt,
   unlesbar) stehen in der Tabelle `skipped` und werden erst nach einer Änderung neu versucht.
   Abschaltbar unter Einstellungen › Study-Tutor (`tutor_auto` in `config.json`, Standard an).
   Auf der Übersicht zeigt eine Karte die Zahl der Fragen mit „Tutor starten“.

## Abweichungen vom Prompt (bewusst)

| Prompt | Umgesetzt | Grund |
|---|---|---|
| `src/app_core/tutor/`, `src/app_ui/tutor/` | `server/tutor.py`, `server/voice.py`, `ui/tutor.js` | Projektstruktur laut CLAUDE.md |
| nur Gemma + ElevenLabs-Agent als Gehirne | Gemma (Standard), Claude, ChatGPT | Gemma 3 270M bewertet unbrauchbar (live getestet: richtige Antwort als „wrong“, Feedback wiederholt die Anweisung). Claude/ChatGPT kommen aus der vorhandenen KI-Schicht, kein Mehraufwand. |
| `config.toml`, Migrationen | `config.json` (`tutor_brain`, `voice_id`), `tutor.sqlite3` mit `CREATE … IF NOT EXISTS` | bestehende Konfiguration |
| CLI `app tutor setup` / `check` | Einstellungen › Study-Tutor, Status in der Tutor-Ansicht | die App hat keine solche CLI |
| Push-to-Talk im App-Fenster | im Standardbrowser | pywebview gibt WebKit kein Mikrofon frei (`navigator.mediaDevices` fehlt, getestet). Vorlesen klappt im Fenster. |
| Agent bewertet über unser Gehirn | Agent bewertet selbst (bekommt die Musterlösung) | schneller und natürlicher; Gemma bewertet unzuverlässig (Teamentscheidung) |
| Windows-Doku, englische Kommentare | nur macOS, Deutsch | CLAUDE.md (Hackathon-Stand) |

## Geänderte bestehende Dateien

| Datei | Änderung |
|---|---|
| `server/ai.py` | `_claude_send()` und `_openai_send()` aus `_claude()`/`_openai()` herausgezogen (gleiches Verhalten); neue Funktion `complete()` für kurze Anfragen an jeden Anbieter; `num_predict` begrenzt Gemma-Ausgaben (270M lief bei JSON-Vorgabe sonst endlos) |
| `server/app.py` | Einstellungen `tutor_brain`, `voice_id`, `elevenlabs_key`; Endpunkte unter `/api/tutor/…` angehängt |
| `ui/index.html` | Navigationspunkt „Tutor“, Ansicht, `tutor.js` |
| `ui/app.js` | Ansicht registriert, ⌘1–6, Einstellungsblock „Study-Tutor“, `#tutor` öffnet direkt den Tutor |
| `ui/style.css` | Styles für den Tutor; Kreis „Tutor spricht / hört zu“ |
| `server/voice.py` | `signed_url()` für den Gesprächsmodus |
| `server/tutor.py` | `record()` aus `grade()` herausgezogen (gleiches Verhalten); `add_fixed_questions()`; `next_question(with_solution=…)`; einzige Frage wird wiederholt statt „keine Fragen“; `AGENT_PROMPT` |
| `server/app.py` (Agent) | Einstellung `agent_id`, `agent_ready` im Status, `/api/tutor/agent-session`, `/api/tutor/record`, `?solution=true` bei `/api/tutor/next` |
| `ui/tutor.js` (Agent) | „Gespräch starten“, Client-Tools, SDK wird erst beim Start geladen |
| `ui/app.js` (Agent) | Einstellung „ElevenLabs Agent-ID“ |
| `server/app.py` (Automatik) | Hintergrund-Thread über FastAPI-`lifespan`; nach `/api/sync` wird er geweckt; Einstellung `tutor_auto`; `auto` im Tutor-Status |
| `ui/app.js` (Automatik) | Karte „Study-Tutor“ auf der Übersicht, Schalter in den Einstellungen |
| `server/app.py` (Gespräch) | Endpunkt `/api/tutor/chat` angehängt; `Field` aus pydantic importiert |
| `ui/tutor.js`, `ui/style.css` (Gespräch) | Umschalter „Abfrage \| Gespräch“, Chat-Verlauf |
| `ui/studyhub/js/live.js` (Gespräch) | Knopf „Lerngespräch“, `chatStarten/chatSenden/chatBeenden`; „Gespräch starten“ heißt jetzt „Frage für Frage“ |
| `scripts/demo_data.py` | `DEMO_QUESTIONS` und `seed_tutor()` (läuft bei jedem Demo-Start, legt nichts doppelt an) |

## Neu

- **Dateien:** `server/tutor.py`, `server/voice.py`, `ui/tutor.js`, `tests/test_tutor.py`
- **Abhängigkeiten (Python):** keine (SQLite/FTS5 ist in Python enthalten, HTTP über das vorhandene `httpx2`)
- **Abhängigkeit (Browser):** `@elevenlabs/client` 1.27.0 (MIT), unverändert abgelegt unter
  `ui/vendor/elevenlabs-client-1.27.0/` (ca. 1,1 MB, kein Build-Schritt, kein CDN). Im Team
  abgestimmt; Herkunft und Prüfsumme in der README daneben.
- **Tabellen** in `<Datenordner>/tutor.sqlite3`: `files`, `pages` (FTS5), `questions`, `results`, `skipped`
- **Schlüsselbund:** Konto „ElevenLabs-API-Key“ im Dienst „ILIAS-Sync“

## API

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/tutor/status?course=` | Zähler, Gehirn, bereit? |
| POST | `/api/tutor/prepare` `{path}` | eine Datei vorbereiten |
| GET | `/api/tutor/next?course=&exclude=` | nächste Frage |
| POST | `/api/tutor/answer` `{question_id, text}` | bewerten |
| POST | `/api/tutor/ask` `{question_id, text}` | Rückfrage |
| POST | `/api/tutor/transcribe` (Audio-Body) | Speech-to-Text |
| POST | `/api/tutor/speak` `{text}` | Text-to-Speech, liefert MP3 |
| GET | `/api/tutor/next?solution=true` | nächste Frage mit Musterlösung (für den Agent) |
| POST | `/api/tutor/chat` `{text, history, course, question_id}` | ein Beitrag im freien Lerngespräch |
| POST | `/api/tutor/record` `{question_id, answer, verdict, feedback}` | Bewertung des Agents speichern |
| POST | `/api/tutor/agent-session` `{course}` | Signed URL, Prompt, erste Nachricht, Dynamic Variables |
| POST | `/api/tutor/open-browser` | Tutor im Standardbrowser öffnen |

## Ein- und ausschalten

Der Tutor ist ein eigener Menüpunkt. Im Hintergrund läuft nur die automatische Vorbereitung
(abschaltbar, siehe oben; ohne Gemma tut sie nichts). Ohne ElevenLabs-Key
funktioniert er per Tastatur; ohne vorbereitetes Material zeigt er die Vorbereitungs-Seite.

## Bekannte Einschränkungen

- Mit Gemma 3 270M sind Fragen brauchbar, Bewertung und Rückfragen nicht (Hinweis in der App).
- Gescannte Folien ohne Text werden übersprungen.
- Pro Datei gehen höchstens ca. 40.000 Zeichen in die Fragenerzeugung.
- ElevenLabs live noch nicht getestet (kein Key im Team zum Testzeitpunkt). Gesprächsmodus:
  Oberfläche, SDK-Laden und Client-Tools im Browser getestet, das echte Gespräch nicht.
- Gesprächsmodus nur im Browser (wie Push-to-Talk), nicht im App-Fenster.
- Im Gesprächsmodus sieht der Agent die Musterlösung; die Bewertung hängt am LLM, das im
  ElevenLabs-Dashboard für den Agent eingestellt ist.
- Rückfragen beantwortet der Agent nur aus der Musterlösung, nicht per Volltextsuche.
- Automatik: Dateien, die der Hintergrund-Abgleich (launchd) lädt, während die App geschlossen
  ist, werden beim nächsten App-Start bzw. spätestens nach 10 Minuten vorbereitet. Mit Gemma
  dauert eine Datei je nach Mac und Modell etwa eine halbe bis mehrere Minuten.
- Lerngespräch: Qualität hängt stark am Gehirn. Gemma 4B führt das Gespräch holprig (hält das
  JSON-Format nicht immer ein, bewertet zu großzügig); Claude oder ChatGPT deutlich besser,
  kosten aber pro Beitrag einen Aufruf. Mit echtem Gemma nicht getestet.
- Lerngespräch: Der Verlauf liegt nur im Browser; nach Neuladen beginnt ein neues Gespräch.
