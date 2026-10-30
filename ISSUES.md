# Issue-Liste

Arbeitspakete aus der Entstehung der App (Hackathon `H1`–`H11`, Weitergabe `W1`–`W5`) und die
ursprüngliche Roadmap. Bereiche: A Kern und Integration (`core/`), B KI (`ki/`), C Oberfläche (`ui/`),
D Integrationen (`int/`). Stretch-Ziele sind mit ⭐ markiert.

---

## Hackathon

### H1 · Start: Umgebung und Merge des MVP
**Verantwortlich:** A (alle wirken mit) · **Abhängigkeiten:** keine

- [ ] `phase-5/hackathon-mvp` ist in `main` gemerged, die CI ist grün.
- [ ] Alle vier haben Schreibzugriff, `bash scripts/setup.sh` ausgeführt und die Demo läuft (`--demo`).
- [ ] Alle haben Zugang zu Claude (eigener API-Key oder `ant auth login`).

### H2 · Echter ILIAS-Abgleich
**Verantwortlich:** A · **Review:** D

- [ ] Login mit echter Uni-ID über Einstellungen › ILIAS-Zugang klappt.
- [ ] Erster Abgleich lädt Dateien in den Zielordner; sie erscheinen unter „Dateien“.
- [ ] Gefundene Fehler als Issue oder Fix mit Test.

### H3 · ChatGPT als dritter KI-Anbieter
**Verantwortlich:** B · **Review:** A

- [ ] `_openai()` in `server/ai.py` mit derselben Rückgabe wie `_claude()` (`output, meta`).
- [ ] API-Key über `keyring` (Konto „OpenAI-API-Key“), Eingabe in den Einstellungen.
- [ ] Modellname und SDK-Aufruf nach aktueller OpenAI-Dokumentation; neue Abhängigkeit vorher abgestimmt.
- [ ] Test mit ersetztem Anbieter (kein echter Aufruf in der CI).
- [ ] Anbieter erscheint in `/api/ai/providers` und im Auswahlmenü (mit C abstimmen).

### H4 · Bessere Prompts und Ausgaben
**Verantwortlich:** B · **Review:** C

- [ ] Zusammenfassung und Karten an 3 echten Vorlesungs-PDFs geprüft und Prompts angepasst.
- [ ] Gescannte Folien (ohne Text) einmal mit Claude getestet.
- [ ] ⭐ Fragen über einen ganzen Kurs (alle Dokumente), mit Quellenangabe pro Antwort.

### H5 · Oberfläche: Feinschliff und erster Start
**Verantwortlich:** C · **Review:** A

- [x] Einrichtungs-Assistent beim ersten Start (Zugang → Kurse → Zielordner → KI), erneut startbar in den Einstellungen.
- [ ] Ladezustände und Fehlermeldungen überall verständlich.
- [ ] PDF-Vorschau im nativen Fenster geprüft.
- [ ] ⭐ App-Icon
- [x] ⭐ Tastaturkürzel: ⌘1–5 Ansichten, ⌘R abgleichen, ⌘F suchen, ⌘, Einstellungen
- [x] StudyHub skaliert in normalen Fenstergrößen (980–1320 px) ohne Überlauf
- [x] Karteikarten mit gespeichertem Lernstand (SM-2), nur fällige Karten
- [x] Anki: Deck übernehmen und Karten senden (AnkiConnect), Textdatei importieren/exportieren
- [x] Eigene Zusammenfassungen schreiben oder hochladen; PowerPoint und Word für KI lesbar
- [x] Klausurtermine von Hand eintragen
- [x] Bibliotheken: Auslastung der UB-Bereiche live und als Verlauf je Wochentag/Stunde (eigene Messungen)

### H6 · reMarkable echt testen
**Verantwortlich:** D · **Review:** B

- [ ] Original-PDF und Lernkarten-PDF kommen auf dem Tablet an (USB-Webinterface oder reMarkable-App).
- [ ] Fehlermeldung, wenn kein Weg verfügbar ist, ist verständlich.

### H7 · Telegram interaktiv
**Verantwortlich:** D · **Review:** B

- [ ] Telegram in der App verbunden und getestet.
- [ ] Nach fertiger Zusammenfassung optional automatisch an Telegram.
- [ ] ⭐ Bot-Befehl `/karte` schickt eine zufällige Lernkarte, Antwort als Spoiler.
- [x] Bot-Befehl `/bib` (Auslastung der Bibliotheken) und Meldungen „voll / wieder Platz“; Einrichtung auf der Seite „Bibliotheken“ (am Mac noch nicht live getestet)

### H8 · Demo und Pitch
**Verantwortlich:** A · **Review:** alle

- [x] Demo-Ablauf (3 Minuten), Pitch-Text und Antworten auf Jury-Fragen: `docs/DEMO.md`
- [ ] Demo zweimal auf dem Präsentations-Mac geprobt
- [ ] Backup-Video der Demo, falls das WLAN ausfällt.
- [ ] Demo nutzt vorab geladene Dateien, nicht Live-ILIAS.

### H10 · Sprechender Study-Tutor (ElevenLabs)
**Verantwortlich:** B · Doku: `docs/tutor/`

- [x] Material und Fragen (SQLite/FTS5), Bewertung, Rückfragen mit Quelle
- [x] Gehirn wählbar: Gemma (Standard), Claude, ChatGPT
- [x] Push-to-Talk (im Browser) und Vorlesen über ElevenLabs
- [ ] Live-Test mit ElevenLabs-Key
- [x] ⭐ ElevenLabs Agent (Gesprächsmodus), Branch `ki/elevenlabs-agent`; Live-Test offen
- [x] Feste Demo-Fragen für `--demo`
- [x] Fragen automatisch im Hintergrund (Gemma) für alle Kursdateien, Karte auf der Übersicht
- [x] Freies Lerngespräch per Push-to-Talk (eigene Fragen aus dem Material, Hinweise, Erklärungen, Themenwechsel), alte Tutor-Ansicht und StudyHub

### H11 · ⭐ MCP-Server für Claude Desktop (Claude-Abo statt API-Key)
**Verantwortlich:** C · Doku: `docs/mcp.md` · vorgezogen aus der Roadmap (Punkt 4)

- [x] `server/mcp_server.py` (stdio): Kurse, Dateien, Dateitext, StudyHub-Stand lesen
- [x] Schreiben nur in den KI-Cache: `save_thema`, `save_flashcards`; erscheint in StudyHub
- [x] Tests ohne Netz, inklusive stdio-Durchlauf
- [x] Knopf „✦ Claude“ in StudyHub: neuer Chat in Claude Desktop als Lerncoach, dazu MCP-Prompt `lerncoach`
- [ ] Live-Test in Claude Desktop
- [ ] Neue Abhängigkeit `mcp` im Team bestätigt

### H12 · Gemini als vierter KI-Anbieter
**Verantwortlich:** B

- [x] `_gemini_doc()` in `server/ai.py` mit derselben Rückgabe wie `_claude()` (`output, meta`), gescannte PDFs als PDF
- [x] Google-AI-API-Key aus dem Schlüsselbund (derselbe wie für Gemma über die Gemini API), keine neue Abhängigkeit
- [x] Anbieter in `/api/ai/providers`, Einstellungen (StudyHub, klassisch), Einrichtungs-Assistent und als Tutor-Gehirn
- [x] Tests mit ersetzter API (kein echter Aufruf)
- [x] Am Mac mit echtem Key geprüft

### H9 · Tests und Qualität (laufend)
**Verantwortlich:** alle

- [ ] CI bleibt auf jedem PR grün.
- [ ] Jeder behobene Fehler bekommt einen Test.

---

## Weitergabe an andere (W1–W5)

Ziel: Andere Studierende (Mac) können die App ohne Entwicklerwerkzeuge installieren, aktualisieren und entfernen.

### W1 · Installation, Update, Deinstallation
- [x] `scripts/install.sh`: ohne Admin-Rechte, Xcode und git; Programm an fester Stelle, App in `~/Applications`
- [x] Update über denselben Befehl, Daten und Python-Umgebung bleiben; Hintergrund-Jobs ziehen beim App-Start nach
- [x] `scripts/uninstall.sh`, mit `--alles` auch Daten und Schlüsselbund (nicht, wenn die Terminal-Version sie nutzt)
- [x] App-Symbol fertig im Repo (`assets/AppIcon.icns`), Version in Einstellungen › Über die App
- [x] Am Mac geprüft: Installation, Update, Deinstallation, Hintergrund-Jobs nach dem Update

### W2 · Texte und Zustände für App-Nutzer
- [x] Meldungen ohne Verweis auf das Terminal-Programm (`core/sync.py`, Notion-Zeile nur wenn eingerichtet)
- [x] Keine Beispieldaten im echten Modus (auch nicht bei Verbindungsfehlern): „Lädt …“ bzw. Fehlerseite mit „Erneut versuchen“
- [x] Knopf „Synchronisieren“ in StudyHub startet den Abgleich (warf vorher einen JS-Fehler)
- [x] Ollama ohne Homebrew einrichtbar (Hinweis auf ollama.com/download)
- [x] Fortschritt beim Abgleich („3 von 8 Kursen fertig · 1:20“), auch für einen schon laufenden Hintergrund-Abgleich

### W3 · KI-Einrichtung, Datenschutz, Kosten
- [x] Einrichtungsschritt „KI“ mit Hinweis, wohin Kursmaterial geht (StudyHub, klassischer Assistent)
- [x] Kosten pro Ergebnis und Monat anzeigen (Schätzung nach Listenpreisen, `PRICES` in `server/ai.py`)
- [x] Abgeschnittene JSON-Antworten als verständlicher Fehler statt HTTP 500

### W4 · CI
- [x] Linux-Job statt macOS-Job (bekam nie einen Runner), Spotlight-Suche (`mdfind`) in allen Tests ersetzt

### W5 · Doku, Lizenz, Release
- [x] Nutzeranleitung (`docs/anleitung.md`: Installation, Datenschutz, Kosten, FAQ, Deinstallation)
- [x] `LICENSE` (Alle Rechte vorbehalten), `THIRD_PARTY_NOTICES.md` (Test prüft gegen `uv.lock`)
- [x] Version 1.0.0
- [x] Release `v1.0.0` (Tag und ZIP), nach dem Fix „Einstellungen gehen beim Abgleich verloren“; am Mac aus dem ZIP installiert
- [ ] Installationsbefehl ohne Download des Projekts (erst, wenn das Repository öffentlich ist)

### A · Analyse vom 30.10.2026
- [x] A1 Fehler: Kurs umbenennen behält Lernstand und KI-Ergebnisse, Zielordner geprüft, Skills gespeichert,
  Cache der Oberfläche, Python 3.13–3.14
- [x] A2 StudyHub einzige Oberfläche: Suche (Dateinamen und Text), Frage zum Dokument, Weitergeben an
  Telegram/reMarkable, Im Finder zeigen; klassische Ansicht entfernt (Version 1.2.0)
- [ ] A3 Anleitung „Was StudyHub kann“ (Lernplan, Karteikarten, Tutor, Bibliotheken, Suche, Weitergeben …)
- [ ] Später: „Heute dran“ nach Klausurtermin, Probeklausur für echte Kurse, Formeln (KaTeX, neue Abhängigkeit),
  Erinnerung an fällige Karten per Telegram, Zusammenfassung als PDF, Frage zu Dokumenten ohne Lernthema

---

## Nach dem Hackathon (ursprüngliche Roadmap)

Diese Ziele bleiben gültig, sind für heute aber bewusst zurückgestellt:

1. **Struktur:** Umzug nach `src/app_core`, `src/app_ui`, `src/app_platform` usw.;
   OS-spezifischer Code nur in `app_platform`.
2. **Windows-Version:** Aufgabenplanung statt launchd, Windows-Anmeldeinformationsverwaltung,
   Ersatz für osascript/GoodNotes; CI wieder auf macOS und Windows.
3. **Konfiguration:** `config.toml` und SQLite über `platformdirs`, `APP_DATA_DIR` statt `ILIAS_SYNC_HOME`.
4. **MCP-Server** (`app-mcp`, stdio) mit Lese-Tools und genau einem Schreib-Tool `save_summary`,
   Anbindung an Claude Desktop.
5. **Paketierung:** Installationsskripte bzw. signierte App, Deinstallation ohne Rückstände.
6. **Optional:** Betrieb auf Heimserver mit Tunnel und OAuth für claude.ai Web/Mobile.
