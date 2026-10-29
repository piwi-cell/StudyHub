#!/bin/bash
# Entfernt StudyHub (auch eine Installation unter dem alten Namen ILIAS-Lerner): App, Programmordner und Hintergrund-Jobs (Abgleich, Bibliotheken).
# Deine Daten (Einstellungen, geladene Dateien, KI-Ergebnisse, Lernstand) und die Zugangsdaten im
# Schlüsselbund bleiben, außer mit --alles. Der Zielordner mit deinen Kursdateien bleibt immer.
#   bash "$HOME/Library/Application Support/StudyHub/app/scripts/uninstall.sh" [--alles]
set -euo pipefail

INSTALL_DIR="${ILIAS_LERNER_INSTALL_DIR:-$HOME/Library/Application Support/StudyHub/app}"
APP="${ILIAS_LERNER_APP:-$HOME/Applications/StudyHub.app}"
OLD_INSTALL_DIR="${ILIAS_LERNER_OLD_INSTALL_DIR:-$HOME/Library/Application Support/ILIAS-Lerner/app}"  # bis 1.0
OLD_APP="${ILIAS_LERNER_OLD_APP:-$HOME/Applications/ILIAS-Lerner.app}"
DATA_DIR="$HOME/Library/Application Support/ILIAS-Sync"  # wie core.APP_DIR
AGENTS="$HOME/Library/LaunchAgents"
KEYCHAIN_SERVICE="ILIAS-Sync"  # wie core.KEYCHAIN_SERVICE
MARKER=".ilias-lerner-install"

fail() { echo "Abbruch: $*" >&2; exit 1; }

remove_job() {
  launchctl bootout "gui/$(id -u)/$1" >/dev/null 2>&1 || true
  launchctl enable "gui/$(id -u)/$1" >/dev/null 2>&1 || true  # ein früheres „angehalten“ vergessen
  rm -f "$AGENTS/$1.plist"
  echo "Hintergrund-Job $1 entfernt"
}

main() {
  local alles=false
  case "${1:-}" in
    "") ;;
    --alles) alles=true ;;
    *) fail "Unbekannte Option $1 (möglich: --alles)" ;;
  esac
  [ "$(uname -s)" = "Darwin" ] || fail "Nur macOS."
  if pgrep -f "$INSTALL_DIR/main.py" >/dev/null 2>&1 || pgrep -f "$OLD_INSTALL_DIR/main.py" >/dev/null 2>&1; then
    fail "StudyHub läuft noch. Bitte die App beenden (⌘Q) und das Skript erneut starten."
  fi

  local terminal=false  # Terminal-Version „ilias-sync“ nutzt dieselben Daten und denselben Schlüsselbund
  if [ -f "$DATA_DIR/app/cli.py" ] || [ -e "$HOME/.local/bin/ilias-sync" ]; then
    terminal=true
  fi

  if [ "$alles" = true ] && [ "$terminal" = false ]; then
    local answer=""
    read -r -p "Auch Einstellungen, geladene Dateien, KI-Ergebnisse und Zugangsdaten löschen? [j/N] " answer || true
    case "$answer" in
      j | J | ja | Ja) ;;
      *) echo "Nichts gelöscht."; exit 0 ;;
    esac
  fi

  [ -f "$AGENTS/local.ilias-lerner.bibliothek.plist" ] && remove_job local.ilias-lerner.bibliothek
  if [ -f "$AGENTS/local.ilias-sync.plist" ]; then
    if grep -q "/core/sync.py</string>" "$AGENTS/local.ilias-sync.plist"; then
      remove_job local.ilias-sync
    else
      echo "Abgleich-Job der Terminal-Version bleibt (ilias-sync)"
    fi
  fi

  local app dir
  for app in "$APP" "$OLD_APP"; do
    if [ -f "$app/Contents/Info.plist" ] && grep -q "local.ilias-lerner" "$app/Contents/Info.plist"; then
      rm -rf "$app"
      echo "App entfernt: $app"
    fi
  done
  for dir in "$INSTALL_DIR" "$OLD_INSTALL_DIR"; do
    if [ -f "$dir/$MARKER" ]; then
      rm -rf "$dir"
      rmdir "$(dirname "$dir")" 2>/dev/null || true
      echo "Programmordner entfernt: $dir"
    fi
  done

  if [ "$alles" = false ]; then
    echo "Deine Daten bleiben in $DATA_DIR (alles löschen: --alles)."
  elif [ "$terminal" = true ]; then
    echo "Daten und Zugangsdaten bleiben: die Terminal-Version ilias-sync nutzt sie mit."
  else
    rm -rf "$DATA_DIR"
    rm -f "$HOME/Library/Logs/StudyHub.log" "$HOME/Library/Logs/ILIAS-Lerner.log" "$HOME/Library/Logs/ILIAS-Sync.log" \
      "$HOME/Library/Logs/ILIAS-Sync-pferd.log"
    local n=0
    while [ "$n" -lt 50 ] && security delete-generic-password -s "$KEYCHAIN_SERVICE" >/dev/null 2>&1; do
      n=$((n + 1))
    done
    echo "Daten, Protokolle und $n Einträge im Schlüsselbund gelöscht."
  fi
  local claude_config="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  if grep -q "mcp_server.py" "$claude_config" 2>/dev/null; then
    echo "Hinweis: In Claude Desktop steht noch ein Eintrag für StudyHub ($claude_config)."
  fi
  echo "Deine Kursdateien im Zielordner bleiben erhalten."
}

main "$@"  # erst alles einlesen, dann ausführen: das Skript löscht seinen eigenen Ordner
