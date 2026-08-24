#!/bin/bash
# Double-click this in Finder to start the island.
#
# Starting it from Finder or a terminal is what makes macOS attribute the
# microphone prompt to something you recognise the first time it appears.
#
# There is no "kill the old one" step here. The app takes a lock on startup and
# a second copy exits by itself, so nothing on your Mac gets killed by a pattern
# match on a process name.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x venv/bin/python ]; then
    echo "No venv yet. Running setup first."
    ./scripts/setup.sh
fi

echo "Starting Claude Voice Island. Hover the notch to reveal it."
echo "Hold the pill to talk, release to send, tap while it speaks to interrupt."
exec ./venv/bin/python -m voiceisland
