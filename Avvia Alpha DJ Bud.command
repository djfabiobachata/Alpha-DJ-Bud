#!/bin/bash
# Doppio clic per avviare Alpha DJ Bud su macOS.
cd "$(dirname "$0")"
VENV="$HOME/Library/Application Support/Alpha DJ Bud/venv"
if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display dialog "Serve Python 3. Apri il Terminale e lancia: xcode-select --install" buttons {"OK"}'
  exit 1
fi
if [ ! -x "$VENV/bin/python3" ]; then
  echo "Prima installazione: preparo la finestra nativa (pywebview)…"
  mkdir -p "$(dirname "$VENV")"
  python3 -m venv "$VENV" && "$VENV/bin/python3" -m pip install --quiet --upgrade pip && \
    "$VENV/bin/python3" -m pip install --quiet -r requirements.txt || \
    echo "pywebview non installato: userò il browser in modalità app."
fi
PY="$VENV/bin/python3"; [ -x "$PY" ] || PY=python3
exec "$PY" -m alpha_dj_bud.app "$@"
