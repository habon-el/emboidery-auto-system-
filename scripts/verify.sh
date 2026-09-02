#!/usr/bin/env bash
# One-command "did the latest update work" check, for Linux/macOS.
#
#   ./scripts/verify.sh
#
# Pulls the latest code, makes sure the venv has whatever new
# dependencies were added, runs the full test suite, and then starts
# the local web UI and opens it in your browser -- so every update
# ends with something you can actually click through, not just a wall
# of test output. See scripts/verify.bat for the Windows equivalent.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== git pull =="
git pull

if [ ! -d .venv ]; then
    echo "== creating .venv (first run) =="
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "== installing/updating dependencies =="
pip install -q -r requirements.txt

echo
echo "== running the full test suite =="
python -m pytest tests/ -q

echo
echo "== starting the web UI at http://127.0.0.1:5000 =="
python -m webapp.app &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT

sleep 2
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://127.0.0.1:5000 >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
    open http://127.0.0.1:5000 || true
else
    echo "Open http://127.0.0.1:5000 in your browser."
fi

echo "Press Ctrl+C to stop the server."
wait $SERVER_PID
