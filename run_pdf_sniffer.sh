#!/usr/bin/env sh
# Linux / macOS launcher.  Installs the libraries into ./runtime on first use (needs Python 3.10+ and internet once).
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if [ ! -f runtime/.installed ]; then
  echo "First-time setup: installing libraries into $(pwd)/runtime/site-packages ..."
  "$PY" -m pip install --quiet --target runtime/site-packages -r requirements.txt
  touch runtime/.installed
fi
PYTHONPATH="$(pwd)/runtime/site-packages:$(pwd)" exec "$PY" -m pdf_sniffer "$@"
