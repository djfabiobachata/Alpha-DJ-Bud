#!/bin/bash
# Double-click to start Alpha DJ Bud on macOS.
cd "$(dirname "$0")"
VENV="$HOME/Library/Application Support/Alpha DJ Bud/venv"
if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display dialog "Python 3 is required. Open Terminal and run: xcode-select --install" buttons {"OK"}'
  exit 1
fi
if [ ! -x "$VENV/bin/python3" ]; then
  echo "First run: installing the native window (pywebview)…"
  mkdir -p "$(dirname "$VENV")"
  python3 -m venv "$VENV" && "$VENV/bin/python3" -m pip install --quiet --upgrade pip && \
    "$VENV/bin/python3" -m pip install --quiet -r requirements.txt || \
    echo "pywebview not installed: the browser will be used in app mode."
fi
PY="$VENV/bin/python3"; [ -x "$PY" ] || PY=python3
exec "$PY" -m alpha_dj_bud.app "$@"
