"""Start at login, using a LaunchAgent.

A plist in ~/Library/LaunchAgents is how a background app asks macOS to start it
at login. Enabling writes the file and loads it; disabling unloads and deletes
it, so turning the setting off leaves nothing behind.

The agent opens the built .app bundle rather than running Python directly. That
keeps the microphone permission attached to one identity: macOS grants access to
the app that asked for it, and a bare interpreter is a different asker every time
its path changes.
"""

from __future__ import annotations

import logging
import plistlib
import subprocess
from pathlib import Path

from voiceisland.config import BUNDLE_ID

_log = logging.getLogger("voiceisland.launchagent")

APP_BUNDLE = Path.home() / "Applications" / "Claude Voice Island.app"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"
LAUNCHCTL = "/bin/launchctl"


def is_enabled() -> bool:
    return PLIST_PATH.exists()


def set_enabled(enabled: bool) -> bool:
    """Turn start-at-login on or off. Returns the state actually reached."""
    try:
        if enabled:
            _install()
        else:
            _remove()
    except (OSError, subprocess.SubprocessError):
        _log.exception("could not change the login item")
    return is_enabled()


def _install() -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": BUNDLE_ID,
        "ProgramArguments": ["/usr/bin/open", "-a", str(APP_BUNDLE)],
        "RunAtLoad": True,
    }
    # plistlib writes valid XML for any path, including one with a quote in it.
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(payload, handle)
    subprocess.run([LAUNCHCTL, "load", "-w", str(PLIST_PATH)], capture_output=True, check=False)


def _remove() -> None:
    subprocess.run([LAUNCHCTL, "unload", "-w", str(PLIST_PATH)], capture_output=True, check=False)
    PLIST_PATH.unlink(missing_ok=True)
