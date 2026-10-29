# StudyHub · Anleitung

StudyHub lädt die Dateien deiner ILIAS-Kurse der Uni Mannheim auf deinen Mac, sortiert sie in
Kursordner und macht daraus auf Wunsch mit KI Zusammenfassungen, Lernkarten und Tutor-Fragen.

## Voraussetzungen

- Mac mit macOS 13 oder neuer, ca. 300 MB frei, Internet
- Uni-Kennung (Login wie bei ILIAS)
- Keine Admin-Rechte, kein Xcode, kein git nötig
- Für KI optional: ein eigener API-Key (Claude, ChatGPT oder Gemini) oder Ollama für Gemma auf dem Mac

## Installieren

Terminal öffnen (Programme › Dienstprogramme › Terminal), diesen Befehl einfügen und Return drücken:

```bash
curl -fsSL https://raw.githubusercontent.com/piwi-cell/StudyHub/main/scripts/install.sh | bash
```

Das dauert einige Minuten. Danach liegt die App unter `~/Applications/StudyHub.app` (im Finder:
Benutzerordner › Programme) und öffnet sich. Die Einrichtung führt durch Uni-Login, Kurswahl, Zielordner und
KI.

Ohne diesen Befehl geht es auch so: auf github.com/piwi-cell/StudyHub unter „Code“ › „Download ZIP“ laden,
entpacken, im Terminal `cd ` eintippen (mit Leerzeichen), den Ordner ins Fenster ziehen, Return, dann
`bash scripts/install.sh`.

Tipp: App ins Dock ziehen. Öffnest du sie ein zweites Mal, holt sie das offene Fenster nach vorn.

## Aktualisieren

App beenden (⌘Q) und den Installationsbefehl von oben erneut ausführen.
Einstellungen, Dateien, Lernstand und Zugangsdaten bleiben erhalten. Die installierte Version steht unter
Einstellungen › Über die App.

### Umstieg von ILIAS-Lerner

Bis Version 1.0 hieß die App ILIAS-Lerner. Den Installationsbefehl einfach ausführen: Er installiert
StudyHub, entfernt die alte ILIAS-Lerner.app samt Programmordner und öffnet StudyHub. Einstellungen,
Dateien, Lernstand und Zugangsdaten bleiben. Danach:

- StudyHub.app ins Dock ziehen (das alte Symbol verschwindet).
- Fragt macOS nach dem Schlüsselbund: „Immer erlauben“ (das Programm liegt jetzt an einer anderen Stelle).
- Mit Claude Desktop: Einstellungen › KI › Claude Desktop › „Aktualisieren“, dann Claude Desktop neu starten.
- Anki: Neue Karten landen im Stapel „StudyHub::<Kurs>“ statt „ILIAS-Lerner::<Kurs>“.

## Entfernen

```bash
bash "$HOME/Library/Application Support/StudyHub/app/scripts/uninstall.sh"
```

Das entfernt App, Programm und Hintergrund-Jobs. Mit `--alles` am Ende (nach Rückfrage) auch Einstellungen,
geladene Dateien, KI-Ergebnisse, Lernstand und die Einträge im Schlüsselbund. Dein Zielordner mit den
Kursdateien bleibt immer erhalten.

## Claude Desktop statt API-Key

Hast du ein Claude-Abo (Pro oder Max), kann **Claude Desktop** mit deinen Kursunterlagen arbeiten, ohne
API-Key und ohne API-Kosten: Lernthemen, Lernkarten und Tutor-Fragen erstellen und in der App speichern.

1. Claude Desktop von claude.com/download installieren und anmelden.
2. In StudyHub unter Einstellungen › KI › Claude Desktop auf **Einrichten** klicken.
3. Claude Desktop mit ⌘Q beenden und neu öffnen.

Danach in Claude zum Beispiel schreiben: „Erstelle für Statistik I ein Lernthema aus der Vorlesung 07 und
speichere es.“ Oder in StudyHub oben rechts auf **✦ Claude** klicken: Claude startet dann als Lerncoach.
Claude Desktop fragt vor jedem Zugriff auf die Unterlagen nach deiner Erlaubnis. Mehr: `docs/mcp.md`.

## Datenschutz: was wohin geht

| Was | Wohin |
|---|---|
| Uni-Kennung und Passwort | Schlüsselbund des Macs (Dienst „ILIAS-Sync“); geht nur an den Uni-Login (ILIAS) |
| Kursdateien | Nur auf deinen Mac: Spiegel unter `~/Library/Application Support/ILIAS-Sync`, Kopie in deinem Zielordner |
| API-Keys, Telegram-Token | Schlüsselbund; nie in Dateien oder Protokollen |
| Text aus Kursunterlagen | Nur wenn du eine KI-Funktion nutzt: an den gewählten Anbieter, bei gescannten Folien die PDF selbst |
| Gemma über Ollama | Bleibt komplett auf dem Mac |
| Sprachtutor | Deine Sprachaufnahme und die Antworttexte gehen an ElevenLabs (nur wenn eingerichtet) |
| Claude Desktop | Nur was Claude über „studyhub“ liest, und nur nach deiner Erlaubnis; geht an Anthropic wie jeder Claude-Chat |
| Telegram, reMarkable | Nur was du selbst schickst bzw. was der Bot auf deine Befehle antwortet |

Die App öffnet keinen Zugang von außen: Ihr Server hört nur auf dem eigenen Mac (`127.0.0.1`). Was ein
KI-Anbieter mit den Inhalten macht, regeln seine Nutzungsbedingungen. Lade nur Material hoch, das du
weitergeben darfst; Kursunterlagen sind oft nur für Kursteilnehmer bestimmt.

## Kosten

Die App selbst kostet nichts. KI-Anbieter rechnen über deinen API-Key ab, nach verbrauchten Tokens:

- **Gemma über Ollama:** kostenlos, läuft auf dem Mac (langsamer, einfachere Ergebnisse).
- **Gemma über die Gemini API:** mit kostenlosem Key aus Google AI Studio, mit Nutzungsgrenzen.
- **Claude, ChatGPT, Gemini:** kostenpflichtig. Eine Zusammenfassung einer üblichen Foliensammlung kostet
  meist wenige Cent, mit den größten Modellen mehr.

Jedes Ergebnis wird nur einmal pro Dateiinhalt erzeugt und dann wiederverwendet. Einstellungen › KI zeigt eine
Kostenschätzung für den Monat (nach Listenpreisen, ohne Gewähr; die echte Abrechnung steht beim Anbieter). Bei
Gemini gelten Einführungspreise, die sich zum 1.12.2026 bzw. 1.1.2027 verdoppeln. Gespräche im Sprachtutor
(ElevenLabs) und über Claude Desktop sind in der Schätzung nicht enthalten. Setze beim Anbieter ein
Ausgabenlimit, wenn du sicher gehen willst.

## Häufige Fragen

**„StudyHub ist schon geöffnet“ erscheint.**
Die App läuft schon, oft minimiert oder auf einem anderen Schreibtisch. Normalerweise holt ein zweiter
Start das Fenster nach vorn; die Meldung kommt nur, wenn das nicht klappt. Dann im Dock auf das Symbol
klicken oder die App mit ⌘Q beenden und neu öffnen.

**Der Abgleich lädt nichts oder meldet einen Fehler.**
Uni-Login prüfen (Einstellungen), Internet prüfen und „Synchronisieren“ erneut drücken. Während der Abgleich
läuft, zeigt die App den Fortschritt („3 von 8 Kursen fertig“). Details stehen im Protokoll
`~/Library/Logs/ILIAS-Sync.log`.

**Neue Dateien kommen nur, wenn die App offen ist.**
In den Einstellungen „Automatisch im Hintergrund“ einschalten; dann gleicht der Mac regelmäßig ab, auch ohne
geöffnete App.

**macOS fragt nach dem Schlüsselbund-Passwort.**
Das passiert, wenn ein neues Programm zum ersten Mal auf gespeicherte Zugangsdaten zugreift, z. B. nach einem
Update. Mit „Immer erlauben“ bestätigen.

**Gemma antwortet nicht.**
Ollama von ollama.com/download installieren, öffnen und einmal im Terminal `ollama pull gemma3:4b` ausführen.
Alternativ unter Einstellungen › KI einen kostenlosen Key aus Google AI Studio für Gemma hinterlegen.

**Der Telegram-Bot reagiert nicht oder doppelt.**
Ein Bot-Token darf nur von einem Programm gleichzeitig abgefragt werden. Läuft ein anderes Programm mit
demselben Bot (oder eine zweite Installation), nimmt es der App die Nachrichten weg. Jedem Programm einen
eigenen Bot geben.

**Wo liegen meine Dateien?**
Im Zielordner, den du in der Einrichtung gewählt hast (änderbar in den Einstellungen). Programm und Daten der
App liegen unter `~/Library/Application Support/StudyHub` bzw. `…/ILIAS-Sync`, Protokolle unter
`~/Library/Logs`.

## Lizenz

StudyHub: Alle Rechte vorbehalten, Julius Piwaronas (siehe `LICENSE`). Nutzung für das eigene Studium
erlaubt; bitte keine Kopien weitergeben, sondern auf github.com/piwi-cell/StudyHub verweisen.
Drittsoftware: siehe `THIRD_PARTY_NOTICES.md`.
