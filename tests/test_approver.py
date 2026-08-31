"""The approver decides whether anything is allowed to happen, so its failure
modes matter more than its happy path. Everything here checks that it says no."""

from __future__ import annotations

import io
import json

from voiceisland import approver


def test_a_shell_command_is_shown_in_full_when_it_fits():
    body = approver.summarize("Bash", {"command": "rm -rf build"})
    assert "rm -rf build" in body
    assert body.startswith("Run shell command")


def test_a_long_command_says_how_much_is_hidden():
    command = "echo " + "x" * 2000
    body = approver.summarize("Bash", {"command": command})
    assert "not shown" in body
    # The number of hidden characters has to be honest, or the note is worse
    # than no note.
    hidden = len(command) - approver._DETAIL_LIMIT
    assert str(hidden) in body


def test_a_file_edit_names_the_file():
    assert "app.py" in approver.summarize("Edit", {"file_path": "/x/app.py"})


def test_a_tool_with_no_arguments_still_describes_itself():
    assert "Whatever" in approver.summarize("Whatever", {})


def test_broken_input_does_not_raise():
    assert approver.summarize("Bash", "not a dict")


def test_allow_returns_the_input_unchanged(monkeypatch):
    monkeypatch.setattr(approver, "ask_yes_no", lambda **_: True)
    answer = json.loads(approver.decide({"tool_name": "Bash", "input": {"command": "ls"}}))
    assert answer == {"behavior": "allow", "updatedInput": {"command": "ls"}}


def test_deny_is_the_answer_when_the_dialog_says_no(monkeypatch):
    monkeypatch.setattr(approver, "ask_yes_no", lambda **_: False)
    answer = json.loads(approver.decide({"tool_name": "Bash", "input": {"command": "ls"}}))
    assert answer["behavior"] == "deny"


def test_a_missing_tool_name_is_still_asked_about(monkeypatch):
    asked = {}

    def fake(**kwargs):
        asked.update(kwargs)
        return False

    monkeypatch.setattr(approver, "ask_yes_no", fake)
    approver.decide({})
    assert "a tool" in asked["body"]


def _responses(capsys):
    out = capsys.readouterr().out.strip().splitlines()
    return [json.loads(line) for line in out if line]


def test_initialize_answers_with_the_tool_capability(capsys):
    approver.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    result = _responses(capsys)[0]["result"]
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"]["name"] == "approver"


def test_tools_list_advertises_exactly_one_tool(capsys):
    approver.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = _responses(capsys)[0]["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["approval_prompt"]


def test_a_call_comes_back_as_a_text_content_block(capsys, monkeypatch):
    monkeypatch.setattr(approver, "ask_yes_no", lambda **_: True)
    approver.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"arguments": {"tool_name": "Read", "input": {"file_path": "/x"}}},
    })
    content = _responses(capsys)[0]["result"]["content"]
    assert content[0]["type"] == "text"
    assert json.loads(content[0]["text"])["behavior"] == "allow"


def test_an_unknown_method_gets_a_json_rpc_error(capsys):
    approver.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})
    assert _responses(capsys)[0]["error"]["code"] == -32601


def test_a_notification_gets_no_reply(capsys):
    approver.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert _responses(capsys) == []


def _feed(monkeypatch, *messages):
    """Run the loop over a fixed list of messages instead of real stdin."""
    monkeypatch.setattr(
        approver.sys, "stdin",
        io.StringIO("".join(json.dumps(message) + "\n" for message in messages)),
    )
    approver.main()


def test_a_crash_while_asking_still_answers_with_a_deny(capsys, monkeypatch):
    """A handler that falls over must not leave the run hanging.

    Claude Code blocks on the id it sent. Logging the crash and moving on left
    that request unanswered forever: no dialog, no denial, just a turn that
    stopped. Surviving the exception is only half of it.
    """
    def explode(**_kwargs):
        raise RuntimeError("no window server")

    monkeypatch.setattr(approver, "ask_yes_no", explode)
    _feed(monkeypatch, {
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"arguments": {"tool_name": "Bash", "input": {"command": "rm -rf /"}}},
    })
    answered = _responses(capsys)
    assert len(answered) == 1
    assert json.loads(answered[0]["result"]["content"][0]["text"])["behavior"] == "deny"


def test_a_crash_on_anything_else_comes_back_as_an_error(capsys, monkeypatch):
    def explode(_message):
        raise RuntimeError("broken")

    monkeypatch.setattr(approver, "handle", explode)
    _feed(monkeypatch, {"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
    assert _responses(capsys)[0]["error"]["code"] == -32603


def test_a_crash_on_a_notification_answers_nothing(capsys, monkeypatch):
    def explode(_message):
        raise RuntimeError("broken")

    monkeypatch.setattr(approver, "handle", explode)
    _feed(monkeypatch, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert _responses(capsys) == []


def test_json_that_is_not_an_object_does_not_stop_the_loop(capsys, monkeypatch):
    monkeypatch.setattr(
        approver.sys, "stdin",
        io.StringIO('[1, 2]\nnot json at all\n'
                    + json.dumps({"jsonrpc": "2.0", "id": 11, "method": "ping"}) + "\n"),
    )
    approver.main()
    answered = _responses(capsys)
    assert len(answered) == 1 and answered[0]["id"] == 11
