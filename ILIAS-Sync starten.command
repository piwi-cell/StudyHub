#!/bin/bash
# Doppelklick startet die App. Mit Beispieldaten: im Terminal  ./"ILIAS-Sync starten.command" --demo
cd "$(dirname "$0")"
exec .venv/bin/python main.py "$@"
