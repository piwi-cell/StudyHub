# Prompt für Claude Code: Feature „Sprechender Study-Tutor“ (Basisversion)

> **Anleitung fürs Team:** Öffne Claude Code im Root-Ordner unseres Projekts (dort, wo `CLAUDE.md` und `pyproject.toml` liegen). Kopiere alles ab der Linie unten und füge es als erste Nachricht ein. Claude arbeitet in Etappen und wartet nach jeder Etappe auf dein OK. API-Keys gibst du nie im Chat ein, sondern nur über `app tutor setup`.

---

Du arbeitest in unserem bestehenden Projekt. Bau eine **einfache Basisversion** des Features „Sprechender Study-Tutor“ in das vorhandene Gerüst ein. Ziel ist ein sauberes Fundament, auf dem das Team später aufbaut. Halte alles so einfach wie möglich: keine Extras, keine vorzeitigen Optimierungen.

## 0. Projekt verstehen (noch kein Code)

- Lies `CLAUDE.md`, `README.md`, `pyproject.toml` und den Code unter `src/` (vor allem `app_core`, `app_ui`, `app_platform`, `app_worker`).
- Halte dich strikt an die Regeln in `CLAUDE.md`. Wenn der Code von meiner Beschreibung abweicht, gilt der Code. Sag mir Bescheid.
- Wenn du `CLAUDE.md`, `pyproject.toml` oder `src/` nicht findest, brich ab und sag es mir.

## 1. Das Feature

Die App enthält Folien, Übungen und Tutorien aus unseren Uni-Kursen. Der Tutor stellt Fragen zu diesem Material, und der Nutzer antwortet per Sprache. Der Tutor bewertet die Antwort gegen eine Musterlösung, gibt kurzes Feedback per Sprache und stellt die nächste Frage. Bei Rückfragen nennt er die Quelle, z. B. „Folie 14, Vorlesung 5“.

Es gibt **nur zwei Modi**:

| Modus | Gehirn | Sprache |
| --- | --- | --- |
| **Gemma (Standard)** | Gemma lokal über Ollama | ElevenLabs Speech-to-Text + Text-to-Speech, Push-to-Talk |
| **Gespräch** | ElevenLabs Agent | freies Gespräch über das ElevenLabs-JavaScript-SDK |

- **Keine Claude-/Anthropic-Integration** in dieser Version, auch nicht für die Fragengenerierung.
- Gemma ist der Standard (`tutor.brain = "gemma"` in `config.toml`).
- Halte das Interface für Gehirne so, dass später weitere ergänzt werden können, ohne den Kern umzubauen. Baue aber nur diese beiden.

## 2. Regeln

- Arbeite nur auf dem Branch `feature/voice-tutor`. `main` bleibt unverändert.
- Neuer Code liegt in `src/app_core/tutor/` (mit `brains/gemma.py` und `brains/elevenlabs.py`) und in `src/app_ui/tutor/`.
- Bestehende Dateien änderst du nur, wo es für die Anbindung nötig ist. Liste jede Stelle in `docs/tutor/INTEGRATION.md` auf.
- `tutor.enabled = false` in `config.toml` → die App verhält sich exakt wie vorher.
- Kleine Commits mit klaren Nachrichten.
- pytest-Tests für jede neue Funktion in `app_core`. Ollama und ElevenLabs werden gemockt; die Tests laufen ohne Keys und ohne Internet.
- Code und Kommentare auf Englisch, Doku auf Deutsch.
- Secrets nur über keyring. Der ElevenLabs-Key bleibt auf dem Server; der Browser bekommt nur Signed URLs oder fertiges Audio.
- **Neue Abhängigkeiten so wenige wie möglich, jede nur nach Rückfrage.** Für die Suche im Material reicht die eingebaute SQLite-Volltextsuche (FTS5). Vektorsuche kommt später.

## 3. Bevor du Code schreibst

1. Fasse in 5–10 Sätzen zusammen, wie Materialien aktuell gespeichert werden und was für den Tutor noch fehlt.
2. Prüfe die **aktuelle offizielle Doku** für die APIs, die du nutzt: ElevenLabs Speech-to-Text, Text-to-Speech, Agents (JavaScript-SDK, Signed URLs, Client-Tools) und die Ollama-API. Schreib keine API-Aufrufe aus dem Gedächtnis.
3. Leg im Plan-Modus einen kurzen Plan vor: neue Dateien, geänderte bestehende Dateien, neue Tabellen, neue `config.toml`-Einträge, neue Abhängigkeiten. **Warte auf meine Freigabe.**

## 4. Umsetzung

Nach **jedem** Schritt: Tests ausführen, committen, kurz sagen, was fertig ist und wie ich es teste. **Dann auf mein OK warten.**

**Schritt 1: Material und Fragen**
- Text pro Folie/Seite mit Kurs, Datei und Foliennummer speichern (bestehende Logik wiederverwenden, falls vorhanden).
- Volltextsuche (FTS5) über diesen Text.
- Pro Datei Fragen mit Gemma erzeugen: Frage, Musterlösung, Quelle. Bereits verarbeitete Dateien werden nicht erneut verarbeitet.
- Neue Tabellen per Migration: `questions`, `results`.

**Schritt 2: Tutor-Kern als Text-Chat mit Gemma**
- Kleines Interface `TutorBrain` mit `ask_question`, `grade_answer` und `follow_up`.
- `brains/gemma.py` über Ollama.
- Der Ablauf liegt im Code:
  - Der Code wählt die nächste Frage zufällig, bevorzugt falsch beantwortete.
  - Gemma bewertet gegen die Musterlösung und liefert JSON (`verdict`: `correct|partial|wrong`, `feedback`: 1–2 Sätze).
  - Das Ergebnis landet in `results`.
- Ein zentraler System-Prompt: Lerntutor, Deutsch, kurz, nur das Material als Quelle.
- FastAPI-Endpunkte und eine einfache Chat-Seite zum Testen.

**Schritt 3: Push-to-Talk**
- Einfache Tutor-Seite ohne Frontend-Framework: Sprechen-Button (Aufnahme, solange gedrückt), Frage und Transkript als Text, Feedback mit Symbol (✓ / ✗ / 💡).
- `/tutor/transcribe`: Audio an ElevenLabs Speech-to-Text.
- `/tutor/speak`: Antworttext an ElevenLabs Text-to-Speech, Audio im Browser abspielen.
- Optik einfach halten und das bestehende Styling der App übernehmen.

**Schritt 4: ElevenLabs Agent**
- `/tutor/agent-session` erzeugt serverseitig eine Signed URL. Das Frontend nutzt das offizielle JavaScript-SDK.
- Zwei Client-Tools, die im Browser unsere API auf `127.0.0.1` aufrufen:
  - `get_next_question`
  - `record_result`
- Keine Server-Webhooks.

**Schritt 5: Einrichtung und Fehlermeldungen**
- `app tutor setup`: fragt den ElevenLabs-Key verdeckt ab, speichert ihn in keyring und trägt Voice-ID und Agent-ID in `config.toml` ein.
- `app tutor check`: prüft ElevenLabs, Ollama und das Gemma-Modell und sagt bei Fehlern konkret, was zu tun ist.
- Fehlt ein Key oder Dienst, zeigt die Seite eine klare Meldung statt abzustürzen.

## 5. Doku unter `docs/tutor/` (auf Deutsch, kurz)

- **INTEGRATION.md:**
  - was das Feature tut
  - geänderte bestehende Dateien mit Begründung
  - neue Abhängigkeiten, Tabellen und `config.toml`-Einträge
  - ein- und ausschalten
  - bekannte Einschränkungen
- **SETUP.md:** Schritt für Schritt für macOS und Windows:
  - ElevenLabs-Key und Stimme
  - Agent im Dashboard anlegen, inklusive der zwei Client-Tools
  - Ollama und Gemma installieren
  - `app tutor setup` und `app tutor check` ausführen
- **NEXT_STEPS.md:** Ideen für später (z. B. Claude als weiteres Gehirn, Vektorsuche, Spaced Repetition, Kostenübersicht) und alle Annahmen, die du getroffen hast.

## 6. Abschluss

1. Alle Tests ausführen und auf macOS-/Windows-Tauglichkeit achten: Pfade über pathlib/platformdirs, `encoding="utf-8"`.
2. Branch pushen. Wenn `gh` eingerichtet ist, einen Pull Request nach `main` mit Zusammenfassung, Änderungsliste, Links auf die Doku und Testanleitung erstellen. Sonst erklär mir, wie ich ihn selbst erstelle.

**Wenn etwas unklar ist oder nicht zur bestehenden Architektur passt, frag nach, statt zu raten.**
