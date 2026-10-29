#!/bin/bash
# Doppelklick-Variante von install.sh (öffnet ein Terminal-Fenster)
bash "$(dirname "$0")/install.sh"
echo
read -r -p "  Fertig. Enter drücken zum Schließen … "
