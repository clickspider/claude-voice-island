"""The bridge to the `claude` command line tool.

One spoken sentence becomes one `claude -p` run inside the working directory of
the chat you picked, resuming that chat so the conversation keeps its history.
Output is read as a stream of JSON events, which is what lets the pill show what
Claude is doing while it is still doing it.

There is no API key anywhere in this project. The CLI already carries your Claude
Code subscription, and this is a client of the CLI.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voiceisland import config

_log = logging.getLogger("voiceisland.claude")

# A voice reply is read out loud, so the model is told to answer the way a person
# would answer out loud. Without this you get headings and code fences, and the
# speech engine reads them as "hash hash star".
VOICE_PREFIX = (
    "[Voice message. Your reply will be READ ALOUD by text-to-speech.] "
    "Answer in at most two short, natural spoken sentences. Plain text only: no "
    "markdown, no headings, no bullet points, no code blocks, no URLs, no emojis, "
    "and no symbols like #, *, or backticks. If code or long detail is needed, say "
    "so briefly out loud instead of dictating it. Here is what I said: "
)

# A voice action can legitimately run long: browsing, a multi-step edit, a test
# suite. This is the point where the run is abandoned rather than left hanging.
DEFAULT_TIMEOUT_S = 600

APPROVER_TOOL = "mcp__approver__approval_prompt"

# A GUI app launched from Finder does not inherit the shell PATH, so the CLI has
# to be found the way a shell would have found it.
_SEARCH_PATHS = [
    str(Path.home() / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
]


class ClaudeNotFoundError(RuntimeError):
    """The `claude` executable is not installed or not on any known path."""


def resolve_binary() -> str:
    """Absolute path to the `claude` executable."""
    found = shutil.which("claude")
    if found:
        return found
    for directory in _SEARCH_PATHS:
        candidate = Path(directory) / "claude"
        if candidate.exists():
            return str(candidate)
    raise ClaudeNotFoundError("claude command not found, install Claude Code first")


def subprocess_env() -> dict[str, str]:
    """The parent environment with the search paths prepended, order preserved."""
    env = os.environ.copy()
    ordered: list[str] = []
    for entry in _SEARCH_PATHS + env.get("PATH", "").split(":"):
        if entry and entry not in ordered:
            ordered.append(entry)
    env["PATH"] = ":".join(ordered)
    return env


def mcp_config_path() -> Path:
    return config.app_dir() / "mcp-approver.json"


def write_mcp_config() -> Path:
    """Write the MCP config that points Claude Code at our approver.

    Written at startup rather than shipped as a file, because it has to name the
    interpreter of whatever environment this copy is running in.
    """
    path = mcp_config_path()
    payload = {
        "mcpServers": {
            "approver": {
                "command": sys.executable,
                "args": ["-m", "voiceisland.approver"],
                # The approver is started by Claude Code, not by us, so it is
                # handed the interpreter and the import path of this exact
                # checkout rather than whatever python it would otherwise find.
                # The environment is the minimum it needs and nothing else: this
                # file names a process that gets to answer permission questions.
                "env": {
                    "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                    "PATH": ":".join(_SEARCH_PATHS),
                },
            }
        }
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def build_command(session_id: str, text: str, permissions: str, safe_tools: list[str]) -> list[str]:
    """The full argv for one voice turn.

    permissions:
        "prompt"  every action Claude wants to take pops an Allow/Deny dialog,
                  except the tools in `safe_tools`.
        "auto"    no dialogs at all. Claude runs anything it decides to run.
        "ask"     no approval route is offered, so anything needing approval is
                  refused and Claude works with what it already has.

    Every mode states its permission mode explicitly. Claude Code reads a default
    mode from the user's own settings.json, and a machine set to "auto" there
    skips the approver without a word: it connects, lists its tool, and is never
    called. Saying nothing here meant inheriting whatever that file happened to
    say, which turned both careful modes into no mode at all.

    Anything that is not one of the three names is treated as "prompt", because
    the alternative is that hole again: config.json is a file people hand-edit,
    and a typo there must not be the thing that decides whether you get asked.
    """
    command = [
        resolve_binary(),
        "-p",
        VOICE_PREFIX + text,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if permissions == "auto":
        command.append("--dangerously-skip-permissions")
    elif permissions == "ask":
        # Refuse anything that needs approval, without a dialog, by offering no
        # approval route and a mode that denies rather than asks.
        command += ["--permission-mode", "dontAsk"]
        if safe_tools:
            command += ["--allowedTools", *safe_tools]
    else:
        # "prompt", and anything unrecognised, which lands here rather than
        # falling out of the bottom with no flags at all.
        command += [
            # "default" is the mode that actually asks. Without it the approver
            # below is decoration.
            "--permission-mode", "default",
            "--mcp-config", str(mcp_config_path()),
            "--permission-prompt-tool", APPROVER_TOOL,
        ]
        if safe_tools:
            command += ["--allowedTools", *safe_tools]
    if session_id:
        command += ["--resume", session_id]
    return command


@dataclass
class Reply:
    """What one voice turn produced."""

    text: str
    session_id: str
    events: int = 0
    stderr: str = field(default="", repr=False)


def ask(
    session_id: str,
    cwd: str,
    text: str,
    on_event: Callable[[str, Any], None] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Reply:
    """Send one spoken sentence to Claude and return the reply.

    `on_event` is called as the run happens, from this thread, with:
        ("assistant_text", str)             Claude thinking out loud
        ("tool", {"name", "input"})         a tool call starting
        ("tool_result", {"is_error": bool}) that tool finishing

    A new chat is created when `session_id` is empty, and the id of that new chat
    comes back on the Reply so the next turn can continue it.
    """
    settings = config.load()
    workdir = cwd if cwd and Path(cwd).is_dir() else str(Path.home())
    try:
        command = build_command(
            session_id, text, settings["permissions"], list(settings["safe_tools"])
        )
    except ClaudeNotFoundError:
        _log.error("claude CLI missing")
        return Reply("I could not find the Claude command on this Mac.", session_id)

    try:
        process = subprocess.Popen(
            command,
            cwd=workdir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=subprocess_env(),
        )
    except OSError:
        _log.exception("could not start claude")
        return Reply("I could not start the Claude command.", session_id)

    # stderr is drained on its own thread. Left unread it fills the pipe buffer,
    # the child blocks writing to it, we block reading stdout, and the whole turn
    # hangs until the timeout instead of answering.
    errors: list[str] = []
    drain = threading.Thread(target=_drain, args=(process.stderr, errors), daemon=True)
    drain.start()

    timer = threading.Timer(timeout_s, process.kill)
    timer.start()
    reply, current_session, seen = "", session_id, 0
    try:
        for line in process.stdout:
            event = _parse(line)
            if event is None:
                continue
            seen += 1
            current_session = event.get("session_id") or current_session
            reply = _consume(event, reply, on_event)
    finally:
        timer.cancel()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        drain.join(timeout=2)

    stderr_text = "".join(errors).strip()
    if not reply:
        reply = _failure_text(process.returncode, stderr_text)
        _log.warning("empty reply (exit %s): %s", process.returncode, stderr_text[:400])
    return Reply(reply, current_session, events=seen, stderr=stderr_text)


def _drain(stream, sink: list[str]) -> None:
    if stream is None:
        return
    try:
        for line in stream:
            sink.append(line)
            if len(sink) > 200:  # keep the tail, never grow without bound
                del sink[:100]
    except (OSError, ValueError):
        pass


def _parse(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _consume(event: dict, reply: str, on_event: Callable[[str, Any], None] | None) -> str:
    """Fold one stream event into the reply, reporting anything worth showing."""
    kind = event.get("type")
    if kind == "assistant":
        for block in _blocks(event):
            if block.get("type") == "text":
                text = (block.get("text") or "").strip()
                if text:
                    _emit(on_event, "assistant_text", text)
            elif block.get("type") == "tool_use":
                _emit(on_event, "tool", {
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                })
    elif kind == "user":
        for block in _blocks(event):
            if block.get("type") == "tool_result":
                _emit(on_event, "tool_result", {"is_error": bool(block.get("is_error"))})
    elif kind == "result":
        return (event.get("result") or "").strip() or reply
    return reply


def _blocks(event: dict) -> list[dict]:
    content = (event.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _emit(on_event: Callable[[str, Any], None] | None, kind: str, data: Any) -> None:
    if on_event is None:
        return
    try:
        on_event(kind, data)
    except Exception:  # noqa: BLE001
        # A broken listener must not take down a turn that is otherwise fine.
        _log.exception("event listener failed")


def _failure_text(returncode: int | None, stderr_text: str) -> str:
    if returncode is not None and returncode < 0:
        return "That took too long, so I stopped it. Try asking for something smaller."
    if stderr_text:
        return f"Claude did not reply. {stderr_text.splitlines()[-1][:150]}"
    return "Claude did not reply."
