#!/bin/bash
# Richtet die Umgebung ein: uv (geprüfte Version), Python 3.13, .venv mit allen Abhängigkeiten nach uv.lock.
#   bash scripts/setup.sh         Entwicklung (mit pytest und ruff)
#   bash scripts/setup.sh --app   nur was die App braucht (scripts/install.sh)
set -euo pipefail
cd "$(dirname "$0")/.."

UV_VERSION="0.12.19"
[ "$(uname -s)" = "Darwin" ] || { echo "Nur macOS."; exit 1; }
case "$(uname -m)" in
  arm64)  UV_ARCH="aarch64"; UV_SHA256="a9a8df1eedeb192f2e47e40e2faabfb387db4b850209118786d42f89dde3e0ba" ;;
  x86_64) UV_ARCH="x86_64";  UV_SHA256="cb5fa57bafe68fc0fb94b17f06bee0b0b9a7feb94ccbd110445afa0696e39273" ;;
  *) echo "Unbekannter Prozessor: $(uname -m)"; exit 1 ;;
esac

mkdir -p .tools
if [ "$(.tools/uv --version 2>/dev/null | cut -d' ' -f2)" != "$UV_VERSION" ]; then
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/uv.tar.gz" \
    "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_ARCH-apple-darwin.tar.gz"
  echo "$UV_SHA256  $tmp/uv.tar.gz" | shasum -a 256 -c --status || { echo "Prüfsumme falsch, Abbruch."; exit 1; }
  tar xzf "$tmp/uv.tar.gz" -C .tools --strip-components 1 "uv-$UV_ARCH-apple-darwin/uv"
  rm -rf "$tmp"
fi

export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"
if [ "${1:-}" = "--app" ]; then
  .tools/uv sync --quiet --locked --no-dev  # .venv exakt nach uv.lock, ohne Test-Werkzeuge
else
  .tools/uv sync --quiet  # .venv exakt nach uv.lock, inklusive Test-Werkzeugen
  echo "Fertig. Starten mit:  ./\"ILIAS-Sync starten.command\"   (Vorführung mit Beispieldaten: --demo)"
fi
