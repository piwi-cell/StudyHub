#!/bin/bash
# Erzeugt das App-Symbol neu, nachdem assets/icon.svg geändert wurde (braucht die Xcode Command Line Tools).
# Ergebnis wird eingecheckt: assets/AppIcon.icns (für make_app.sh) und assets/icon-512.png (Dock-Symbol in main.py).
#   bash scripts/make_icon.sh
set -euo pipefail
cd "$(dirname "$0")/.."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
swift scripts/render_icon.swift assets/icon.svg "$tmp"  # SVG → PNGs mit transparentem Hintergrund
iconset="$tmp/AppIcon.iconset"
mkdir "$iconset"
for size in 16 32 128 256 512; do
  cp "$tmp/$size.png" "$iconset/icon_${size}x${size}.png"
  cp "$tmp/$((size * 2)).png" "$iconset/icon_${size}x${size}@2x.png"
done
iconutil -c icns "$iconset" -o assets/AppIcon.icns
cp "$tmp/512.png" assets/icon-512.png
echo "Fertig: assets/AppIcon.icns und assets/icon-512.png"
