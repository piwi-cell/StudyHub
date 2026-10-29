# Demo & Pitch (H8)

**Länge:** 3 Minuten Demo + Pitch, danach Fragen. **Sprecher:** A führt, B übernimmt den Tutor-Teil.
Alles läuft lokal auf dem Präsentations-Mac, **ohne Live-ILIAS** (WLAN ist der größte Risikofaktor).

---

## Pitch (Text, ca. 45 Sekunden gesamt)

**Problem (15 s)**
> „Jede Woche landen auf ILIAS neue Folien, Übungen und Tutorien, verteilt über zehn Kurse.
> Man lädt alles von Hand, sortiert, druckt, und dann fängt das Lernen erst an.
> Und vor der Klausur steht man vor 300 Folien und weiß nicht, wo man anfangen soll.“

**Lösung (15 s)**
> „StudyHub holt alles automatisch von ILIAS, sortiert es nach Kurs und Vorlesung, Übung,
> Tutorium, und macht daraus Lernmaterial: Zusammenfassungen mit Formeln und Klausurfallen,
> Karteikarten und einen Tutor, der dich mündlich abfragt, wie in der Lerngruppe.“

**Warum wir (15 s)**
> „Das Fundament läuft schon seit Wochen im Alltag: Der ILIAS-Abgleich ist ein eigenes Tool,
> das wir heute in eine echte Mac-App verwandelt haben, mit Claude, ChatGPT oder komplett
> lokal mit Gemma, und mit Sprache über ElevenLabs.“

---

## Demo-Ablauf (ca. 2:15)

| Zeit | Was zeigen | Was sagen |
|---|---|---|
| 0:00 | **StudyHub-Startseite** (App ist schon offen) | „Das ist mein Semester. Links die Module, oben ‚Heute dran‘: was neu ist und was ich wiederholen sollte.“ |
| 0:15 | **„Synchronisieren“** klicken | „Ein Klick, und die App fragt ILIAS ab. Im Hintergrund läuft das automatisch alle 30 Minuten.“ (Im Demo-Modus kommt nur die Meldung; nicht auf Live-Daten warten.) |
| 0:25 | Modul **Financial Accounting › Dokumente** | „Alles automatisch sortiert: Vorlesung, Übung, Tutorium. Nichts mehr von Hand herunterladen.“ |
| 0:40 | **Zusammenfassung**, vorbereitetes Thema zeigen, **„Einfacher erklären“** klicken | „Aus 40 Folien wird eine Seite: Kernidee, Formeln, die typische Klausurfalle, mit Quelle. Und wenn ich’s nicht verstehe: einfacher erklärt.“ |
| 1:05 | **Karteikarten**, eine Karte aufdecken, „Gewusst“ | „Die Karten entstehen aus derselben Zusammenfassung. Was ich nicht weiß, landet automatisch im Lernplan.“ |
| 1:25 | **Sprachtutor** › „Gespräch starten“ (B übernimmt) | B beantwortet eine Frage laut (oder tippt sie), Tutor bewertet und nennt die Quelle. „Wie eine Lerngruppe, nur um 2 Uhr nachts.“ |
| 2:00 | Kurz die **Einstellungen**: Claude / ChatGPT / Gemma | „Du entscheidest, welche KI. Gemma läuft komplett offline auf dem Mac, nichts verlässt den Rechner.“ |
| 2:15 | Schluss | „StudyHub: ILIAS rein, Lernen raus. Danke!“ |

**Wenn die Zeit knapp wird:** Einstellungen weglassen. **Wenn etwas hängt:** sofort zum Backup-Video.

---

## Checkliste vor der Demo (15 Minuten vorher)

- [ ] Neuester Stand von `main`: `git pull`, dann `bash scripts/setup.sh`
- [ ] App starten: `./"ILIAS-Sync starten.command" --demo` (eigene Beispieldaten, kein ILIAS-Login nötig).
      Oder mit echten Daten, wenn H2 geklappt hat: ohne `--demo`.
- [ ] **KI vorab erzeugen, nicht live warten:** in der Demo für 2 Dokumente „Zusammenfassung“ (Thema)
      und „Karteikarten“ einmal erzeugen. Danach kommen sie sofort aus dem Speicher.
- [ ] **Tutor vorbereiten:** Einstellungen › Study-Tutor › Gehirn **Claude** (Gemma 270M bewertet unzuverlässig),
      dann im Tutor das Modul vorbereiten (Fragen erzeugen).
- [ ] **ElevenLabs:** Key in den Einstellungen hinterlegt, „Vorlesen“ einmal getestet, Lautstärke an.
      Mikrofon geht nur im Browser („Mit Sprache im Browser öffnen“), im App-Fenster antwortet B per Tastatur.
- [ ] Bildschirm: Mitteilungen aus (Fokus), Dock ausblenden, Fenster maximiert, Dark/Light passend zum Beamer
- [ ] Backup-Video liegt auf dem Desktop und ist einmal abgespielt
- [ ] Ladekabel dran, WLAN-unabhängig getestet (Claude braucht Internet; ohne Netz: Gemma zeigen)

## Backup-Video (bis 15:30 aufnehmen)

1. Demo-Ablauf oben einmal durchspielen, mit ⌘⇧5 › „Gesamten Bildschirm aufnehmen“ (mit Ton).
2. Maximal 2:30 Minuten, nicht schneiden.
3. Auf den Präsentations-Mac und zusätzlich auf einen USB-Stick.

---

## Fragen, die kommen werden

| Frage | Antwort |
|---|---|
| **Wie kommt ihr an die ILIAS-Daten?** | Mit dem eigenen Uni-Login über den offiziellen Shibboleth-Login, wie im Browser. Das Passwort liegt nur im macOS-Schlüsselbund und geht ausschließlich an idp.uni-mannheim.de (im Code erzwungen). |
| **Datenschutz bei der KI?** | Man wählt: Gemma läuft komplett lokal. Bei ChatGPT ist `store: false` gesetzt; Claude und OpenAI bekommen nur das Dokument, das man gerade zusammenfasst. |
| **Was kostet das?** | Ergebnisse werden pro Dateiinhalt gespeichert und nie doppelt erzeugt. Das Dokument wird im Prompt gecacht: Folgefragen kosten ca. 10 % (gemessen: 1.138 von 1.192 Tokens aus dem Cache). Eine Zusammenfassung mit Claude Haiku kostet Bruchteile eines Cents. |
| **Nur Uni Mannheim?** | Heute ja (SAML-Login von Mannheim). PFERD, der Downloader darunter, kann viele ILIAS-Instanzen; der Login ist austauschbar. |
| **Windows?** | Heute nur macOS (launchd, Schlüsselbund). Die Roadmap für Windows steht in `ISSUES.md`. |
| **Halluziniert die KI?** | Jede Antwort nennt die Quelle (Datei, Seite). Der Tutor bewertet nur gegen die Musterlösung aus dem Material. Kleine lokale Modelle kennzeichnen wir als ungeprüft. |
| **Was ist echt, was Mock?** | Echt: Abgleich, Sortierung, Zusammenfassungen, Karten, Tutor, Sprache, Telegram, reMarkable-Versand. Beispiel: das Modul „Finanzmathematik“ in StudyHub (nur mit `--demo`). Kein Klausurdatum aus ILIAS. |

---

## Ehrlicher Stand (für uns, nicht für die Bühne)

- ChatGPT und ElevenLabs sind nur mit nachgebauten Antworten getestet, solange niemand einen Key eingetragen hat.
- Echter ILIAS-Abgleich (H2) und reMarkable am Gerät (H6) sind bis jetzt nicht live getestet.
- Mikrofon im App-Fenster: technisch nicht möglich (pywebview), Sprache nur im Browser.
