from __future__ import annotations

import json
from pathlib import Path

import pytest

from voiceisland import claude


@pytest.fixture(autouse=True)
def fake_binary(monkeypatch):
    monkeypatch.setattr(claude, "resolve_binary", lambda: "/fake/claude")


def build(permissions="prompt", session_id="", safe_tools=None):
    return claude.build_command(
        session_id, "hello", permissions,
        ["Read"] if safe_tools is None else safe_tools,
    )


def test_the_prompt_carries_the_spoken_instruction():
    command = build()
    assert command[1] == "-p"
    assert command[2].endswith("hello")
    assert "READ ALOUD" in command[2]


def test_output_is_requested_as_a_stream():
    command = build()
    assert "--output-format" in command
    assert command[command.index("--output-format") + 1] == "stream-json"


def test_prompt_mode_routes_approval_through_the_approver():
    command = build("prompt")
    assert "--permission-prompt-tool" in command
    assert command[command.index("--permission-prompt-tool") + 1] == claude.APPROVER_TOOL
    assert "--dangerously-skip-permissions" not in command


def test_prompt_mode_states_the_permission_mode_instead_of_inheriting_it():
    """The approver is only consulted in a mode that asks.

    Claude Code takes a default mode from the user's own settings.json. On a
    machine set to "auto" it connects to the approver, lists its tool, and never
    calls it, so every action runs unannounced. Saying nothing here is what made
    the whole approval gate decorative.
    """
    command = build("prompt")
    assert "--permission-mode" in command
    assert command[command.index("--permission-mode") + 1] == "default"


def test_ask_mode_refuses_rather_than_inheriting_whatever_is_configured():
    """"Answer only, no actions" has to actually deny.

    It used to add no flags at all, which meant it inherited the machine default.
    The mode advertised as the most restrictive was the least restrictive.
    """
    command = build("ask")
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert "--permission-prompt-tool" not in command
    assert "--dangerously-skip-permissions" not in command


@pytest.mark.parametrize("mode", ["prompt", "auto", "ask"])
def test_every_mode_says_what_it_wants_out_loud(mode):
    """No mode may leave the decision to a config file this app does not own."""
    command = build(mode)
    assert "--permission-mode" in command or "--dangerously-skip-permissions" in command


def test_prompt_mode_pre_approves_only_the_listed_tools():
    command = build("prompt", safe_tools=["Read", "Grep"])
    index = command.index("--allowedTools")
    assert command[index + 1: index + 3] == ["Read", "Grep"]


def test_an_empty_safe_list_pre_approves_nothing():
    assert "--allowedTools" not in build("prompt", safe_tools=[])


def test_auto_mode_skips_every_prompt_and_nothing_else():
    command = build("auto")
    assert "--dangerously-skip-permissions" in command
    assert "--permission-prompt-tool" not in command
    assert "--allowedTools" not in command


def test_ask_mode_offers_no_approval_route_at_all():
    command = build("ask")
    assert "--dangerously-skip-permissions" not in command
    assert "--permission-prompt-tool" not in command


def test_a_chat_is_resumed_only_when_there_is_one():
    assert "--resume" not in build(session_id="")
    resumed = build(session_id="abc123")
    assert resumed[resumed.index("--resume") + 1] == "abc123"


def test_the_search_paths_are_prepended_without_losing_the_existing_path(monkeypatch):
    monkeypatch.setenv("PATH", "/custom/bin:/usr/bin")
    path = claude.subprocess_env()["PATH"].split(":")
    assert "/custom/bin" in path
    assert path.index("/opt/homebrew/bin") < path.index("/custom/bin")
    assert len(path) == len(set(path))  # no duplicates


def test_the_mcp_config_points_at_this_checkout():
    path = claude.write_mcp_config()
    server = json.loads(path.read_text())["mcpServers"]["approver"]
    assert server["args"] == ["-m", "voiceisland.approver"]
    import_root = Path(server["env"]["PYTHONPATH"])
    assert (import_root / "voiceisland" / "approver.py").exists()


# ---- reading the event stream -------------------------------------------


def assistant(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def collector():
    """A listener plus the list it fills."""
    seen: list[tuple] = []
    return seen, lambda kind, data: seen.append((kind, data))


def test_text_blocks_are_reported_as_they_arrive():
    seen, listener = collector()
    claude._consume(assistant({"type": "text", "text": "  thinking  "}), "", listener)
    assert seen == [("assistant_text", "thinking")]


def test_empty_text_blocks_are_not_reported():
    seen, listener = collector()
    claude._consume(assistant({"type": "text", "text": "   "}), "", listener)
    assert seen == []


def test_tool_calls_are_reported_with_their_arguments():
    seen, listener = collector()
    claude._consume(
        assistant({"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}),
        "", listener,
    )
    assert seen == [("tool", {"name": "Bash", "input": {"command": "ls"}})]


def test_a_failed_tool_result_is_marked_as_an_error():
    seen, listener = collector()
    claude._consume(
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True}]}},
        "", listener,
    )
    assert seen == [("tool_result", {"is_error": True})]


def test_the_result_event_becomes_the_reply():
    assert claude._consume({"type": "result", "result": " done "}, "", None) == "done"


def test_an_empty_result_keeps_what_was_already_there():
    assert claude._consume({"type": "result", "result": ""}, "earlier", None) == "earlier"


def test_a_listener_that_raises_does_not_break_the_turn():
    def broken(_kind, _data):
        raise RuntimeError("listener is broken")

    reply = claude._consume(assistant({"type": "text", "text": "hi"}), "", broken)
    assert reply == ""


def test_malformed_events_are_ignored():
    assert claude._parse("not json") is None
    assert claude._parse("") is None
    assert claude._parse("[1, 2]") is None
    assert claude._parse('{"type": "result"}') == {"type": "result"}


def test_a_killed_run_explains_itself_as_a_timeout():
    assert "too long" in claude._failure_text(-9, "")


def test_a_failure_quotes_the_last_line_of_the_error():
    assert "boom" in claude._failure_text(1, "some noise\nboom")


def test_a_silent_failure_still_says_something():
    assert claude._failure_text(1, "")


def test_an_unrecognised_mode_asks_rather_than_inheriting(monkeypatch):
    """A mode nobody recognises must land on the careful branch.

    config.json is hand-edited, and every mode used to be an explicit `elif`
    with nothing at the bottom, so "Prompt", "propmt", or a value written by a
    later version fell straight through and added no flags at all. That is the
    same hole the explicit modes were added to close: no flags means Claude Code
    reads permissions.defaultMode from the user's own settings.json instead.
    """
    for mode in ("propmt", "Prompt", "", "plan", None):
        command = claude.build_command("", "hello", mode, ["Grep"])
        assert command[command.index("--permission-mode") + 1] == "default"
        assert command[command.index("--permission-prompt-tool") + 1] == claude.APPROVER_TOOL
        assert "--dangerously-skip-permissions" not in command
