#!/bin/bash
# Baut StudyHub.app: Doppelklick startet die App ohne Terminal.
# Die App startet den Code aus diesem Projektordner (Pfad wird beim Bauen eingetragen);
# nach einem Umzug des Ordners einfach noch einmal bauen.
#   bash scripts/make_app.sh                App im Projektordner (Entwicklung)
#   bash scripts/make_app.sh <Pfad>.app     App an anderer Stelle (scripts/install.sh: ~/Applications)
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="$PWD"
APP="${1:-$PROJECT/StudyHub.app}"
case "$APP" in
  *.app) ;;
  *) echo "Zielpfad muss auf .app enden: $APP"; exit 1 ;;
esac
VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)

[ -x .venv/bin/python ] || bash scripts/setup.sh

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp assets/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"  # neu erzeugen: scripts/make_icon.sh

# Kennung local.ilias-lerner bleibt vom alten Namen: Mitteilungen und Rechte bleiben, install.sh und
# uninstall.sh erkennen daran ihre eigene App
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>StudyHub</string>
  <key>CFBundleDisplayName</key><string>StudyHub</string>
  <key>CFBundleIdentifier</key><string>local.ilias-lerner</string>
  <key>CFBundleExecutable</key><string>StudyHub</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Startet Python direkt (exec), damit es nur ein Programm im Dock gibt
cat > "$APP/Contents/MacOS/StudyHub" <<LAUNCHER
#!/bin/bash
PROJECT="$PROJECT"
LOG="\$HOME/Library/Logs/StudyHub.log"
if [ ! -x "\$PROJECT/.venv/bin/python" ]; then
  /usr/bin/osascript -e 'display alert "StudyHub" message "Programmordner nicht gefunden: $PROJECT. Bitte StudyHub neu installieren (scripts/install.sh) oder im Projekt bash scripts/make_app.sh ausführen."'
  exit 1
fi
cd "\$PROJECT"
echo "--- \$(date '+%Y-%m-%d %H:%M:%S') Start" >> "\$LOG"
exec "\$PROJECT/.venv/bin/python" "\$PROJECT/main.py" "\$@" >> "\$LOG" 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/StudyHub"
# Selbst gebaut, nicht heruntergeladen: Quarantäne-Vermerke kopierter Dateien (z. B. aus einem ZIP) entfernen
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Fertig: $APP"
echo "Starten per Doppelklick im Finder, oder: open \"$APP\""
