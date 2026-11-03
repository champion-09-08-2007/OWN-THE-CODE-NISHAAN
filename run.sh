#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
. .venv/bin/activate
echo "Installing requirements..."
python -m pip install -q --disable-pip-version-check -r requirements.txt
echo
echo "Nishaan is starting. Open http://localhost:8000"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${NISHAAN_PORT:-8000}"
