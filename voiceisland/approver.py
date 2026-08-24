"""An MCP server with one tool: ask the human before Claude does anything.

Claude Code is started with `--permission-prompt-tool
mcp__approver__approval_prompt`, which makes it call this server before every
tool it is not already allowed to use. This process answers with allow or deny,
and it only answers allow after a dialog on screen was clicked.

Run it directly to talk to it by hand:

    python -m voiceisland.approver

It speaks newline-delimited JSON-RPC over stdin and stdout, hand-rolled rather
than pulled from a library. The whole protocol surface used here is four
methods, and a dependency-free approver is one less package in the trust chain
of the component whose entire job is saying no.

Contract: the prompt tool receives {tool_name, input} and replies with a
JSON-encoded {"behavior": "allow", "updatedInput": ...} or
{"behavior": "deny", "message": ...}, wrapped in an MCP text content block.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from voiceisland.dialogs import ask_yes_no

SERVER_NAME = "approver"
TOOL_NAME = "approval_prompt"
PROTOCOL_VERSION = "2024-11-05"

# No answer inside two minutes counts as a no.
DIALOG_TIMEOUT_S = 120
# How much of a command or payload the dialog shows. Anything longer is marked
# as cut off, because approving a command whose tail you cannot see is not
# approval.
_DETAIL_LIMIT = 900


def _clip(text: str, limit: int = _DETAIL_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[... {len(text) - limit} more characters not shown]"


def summarize(tool_name: str, tool_input: Any) -> str:
    """One readable description of what is about to happen."""
    fields = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "Bash":
        return "Run shell command:\n\n" + _clip(str(fields.get("command", "")))
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return f"Edit file:\n\n{fields.get('file_path', 'unknown file')}"
    if tool_name == "Read":
        return f"Read file:\n\n{fields.get('file_path', 'unknown file')}"
    if tool_name in ("WebFetch", "WebSearch"):
        target = fields.get("url") or fields.get("query") or ""
        return f"{tool_name}:\n\n{_clip(str(target))}"
    body = _clip(json.dumps(fields, ensure_ascii=False)) if fields else ""
    if tool_name.startswith("mcp__"):
        pretty = tool_name.replace("mcp__", "").replace("__", " · ")
        return f"Use {pretty}:\n\n{body}"
    return f"Use tool {tool_name}\n\n{body}".strip()


def decide(args: dict) -> str:
    """Ask on screen, then return the JSON string Claude Code expects."""
    tool_name = str(args.get("tool_name") or "a tool")
    tool_input = args.get("input") or {}
    allowed = ask_yes_no(
        title="Claude Voice Island: approve this action?",
        body=summarize(tool_name, tool_input),
        timeout_s=DIALOG_TIMEOUT_S,
    )
    _log("ALLOW" if allowed else "DENY", tool_name)
    if allowed:
        return json.dumps({"behavior": "allow", "updatedInput": tool_input})
    return json.dumps({"behavior": "deny", "message": "Denied on screen."})


# ---- JSON-RPC over stdio -------------------------------------------------
# stdout carries the protocol and must stay clean, so anything human-readable
# goes to stderr, where Claude Code collects it.


def _log(*parts: str) -> None:
    print("[approver]", *parts, file=sys.stderr, flush=True)


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _reply(request_id: Any, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Ask the human to approve or deny a tool call on screen.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "tool_name": {"type": "string"},
            "input": {"type": "object"},
        },
        "required": ["tool_name", "input"],
    },
}


def handle(message: dict) -> None:
    """Answer one JSON-RPC message. Notifications (no id) get no reply."""
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        _reply(request_id, {
            "protocolVersion": requested or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
        })
    elif method == "tools/list":
        _reply(request_id, {"tools": [TOOL_SCHEMA]})
    elif method == "tools/call":
        arguments = (message.get("params") or {}).get("arguments") or {}
        _reply(request_id, {"content": [{"type": "text", "text": decide(arguments)}]})
    elif method == "ping":
        _reply(request_id, {})
    elif request_id is not None:
        _error(request_id, -32601, f"method not found: {method}")


def main() -> None:
    _log("ready")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _log("ignoring malformed line")
            continue
        try:
            handle(message)
        except Exception as exc:  # noqa: BLE001
            # A crash here would leave Claude Code waiting on a permission answer
            # that never comes, so the loop survives anything one message does.
            _log(f"handler error: {exc!r}")


if __name__ == "__main__":
    main()
