#!/bin/bash
# Installiert oder aktualisiert StudyHub (bis 1.0: ILIAS-Lerner) für den angemeldeten Benutzer. Braucht weder Admin-Rechte
# noch Xcode oder git; lädt uv, Python 3.13 und die Abhängigkeiten nach uv.lock (ca. 300 MB).
#
#   Programm:  ~/Library/Application Support/StudyHub/app
#   App:       ~/Applications/StudyHub.app
# Eine Installation unter dem alten Namen ILIAS-Lerner wird dabei ersetzt (Daten bleiben).
#   Daten:     ~/Library/Application Support/ILIAS-Sync (Einstellungen, Dateien, KI-Ergebnisse)
#              und Schlüsselbund „ILIAS-Sync“. Ein Update lässt beides unverändert.
#
# Aufruf aus einem entpackten Download oder Klon des Projekts:  bash scripts/install.sh
# Ohne Projektordner (z. B. per curl … | bash) lädt das Skript den aktuellen Stand von GitHub;
# ILIAS_LERNER_ARCHIVE ersetzt die Adresse des Archivs (.tar.gz).
#
# Claude Code (Befehl „claude“, für Claude über das Abo) wird mitinstalliert, falls es fehlt: offizieller
# Installer laut code.claude.com/docs/en/setup („curl -fsSL https://claude.ai/install.sh | bash“, ohne
# Admin-Rechte, legt ~/.local/bin/claude an). Anmelden muss man sich danach in StudyHub.
# ILIAS_LERNER_CLAUDE_INSTALLER ersetzt die Adresse des Installers, ILIAS_LERNER_CLAUDE_PATHS die
# geprüften Orte (durch : getrennt); ILIAS_LERNER_SKIP_CLAUDE=1 lässt den Schritt aus.
# Entfernen: bash "~/Library/Application Support/StudyHub/app/scripts/uninstall.sh"
set -euo pipefail

# Variablen heißen noch ILIAS_LERNER_* (nur für Tests und Sonderfälle)
INSTALL_DIR="${ILIAS_LERNER_INSTALL_DIR:-$HOME/Library/Application Support/StudyHub/app}"
APP="${ILIAS_LERNER_APP:-$HOME/Applications/StudyHub.app}"
OLD_INSTALL_DIR="${ILIAS_LERNER_OLD_INSTALL_DIR:-$HOME/Library/Application Support/ILIAS-Lerner/app}"  # bis 1.0
OLD_APP="${ILIAS_LERNER_OLD_APP:-$HOME/Applications/ILIAS-Lerner.app}"
ARCHIVE="${ILIAS_LERNER_ARCHIVE:-https://github.com/piwi-cell/StudyHub/archive/refs/heads/main.tar.gz}"
MARKER=".ilias-lerner-install"  # nur Ordner mit dieser Datei werden beim Update ersetzt
CLAUDE_INSTALLER="${ILIAS_LERNER_CLAUDE_INSTALLER:-https://claude.ai/install.sh}"
# Dieselben Orte wie server/claude_cli.py: aus dem Finder gestartet fehlt Homebrew im PATH
CLAUDE_PATHS="${ILIAS_LERNER_CLAUDE_PATHS:-$HOME/.local/bin/claude:$HOME/.claude/local/claude:/opt/homebrew/bin/claude:/usr/local/bin/claude}"

fail() { echo "Abbruch: $*" >&2; exit 1; }

# Pfad zu einem vorhandenen „claude“ (Suchpfad, dann die üblichen Orte), sonst leer
find_claude() {
  local found candidate
  found=$(command -v claude 2>/dev/null || true)
  if [ -n "$found" ] && [ -x "$found" ]; then echo "$found"; return; fi
  local IFS=:
  for candidate in $CLAUDE_PATHS; do
    if [ -f "$candidate" ] && [ -x "$candidate" ]; then echo "$candidate"; return; fi
  done
}

# Installiert Claude Code, falls es fehlt. Ein Fehler bricht die Installation von StudyHub nicht ab:
# die App läuft auch ohne Claude Code (andere KI-Anbieter), die Meldung am Ende sagt Bescheid.
ensure_claude() {
  [ -z "${ILIAS_LERNER_SKIP_CLAUDE:-}" ] || return 0
  local found
  found=$(find_claude)
  if [ -n "$found" ]; then
    echo "Claude Code ist schon installiert ($found)."
    return 0
  fi
  echo "Installiere Claude Code (für Claude über das Abo) …"
  if ! curl -fsSL "$CLAUDE_INSTALLER" | bash; then
    echo "Claude Code konnte nicht installiert werden (Installer: $CLAUDE_INSTALLER)."
  fi
}

main() {
  [ "$(uname -s)" = "Darwin" ] || fail "StudyHub läuft nur auf macOS."
  if pgrep -f "$INSTALL_DIR/main.py" >/dev/null 2>&1 || pgrep -f "$OLD_INSTALL_DIR/main.py" >/dev/null 2>&1; then
    fail "StudyHub (ILIAS-Lerner) läuft noch. Bitte die App beenden (⌘Q) und das Skript erneut starten."
  fi

  local source_dir=""
  tmp=$(mktemp -d)  # global: die EXIT-Falle läuft nach dem Ende von main
  trap 'rm -rf "$tmp"' EXIT

  # Quelle: der Projektordner, in dem dieses Skript liegt, sonst das Archiv von GitHub
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    local candidate
    candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    if [ -f "$candidate/main.py" ] && grep -q '^name = "studyhub"' "$candidate/pyproject.toml" 2>/dev/null; then
      source_dir="$candidate"
    fi
  fi
  if [ -z "$source_dir" ]; then
    echo "Lade StudyHub …"
    curl -fsSL "$ARCHIVE" | tar xz -C "$tmp" || fail "Download fehlgeschlagen ($ARCHIVE)."
    source_dir="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [ -f "$source_dir/main.py" ] || fail "Im Archiv fehlt main.py."
  fi

  local update=false
  if [ -e "$INSTALL_DIR" ]; then
    if [ -f "$INSTALL_DIR/$MARKER" ]; then
      update=true
    elif [ -n "$(ls -A "$INSTALL_DIR")" ]; then
      fail "$INSTALL_DIR gibt es schon und stammt nicht von diesem Skript. Bitte prüfen und entfernen."
    fi
  fi

  if [ "$(cd "$source_dir" && pwd -P)" != "$(mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR" && pwd -P)" ]; then
    echo "$([ "$update" = true ] && echo "Aktualisiere" || echo "Installiere") nach $INSTALL_DIR …"
    # Alter Code raus, Python-Umgebung (.venv, .tools) bleibt: das spart den Download und hält
    # Python an derselben Stelle (der Schlüsselbund erkennt die Hintergrund-Jobs daran wieder)
    find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name .venv ! -name .tools -exec rm -rf {} +
    local item
    for item in "$source_dir"/*; do
      case "$(basename "$item")" in
        StudyHub.app | ILIAS-Lerner.app | demo-data) continue ;;
      esac
      cp -R "$item" "$INSTALL_DIR/"
    done
  fi
  touch "$INSTALL_DIR/$MARKER"

  cd "$INSTALL_DIR"
  echo "Richte Python ein (beim ersten Mal einige Minuten) …"
  bash scripts/setup.sh --app
  mkdir -p "$(dirname "$APP")"
  bash scripts/make_app.sh "$APP" >/dev/null
  ensure_claude

  # Umzug vom alten Namen: alte App und alter Programmordner gehen, Daten und Zugangsdaten bleiben
  local renamed=false
  if [ -f "$OLD_INSTALL_DIR/$MARKER" ] && [ "$(cd "$OLD_INSTALL_DIR" && pwd -P)" != "$(pwd -P)" ]; then
    rm -rf "$OLD_INSTALL_DIR"
    rmdir "$(dirname "$OLD_INSTALL_DIR")" 2>/dev/null || true
    renamed=true
  fi
  if [ -f "$OLD_APP/Contents/Info.plist" ] && grep -q "local.ilias-lerner" "$OLD_APP/Contents/Info.plist"; then
    rm -rf "$OLD_APP"
    renamed=true
  fi

  local version
  version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)
  echo
  echo "Fertig: StudyHub $version in $APP"
  if [ "$renamed" = true ]; then
    echo "ILIAS-Lerner heißt jetzt StudyHub: die alte App ist entfernt, Einstellungen, Dateien und Zugangsdaten"
    echo "bleiben. StudyHub.app ggf. neu ins Dock ziehen. Fragt macOS nach dem Schlüsselbund: „Immer erlauben“."
    echo "Claude Desktop: in StudyHub unter Einstellungen › KI › Claude Desktop auf „Aktualisieren“ klicken."
  fi
  if [ -z "${ILIAS_LERNER_SKIP_CLAUDE:-}" ]; then
    local claude
    claude=$(find_claude)
    if [ -n "$claude" ]; then
      echo "Claude Code: gefunden ($claude). Anmelden in StudyHub unter Einstellungen › KI."
    else
      echo "Claude Code: nicht gefunden. StudyHub läuft trotzdem; für Claude über das Abo die Installation"
      echo "später erneut starten (Internetverbindung prüfen) oder einen anderen KI-Anbieter wählen."
    fi
  fi
  echo "Hintergrund-Jobs (Abgleich, Bibliotheken) stellt die App beim nächsten Start auf diese Fassung um."
  echo "Aktualisieren: diesen Befehl erneut ausführen. Entfernen:"
  echo "  bash \"$INSTALL_DIR/scripts/uninstall.sh\""
  # Beim Umzug öffnen: die App stellt die Hintergrund-Jobs auf den neuen Programmordner um
  if { [ "$update" = false ] || [ "$renamed" = true ]; } && [ -z "${ILIAS_LERNER_NO_OPEN:-}" ]; then
    open "$APP"
  fi
}

main "$@"  # erst alles einlesen, dann ausführen: das Skript kann seinen eigenen Ordner ersetzen
