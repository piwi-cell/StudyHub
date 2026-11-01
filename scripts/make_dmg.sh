#!/bin/bash
# Baut die DMG zum Installieren ohne Terminal. Darin liegt „StudyHub installieren.app“: Doppelklick führt
# scripts/install.sh aus (lädt den aktuellen Stand von GitHub, richtet Python ein, legt
# ~/Applications/StudyHub.app an) und öffnet danach StudyHub. Dieselbe App aktualisiert auch.
#   bash scripts/make_dmg.sh                dist/StudyHub-Installer.dmg
#   bash scripts/make_dmg.sh <Pfad>.dmg     DMG an anderer Stelle
# Nur Bordmittel (hdiutil, osascript). Unsigniert: macOS blockiert die App beim ersten Öffnen,
# der Hinweis dazu liegt in der DMG.
set -euo pipefail
DMG="${1:-}"
case "$DMG" in
  "") ;;
  *.dmg) DMG="$(mkdir -p "$(dirname "$DMG")" && cd "$(dirname "$DMG")" && pwd)/$(basename "$DMG")" ;;
  *) echo "Zielpfad muss auf .dmg enden: $DMG"; exit 1 ;;
esac
cd "$(dirname "$0")/.."
DMG="${DMG:-$PWD/dist/StudyHub-Installer.dmg}"
VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
chmod 755 "$stage"  # mktemp legt 700 an
APP="$stage/StudyHub installieren.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp assets/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
# Ohne Projektordner daneben lädt install.sh den aktuellen Stand von GitHub
cp scripts/install.sh "$APP/Contents/Resources/install.sh"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>StudyHub installieren</string>
  <key>CFBundleDisplayName</key><string>StudyHub installieren</string>
  <key>CFBundleIdentifier</key><string>local.studyhub.installer</string>
  <key>CFBundleExecutable</key><string>StudyHub installieren</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Fortschritt und Ergebnis als Dialoge; die Ausgabe von install.sh geht ins Protokoll
cat > "$APP/Contents/MacOS/StudyHub installieren" <<'LAUNCHER'
#!/bin/bash
RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
LOG="$HOME/Library/Logs/StudyHub-Installation.log"
APP="${ILIAS_LERNER_APP:-$HOME/Applications/StudyHub.app}"
export PATH="$PATH:/usr/bin:/bin:/usr/sbin:/sbin"  # aus dem Finder gestartet fehlt sonst einiges
TITLE="StudyHub installieren"

# Text und Pfade als Argumente: keine Anführungszeichen-Probleme im AppleScript
osascript -e 'on run argv' -e 'display dialog (item 1 of argv) with title (item 2 of argv) buttons {"Abbrechen", "Installieren"} default button "Installieren" cancel button "Abbrechen" with icon note' -e 'end run' \
  "StudyHub wird für deinen Benutzer installiert oder aktualisiert. Dafür lädt das Programm den aktuellen Stand und Python aus dem Internet (ca. 300 MB, beim ersten Mal einige Minuten). Admin-Rechte sind nicht nötig.

Einstellungen, Dateien und Zugangsdaten bleiben bei einem Update erhalten." "$TITLE" >/dev/null 2>&1 || exit 0

mkdir -p "$(dirname "$LOG")"
echo "--- $(date '+%Y-%m-%d %H:%M:%S') Installation" >> "$LOG"
osascript -e 'on run argv' -e 'display dialog (item 1 of argv) with title (item 2 of argv) buttons {"Ausblenden"} default button 1 with icon note' -e 'end run' \
  "StudyHub wird installiert …

Das dauert beim ersten Mal einige Minuten. Dieses Fenster schließt sich, sobald alles fertig ist. „Ausblenden“ lässt die Installation weiterlaufen." "$TITLE" >/dev/null 2>&1 &
progress=$!
out=$(mktemp)
ILIAS_LERNER_NO_OPEN=1 bash "$RESOURCES/install.sh" 2>&1 | tee -a "$LOG" > "$out"
status=${PIPESTATUS[0]}
kill "$progress" 2>/dev/null
wait "$progress" 2>/dev/null

if [ "$status" -eq 0 ]; then
  version=$(sed -n 's/^Fertig: StudyHub \([^ ]*\) in .*/\1/p' "$out" | tail -1)
  rm -f "$out"
  osascript -e 'on run argv' -e 'display dialog (item 1 of argv) with title (item 2 of argv) buttons {"StudyHub öffnen"} default button 1 with icon note' -e 'end run' \
    "StudyHub $version ist installiert: Benutzerordner › Programme › StudyHub. Tipp: die App ins Dock ziehen.

Aktualisieren: StudyHub beenden und diese Installer-App erneut öffnen. Die DMG kannst du jetzt auswerfen." "$TITLE" >/dev/null 2>&1
  open "$APP"
else
  reason=$(grep '^Abbruch:' "$out" | tail -1)
  [ -n "$reason" ] || reason=$(grep -v '^[[:space:]]*$' "$out" | tail -3)
  rm -f "$out"
  answer=$(osascript -e 'on run argv' -e 'button returned of (display alert (item 2 of argv) message (item 1 of argv) as critical buttons {"Protokoll öffnen", "OK"} default button "OK")' -e 'end run' \
    "Die Installation ist abgebrochen.

$reason

Protokoll: $LOG" "$TITLE" 2>/dev/null)
  [ "$answer" = "Protokoll öffnen" ] && open -e "$LOG"
  exit 1
fi
LAUNCHER
chmod +x "$APP/Contents/MacOS/StudyHub installieren"

cat > "$stage/Falls macOS das Öffnen blockiert.txt" <<'HINT'
StudyHub installieren
=====================

Doppelklick auf „StudyHub installieren“ installiert StudyHub (oder aktualisiert es) und öffnet die App.
Dauer beim ersten Mal: einige Minuten, ca. 300 MB. Admin-Rechte sind nicht nötig.

Die Installer-App ist nicht von Apple notarisiert. Beim ersten Öffnen meldet macOS deshalb, dass die App
nicht geprüft werden kann:

macOS 15 und neuer
  1. Doppelklick auf „StudyHub installieren“, Meldung mit „Fertig“ schließen.
  2. Systemeinstellungen › Datenschutz & Sicherheit, ganz nach unten: bei „StudyHub installieren“
     auf „Trotzdem öffnen“ klicken und mit Passwort oder Touch ID bestätigen.
  3. Noch einmal „Öffnen“ wählen.

macOS 13 und 14
  Rechtsklick (oder ctrl-Klick) auf „StudyHub installieren“ › „Öffnen“ › „Öffnen“.

Klappt etwas nicht, steht der Grund im Protokoll: ~/Library/Logs/StudyHub-Installation.log
HINT

mkdir -p "$(dirname "$DMG")"
rm -f "$DMG"
hdiutil create -volname "StudyHub installieren" -srcfolder "$stage" -format UDZO -ov "$DMG" >/dev/null

echo "Fertig: $DMG"
