"""One instance at a time, without killing anything.

The obvious way to guarantee a single instance is `pkill -f island.py` in the
launcher. It also kills any editor, terminal, or unrelated script whose command
line happens to contain that text, on someone else's Mac, silently. So instead
this takes an exclusive flock on a file: the kernel releases it when the process
ends, including when it crashes, so there is no stale lock to clean up and no
process to guess at.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO

from voiceisland import config


class AlreadyRunningError(RuntimeError):
    """Another copy of the app holds the lock."""


def acquire(name: str = "island.lock") -> IO[str]:
    """Take the single-instance lock, or raise AlreadyRunningError.

    The returned handle must stay referenced for as long as the app runs. Closing
    it releases the lock.
    """
    path: Path = config.app_dir() / name
    handle = path.open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise AlreadyRunningError(f"another instance holds {path}") from exc
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle
