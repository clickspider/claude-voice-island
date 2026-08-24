#!/bin/bash
# Create the virtual environment and install what the app needs.
# Safe to run again: it reuses an existing venv and re-installs into it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "python3 was not found. Install Python 3.11 or newer." >&2
    exit 1
fi

version="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
required="3.11"
if [ "$(printf '%s\n%s\n' "$required" "$version" | sort -V | head -1)" != "$required" ]; then
    echo "Python $version found, but this needs $required or newer." >&2
    exit 1
fi

if [ ! -d venv ]; then
    echo "Creating venv"
    "$PYTHON" -m venv venv
fi

echo "Installing dependencies"
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

if ! command -v claude >/dev/null 2>&1; then
    echo
    echo "Note: the 'claude' command was not found on your PATH."
    echo "Install Claude Code and sign in, or the app will have nothing to talk to."
fi

echo
echo "Done. Start it with:  ./start.command"
echo "Or build a double-clickable app with:  ./scripts/make_app.sh"
