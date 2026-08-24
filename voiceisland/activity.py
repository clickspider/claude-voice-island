"""Turning tool calls into something a human can read at a glance.

While Claude works, the pill shows a running list of what it is doing. Raw tool
names and JSON arguments are the wrong thing to put there: you are looking at a
strip of glass under a notch, usually while doing something else, and you need
to know "it is editing pipeline.py" without stopping to parse anything.

Every mapping here is pure, which is why this is a module of its own rather than
a method on the view. It is the part worth testing.
"""

from __future__ import annotations

from pathlib import Path

# SF Symbol names, drawn by the pill. A tool with no entry falls back to a
# generic one rather than being hidden, because an unexplained action is exactly
# the one you want to see.
_FALLBACK_ICON = "wrench.and.screwdriver"

_BROWSER_HINTS = ("chrome", "browse", "playwright", "puppeteer")

_SPOKEN = {
    "Bash": "Running a command.",
    "Read": "Reading a file.",
    "Write": "Editing a file.",
    "Edit": "Editing a file.",
    "MultiEdit": "Editing a file.",
    "NotebookEdit": "Editing a file.",
    "Glob": "Searching files.",
    "Grep": "Searching files.",
    "WebSearch": "Searching the web.",
    "WebFetch": "Fetching a page.",
    "Task": "Starting a sub agent.",
    "TodoWrite": "Updating the plan.",
}


def _filename(value) -> str:
    if not value:
        return ""
    try:
        return Path(str(value)).name
    except (TypeError, ValueError):
        return str(value)


def describe(tool_name: str, tool_input: dict | None) -> tuple[str, str]:
    """(icon, one line) for a tool call, as shown in the activity list."""
    fields = tool_input or {}
    if tool_name == "Bash":
        command = " ".join(str(fields.get("command", "")).split())
        return ("terminal", "Run: " + (command[:46] or "command"))
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("pencil", "Edit " + (_filename(fields.get("file_path")) or "a file"))
    if tool_name == "Read":
        return ("doc.text", "Read " + (_filename(fields.get("file_path")) or "a file"))
    if tool_name in ("Glob", "Grep"):
        return ("magnifyingglass", "Search " + (str(fields.get("pattern", ""))[:34] or "files"))
    if tool_name == "WebSearch":
        return ("globe", "Web search: " + str(fields.get("query", ""))[:32])
    if tool_name == "WebFetch":
        return ("globe", "Fetch a web page")
    if tool_name == "Task":
        return ("sparkles", "Sub-agent: " + str(fields.get("description", ""))[:30])
    if tool_name == "TodoWrite":
        return ("checklist", "Update the plan")
    if tool_name.startswith("mcp__"):
        if any(hint in tool_name for hint in _BROWSER_HINTS):
            return ("safari", "Browsing the web")
        server = tool_name.replace("mcp__", "").split("__")[0]
        return ("puzzlepiece.extension", server[:26] or "tool")
    return (_FALLBACK_ICON, tool_name[:30] or "tool")


def spoken(tool_name: str) -> str:
    """A phrase short enough to say out loud between two actions."""
    if tool_name in _SPOKEN:
        return _SPOKEN[tool_name]
    if tool_name.startswith("mcp__") and any(hint in tool_name for hint in _BROWSER_HINTS):
        return "Browsing."
    return "Working."
