#!/bin/zsh
set -e
cd "$(dirname "$0")"
# venv lives outside Desktop: Desktop is often iCloud-synced → reading thousands of library files is very slow
VENV="$HOME/.venvs/musemonitor"
if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p "$HOME/.venvs"
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
if [ ! -f "$VENV/.req_ok" ] || [ requirements.txt -nt "$VENV/.req_ok" ]; then
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  touch "$VENV/.req_ok"
fi
# run the package from src/ (no install needed)
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python -m musemonitor "$@"
