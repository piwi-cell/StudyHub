#!/bin/bash
# Installiert oder aktualisiert ILIAS-Sync und startet danach die Einrichtung.
# Aufruf im Terminal:  bash ~/Downloads/ILIAS-Sync/install.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Library/Application Support/ILIAS-Sync"
BIN="$HOME/.local/bin"
# Feste Versionen mit Prüfsummen: jede Installation lädt genau das, was geprüft wurde.
# PFERD (ILIAS-Downloader) und seine Abhängigkeiten stehen samt Hashes in app/requirements.lock.
UV_VERSION="0.12.19"

[ "$(uname -s)" = "Darwin" ] || { echo "ILIAS-Sync läuft nur auf macOS."; exit 1; }
case "$(uname -m)" in
  arm64)  UV_ARCH="aarch64"; UV_SHA256="a9a8df1eedeb192f2e47e40e2faabfb387db4b850209118786d42f89dde3e0ba" ;;
  x86_64) UV_ARCH="x86_64";  UV_SHA256="cb5fa57bafe68fc0fb94b17f06bee0b0b9a7feb94ccbd110445afa0696e39273" ;;
  *) echo "Unbekannter Prozessor: $(uname -m)"; exit 1 ;;
esac

echo
echo "  ILIAS-Sync wird installiert (einmalig ca. 1–2 Minuten) …"
mkdir -p "$APP/bin" "$BIN"
chmod 700 "$APP"  # Einstellungen, Cookies und Protokoll nur für dich lesbar
cd "$APP"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export UV_CACHE_DIR="$tmp/uv-cache"  # keinen Zwischenspeicher in ~/.cache hinterlassen

if [ "$(bin/uv --version 2>/dev/null | cut -d' ' -f2)" != "$UV_VERSION" ]; then
  curl -fsSL -o "$tmp/uv.tar.gz" \
    "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_ARCH-apple-darwin.tar.gz"
  echo "$UV_SHA256  $tmp/uv.tar.gz" | shasum -a 256 -c --status || { echo "Prüfsumme falsch, Abbruch."; exit 1; }
  tar xzf "$tmp/uv.tar.gz" -C bin --strip-components 1 "uv-$UV_ARCH-apple-darwin/uv"
fi
if [ ! -x venv/bin/python ]; then
  UV_PYTHON_INSTALL_DIR="$APP/python" bin/uv python install --no-bin --quiet 3.13
  UV_PYTHON_INSTALL_DIR="$APP/python" bin/uv venv --quiet --python 3.13 venv
fi
bin/uv pip sync --quiet --require-hashes --python venv/bin/python "$SRC/app/requirements.lock"

rm -rf app
cp -R "$SRC/app" app
/usr/bin/xattr -cr app 2>/dev/null || true  # Download-Markierung entfernen
ln -sf "$APP/app/ilias-sync" "$BIN/ilias-sync"

# Befehl „ilias-sync“ in neuen Terminal-Fenstern verfügbar machen
if [[ ":$PATH:" != *":$BIN:"* ]] && ! grep -q ">>> ILIAS-Sync >>>" "$HOME/.zprofile" 2>/dev/null; then
  printf '\n# >>> ILIAS-Sync >>>\nexport PATH="$HOME/.local/bin:$PATH"\n# <<< ILIAS-Sync <<<\n' >> "$HOME/.zprofile"
fi

echo "  Installiert."
# Als eingerichtet gilt erst, wer den Assistenten bis zum Ende durchlaufen hat (dann gibt es
# den Zeitplan); ein abgebrochener Assistent startet beim nächsten Aufruf neu.
if [ -f "$HOME/Library/LaunchAgents/local.ilias-sync.plist" ]; then
  # Update: Einstellungen bleiben, Zeitplan mit neuem Programm neu laden
  if launchctl print "gui/$(id -u)/local.ilias-sync" >/dev/null 2>&1; then
    venv/bin/python app/cli.py start
  fi
  echo "  Update abgeschlossen. Übersicht: ilias-sync"
elif [ -z "${ILIAS_SYNC_NO_SETUP:-}" ]; then
  exec venv/bin/python app/cli.py einrichten
fi
