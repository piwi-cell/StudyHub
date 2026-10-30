# StudyHub ↔ echte Daten

Für die Oberfläche `ui/studyhub/`. Der Server liefert alles schon **im Format von
`js/daten.js`**: `DATEN` und `MODUL_DETAILS` lassen sich 1:1 ersetzen.

## Daten laden

Alle Aufrufe brauchen den Header `x-app-token` mit dem Token aus der Adresse (`?t=…`).
Ohne Token (Doppelklick auf `index.html`) einfach die Mock-Daten behalten.

```js
const TOKEN = new URLSearchParams(location.search).get("t");
async function api(pfad, { method = "GET", body } = {}) {
  const res = await fetch(pfad, { method, headers: { "x-app-token": TOKEN, ...(body ? { "content-type": "application/json" } : {}) },
                                  body: body ? JSON.stringify(body) : undefined });
  const daten = await res.json();
  if (!res.ok) throw new Error(daten.detail || `Fehler ${res.status}`);
  return daten;
}

// Vor app.js ausführen (app.js liest DATEN und MODUL_DETAILS schon beim Laden):
if (TOKEN) {
  const echt = await api("/api/studyhub");
  Object.assign(DATEN, echt.daten);
  for (const id of Object.keys(MODUL_DETAILS)) delete MODUL_DETAILS[id];
  Object.assign(MODUL_DETAILS, echt.details);
}
```

`GET /api/studyhub` liefert `{ daten, details, sync }`.

## Unterschiede zu den Mock-Daten (bitte in der Oberfläche abfangen)

| Feld | Echt | Hinweis |
|---|---|---|
| `DATEN.naechsteKlausur` | `null` | Klausurtermine kennt ILIAS nicht → Zeile „Klausur in X Tagen“ ausblenden |
| `dokumente[].dateien[].seiten` | `null` | stattdessen `groesse` (Bytes) und `typ` („PDF“) |
| `dokumente[].dateien[].pfad` | neu | für Öffnen und KI-Aufrufe |
| `themen[]` | ein Thema pro Dokument mit KI-Ergebnis | kann **leer** sein → Hinweis „Noch keine Zusammenfassung“ statt `d.themen[0]` |
| `themen[].einfacher` | evtl. `""` | nur vorhanden, wenn das strukturierte Thema erzeugt wurde |
| `themen[].pfad`, `.strukturiert`, `.zusammenfassung` | neu | ob das Thema schon strukturiert ist (sonst aus der Markdown-Zusammenfassung abgeleitet) |
| `karten.liste` | kann leer sein | → Hinweis statt „Runde geschafft“ |
| `karten.beispielThema` | neu | ersetzt den festen Text „Thema 3 · Werte von Renten“ im Widget |
| `karten.liste[].formel` | `{ text: "" }` | KI-Karten haben keine eigene Formel |
| `tutor` | `{ kurs, fragen, beantwortet, richtig, thema, verlauf: [] }` | kein vorgefertigtes Gespräch mehr, siehe unten |
| `lernplan` | Kapitel = Vorlesungsordner, Bereiche = Tutorium-/Übungsordner, ein Eintrag pro Datei; `id` = Dateipfad | Status wird gespeichert, siehe unten |

Alle Texte sind schon HTML-maskiert (Dateinamen und KI-Texte können kein Markup einschleusen).
Formeln enthalten nur `<sub>`/`<sup>`, Kernideen nur `<b>` und `<br>`.

## Aktionen → Endpunkte

| Aktion in StudyHub | Aufruf |
|---|---|
| Lernplan-Status / Notiz ändern (`setzeStatus`, Notizfeld) | `PATCH /api/studyhub/lernplan` `{ pfad, status?, notiz? }`, Status: `offen`, `inArbeit`, `erledigt`, `nochmal` |
| Datei in der App aus-/einblenden (Tab „Dokumente“) | `PATCH /api/studyhub/ausblenden` `{ pfad, ausgeblendet }`; ausgeblendete Dateien fehlen überall in der App (Dokumente, Lernplan, Tutor, MCP), bleiben aber im Spiegel und im Zielordner. `GET /api/studyhub` liefert sie je Modul unter `ausgeblendet: [{ pfad, name, ordner }]` |
| „Synchronisieren“ | `POST /api/sync`, dann `GET /api/status` alle 3 s bis `running: false`, danach `/api/studyhub` neu laden. Statuszeile: `sync.letzter`, `sync.running` |
| Dokument öffnen | `POST /api/open` `{ path }` (öffnet in Vorschau) oder `GET /api/file?path=…&t=…` (im Fenster anzeigen) |
| Zusammenfassung erstellen (Thema) | `POST /api/ai/run` `{ path, task: "thema" }` (ca. 10 s), danach `/api/studyhub` neu laden |
| „Karten erstellen“ | `POST /api/ai/run` `{ path, task: "flashcards" }`, danach neu laden |
| „Einfacher erklären“ | steckt im Thema (`einfacher`); fehlt es, erst `task: "thema"` erzeugen |
| Vorlesen (`sprich`) | `POST /api/tutor/speak` `{ text }` → MP3 (nur wenn ElevenLabs-Key hinterlegt, sonst Browser-Stimme) |
| Sprachtutor | `POST /api/tutor/prepare` `{ path }` pro Datei (einmalig), `GET /api/tutor/next?course=<tutor.kurs>`, `POST /api/tutor/answer` `{ question_id, text }`, Rückfrage `POST /api/tutor/ask`, Lerngespräch `POST /api/tutor/chat` `{ text, history, course, question_id }`, Mikrofon: `POST /api/tutor/transcribe` (Audio-Body) |
| „✦ Claude“ (Top-Bar) | `POST /api/claude/open` `{ kurs? }` öffnet Claude Desktop mit neuem Lerncoach-Chat (`kurs` nur, wenn es ihn gibt) → `{ ok, mcp }`; `mcp: false` = MCP-Server noch nicht in Claude Desktop eingetragen |
| Karte bewerten (Nochmal/Schwer/Gewusst) | `POST /api/cards/review` `{ id, bewertung }` → `{ inTagen, faellig }` (SM-2, `server/cards.py`). Karten in `/api/studyhub` tragen `id`, `neu`, `faellig`, `inTagen`; fällige zuerst. `karten.faellig` zählt fällige, `karten.naechste` = Tage bis zur nächsten |
| Anki | `GET /api/anki/status` → `{ ready, decks, hinweis? }`, `POST /api/anki/import` `{ kurs, deck }`, `POST /api/anki/export` `{ kurs }` (Deck `StudyHub::<Kurs>`). Braucht laufendes Anki mit AnkiConnect (Code 2055492159) |
| Karten als Textdatei | `POST /api/cards/import` (multipart `kurs`, `file`; Tabulator, Anki „Notizen als Text“), `GET /api/cards/export?kurs=…` (Download) bzw. `POST /api/cards/export` `{ kurs }` (Datei in `~/Downloads`) |
| Klausurtermin | `PATCH /api/studyhub/klausur` `{ kurs, datum: "JJJJ-MM-TT" \| null }`; Module tragen `klausur: { datum, tage } \| null`, `naechsteKlausur` = nächste künftige |
| Eigene Zusammenfassung schreiben | `POST /api/summaries` `{ kurs, titel, text }` → Markdown unter `<Kurs>/Eigene Zusammenfassungen/`; Themen daraus tragen `eigene: true` |
| Seite „Bibliotheken“ (`#/bibliotheken`) | `GET /api/libraries` → `{ stand, alterMinuten, taktMinuten, seit, messungen, jetzt: { wochentag, stunde }, wochentage, bereiche: [{ slug, name, url, info, aktuell: { prozent, plaetze, frei, stufe } \| null, offen, oeffnet, zeiten, typischJetzt, woche: [7 × 24 × { stunde, mittel, messungen }] }], hintergrund, quelle, intervallMinuten, alarmAbstand, demo, telegram: { verbunden, bot, alarm: { aktiv, schwelle, bereiche } } }`; „Jetzt messen“ `POST /api/libraries/refresh`; Hintergrund `PATCH /api/libraries/background` `{ aktiv }`; Telegram verbinden `POST /api/telegram/connect` `{ token, chat? }` (ohne `chat` wartet der Server bis zu 5 Min. auf eine Nachricht an den Bot); Meldungen „voll / wieder Platz“ `PATCH /api/libraries/alerts` `{ aktiv?, schwelle? (50–100), bereiche? (leer = alle) }`; Stand an Telegram `POST /api/libraries/telegram` (`server/libraries.py`, Bot-Befehle in `server/integrations.py`) |
| „Modul aus ILIAS hinzufügen“ | Seite „Kurse“ (`#/kurse`, `/api/courses`) |
| Suche oben | `GET /api/search?q=` → `{ treffer: [{ pfad, name, kurs, seite, ausschnitt }], ausstehend }`: erst Dateinamen, dann Textstellen (Volltextindex `tutor.index_all()` im Hintergrund, `<mark>` im Ausschnitt) |
| Frage zu einem Dokument | `POST /api/ai/run` `{ path, task: "qa", question }`; Themen tragen `fragen: [{ frage, antwort }]` (neueste zuerst) |
| Weitergeben, Finder | `POST /api/share` `{ path, task: "thema" \| "summary" \| "flashcards" \| "original", target }`, `POST /api/reveal` `{ path }` |
| Skills (eigene Tabs) | `PATCH /api/studyhub/skills` `{ kurs, skills }`; `/api/studyhub` liefert `skills: { Kurs: [...] }` |

Im App-Fenster gibt es kein Mikrofon (WebKit-Einschränkung von pywebview). Für Sprache StudyHub
im Browser öffnen: `POST /api/studyhub/open-browser` `{ hash }`.

## Eigene Dateien hochladen

`POST /api/upload` (multipart): Feld `course` = Kursordner (`tutor.kurs` eines Moduls), ein oder
mehrere Felder `files`, optional `art` = `material` (Standard) oder `zusammenfassung` (Ablage unter
`<Kurs>/Eigene Zusammenfassungen/`, erscheint im Tab „Zusammenfassung“, nicht im Lernplan).
Antwort `{ saved: [Pfade], errors: [Meldungen] }`; teilweise Erfolg ist möglich.

- Ablage unter `<Kurs>/Eigene Dateien/` im Spiegel; danach sofort in den Zielordner kopiert.
  ILIAS-Abgleiche löschen sie nicht (PFERD `on_conflict = no-delete`).
- Erlaubt: PDF, Office/iWork, Text, Bilder, ZIP; keine ausführbaren Dateien (Öffnen würde sie starten).
- Höchstens 100 MB pro Datei, gleichnamige Dateien werden nie überschrieben („Name (2).pdf“).
- In StudyHub: Knopf „Eigene Dateien hinzufügen“ im Tab Dokumente oder Dateien auf eine Modulseite ziehen.

