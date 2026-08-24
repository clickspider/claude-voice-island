"""Settings, file locations, and logging.

Settings live outside the source tree, in the places macOS expects:

    ~/Library/Application Support/ClaudeVoiceIsland/config.json
    ~/Library/Logs/ClaudeVoiceIsland/island.log

Two reasons that matters. A clone of this repository never accumulates your
personal data, and the app still starts when it is installed somewhere you
cannot write to. Set VOICE_ISLAND_HOME to move both somewhere else; the tests
use it to stay out of your real settings.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

APP_NAME = "ClaudeVoiceIsland"
BUNDLE_ID = "com.danielfrey.claudevoiceisland"

# Every setting the app reads, with the value used when it is absent.
# "permissions" and "safe_tools" decide what a spoken sentence is allowed to do,
# so they are the two worth understanding before you change them. See SECURITY.md.
DEFAULTS: dict[str, Any] = {
    "session_id": "",              # Claude Code chat to continue ("" starts a new one)
    "voice": "en-US-AndrewNeural",  # edge voice id, mapped to a macOS voice for "say"
    "tts_engine": "edge",          # "edge" (Microsoft, better) or "say" (offline)
    "whisper_model": "base.en",    # "small.en" is more accurate and slower
    "permissions": "prompt",       # "prompt" | "auto" | "ask", see claude.py
    # Tools allowed to run without a dialog. Searching is on the list because a
    # single question triggers a lot of it; reading is not, because a file path
    # is worth seeing before the file is opened. See SECURITY.md.
    "safe_tools": ["Glob", "Grep", "TodoWrite"],
    "narrate": False,              # speak a short phrase for each action taken
    "ptt": "off",                  # push-to-talk key: off | option | control | command
    "launch_at_login": False,
    "float_pos": None,             # [x, y] of the pill on a screen with no notch
    "log_transcripts": False,      # write what you said and what Claude replied to the log
}

_log = logging.getLogger("voiceisland.config")


def _directory(*fallback: str) -> Path:
    """A directory under VOICE_ISLAND_HOME, or the given place under the home folder."""
    override = os.environ.get("VOICE_ISLAND_HOME")
    base = Path(override) if override else Path.home().joinpath(*fallback)
    base.mkdir(parents=True, exist_ok=True)
    return base


def app_dir() -> Path:
    """Directory holding config.json and the generated MCP config."""
    return _directory("Library", "Application Support", APP_NAME)


def log_path() -> Path:
    return _directory("Library", "Logs", APP_NAME) / "island.log"


def config_path() -> Path:
    return app_dir() / "config.json"


def load() -> dict[str, Any]:
    """Read the config, falling back to defaults for anything missing or broken."""
    values = dict(DEFAULTS)
    try:
        stored = json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return values
    except (OSError, ValueError):
        _log.warning("config unreadable, using defaults", exc_info=True)
        return values
    if isinstance(stored, dict):
        values.update(stored)
    return values


def save(updates: dict[str, Any]) -> None:
    """Merge `updates` into the stored config and write it atomically.

    Partial saves are the normal case: the menu writes one key at a time. Writing
    through a temporary file in the same directory means an interrupted write
    leaves the old config intact instead of a truncated one.
    """
    current = load()
    current.update(updates)
    target = config_path()
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".config-", suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(current, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except OSError:
        _log.warning("config save failed", exc_info=True)
        Path(tmp_name).unlink(missing_ok=True)


def setup_logging() -> None:
    """Send logs to the app's log file, and to stderr when run from a terminal."""
    handlers: list[logging.Handler] = [logging.FileHandler(str(log_path()), encoding="utf-8")]
    if os.environ.get("VOICE_ISLAND_VERBOSE"):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
    # The HTTP client under faster-whisper logs every model download request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
