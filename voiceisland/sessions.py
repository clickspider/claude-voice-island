"""Finding the Claude Code chats you can talk to.

Claude Code keeps one JSONL file per chat under ~/.claude/projects/, named by
session id, inside a directory named after the working directory. That is enough
to rebuild a picker: the id to resume, the directory to run in, and the first
thing you typed, which is what you actually recognise a chat by.

Only the head of each file is read. Some of these files are tens of megabytes,
and everything needed is in the first few lines.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
_HOME = str(Path.home())

# Enough lines to find the working directory and the first human message, and
# few enough that a huge chat log costs nothing to scan.
_MAX_SCAN_LINES = 400
_TITLE_CHARS = 70

# Lines Claude Code writes that are not something a person typed.
_MACHINE_PREFIXES = ("<", "Caveat:", "[Request")


@dataclass
class Session:
    """One Claude Code chat."""

    id: str
    cwd: str
    project: str
    title: str
    mtime: float
    # Position in the recency-ordered list, 1 for the most recent. Only shown
    # while titles are hidden, where several chats can share the same "19m ago"
    # and the order is otherwise impossible to read.
    rank: int = 0

    @property
    def name(self) -> str:
        return self.title or "(untitled chat)"

    @property
    def is_repo(self) -> bool:
        """True when the chat runs in a project directory rather than at home."""
        return bool(self.cwd) and self.cwd != _HOME

    def label(self, private: bool = False) -> str:
        """The picker line: the chat's own name, plus the project when it adds anything.

        Chats started from the home directory get a project name that is just the
        username, which tells you nothing, so it is left off.

        With `private` set, nothing you typed is shown. See private_label.
        """
        if private:
            return self.private_label()
        return f"{self.name}   ·  {self.project}" if self.is_repo else self.name

    def private_label(self) -> str:
        """A name for this chat that gives away nothing you typed.

        The ordinary label is the first thing you said to the chat, because that
        is what you recognise it by. That works right up until someone else is
        looking at your screen, at which point the picker is a list of your
        private business.

        Two things are safe to show. How long ago you last spoke to a chat, which
        is how people actually find one in a list already sorted by recency, and
        a short slice of the session id, which is stable, unique enough to tell
        two chats apart, and means nothing to anyone.

        The project name is deliberately left out. It reads as harmless and is
        not: a directory can be named after a person, a case, or a diagnosis.
        """
        if not self.id:
            return "New chat"
        position = f"{self.rank}. " if self.rank else ""
        if self.mtime <= 0:
            # A chat started in this session has no file on disk yet, so an age
            # would be invented rather than unknown.
            return f"{position}Chat {self.id[:4]}"
        return f"{position}Chat {self.id[:4]}   ·  {_age(self.mtime)}"


def _age(mtime: float) -> str:
    """How long ago, short enough to sit in a menu line."""
    if mtime <= 0:
        return "unknown"
    seconds = max(0.0, time.time() - mtime)
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def list_sessions(limit: int = 25) -> list[Session]:
    """The most recently active chats, newest first."""
    if not PROJECTS_DIR.exists():
        return []
    files = _by_recency(PROJECTS_DIR.glob("*/*.jsonl"))
    found: list[Session] = []
    # Scan more files than asked for: some hold no usable chat at all.
    for path, mtime in files[: limit * 2]:
        cwd, title = _scan(path)
        found.append(
            Session(
                id=path.stem,
                cwd=cwd or _HOME,
                project=os.path.basename(cwd) if cwd else path.parent.name,
                title=title or "(no prompt yet)",
                mtime=mtime,
                rank=len(found) + 1,
            )
        )
        if len(found) >= limit:
            break
    return found


def _by_recency(paths) -> list[tuple[Path, float]]:
    """(path, mtime) newest first, skipping files that vanish while we look."""
    stamped: list[tuple[Path, float]] = []
    for path in paths:
        try:
            stamped.append((path, path.stat().st_mtime))
        except OSError:
            continue  # a chat deleted or rotated mid-scan is simply not listed
    stamped.sort(key=lambda item: item[1], reverse=True)
    return stamped


def _scan(path: Path) -> tuple[str | None, str | None]:
    """Read the head of a chat file for (working directory, first human message)."""
    cwd: str | None = None
    title: str | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= _MAX_SCAN_LINES or (cwd and title):
                    break
                record = _json_object(line)
                if record is None:
                    continue
                if cwd is None and isinstance(record.get("cwd"), str):
                    cwd = record["cwd"]
                if title is None:
                    title = _human_message(record)
    except OSError:
        pass
    return cwd, title


def _json_object(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _human_message(record: dict) -> str | None:
    """The text of a message a person actually typed, or None."""
    if record.get("type") != "user":
        return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    text = _text_of(message.get("content"))
    if not text or text.startswith(_MACHINE_PREFIXES):
        return None
    return " ".join(text.split())[:_TITLE_CHARS]


def _text_of(content) -> str | None:
    """Message content is either a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                value = block.get("text")
                if isinstance(value, str):
                    return value
    return None
