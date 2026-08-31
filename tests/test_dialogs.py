"""A dialog that fails open would turn the approver into a rubber stamp, so the
question these tests answer is: does anything other than a real click say yes."""

from __future__ import annotations

import subprocess
import types

from voiceisland import dialogs


def fake_run(returncode=0, stdout=""):
    def run(_args, **_kwargs):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return run


def test_the_allow_button_is_the_only_yes(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(0, "Allow\n"))
    assert dialogs.ask_yes_no("t", "b") is True


def test_the_deny_button_is_a_no(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(0, "Deny\n"))
    assert dialogs.ask_yes_no("t", "b") is False


def test_a_timeout_is_a_no(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(0, "__timeout__\n"))
    assert dialogs.ask_yes_no("t", "b") is False


def test_pressing_escape_is_a_no(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(1, ""))
    assert dialogs.ask_yes_no("t", "b") is False


def test_a_dialog_that_cannot_run_is_a_no(monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("no window server")

    monkeypatch.setattr(subprocess, "run", explode)
    assert dialogs.ask_yes_no("t", "b") is False


def test_custom_labels_are_matched_not_the_word_allow(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(0, "Turn off prompts\n"))
    assert dialogs.ask_yes_no("t", "b", allow_label="Turn off prompts") is True
    assert dialogs.ask_yes_no("t", "b", allow_label="Something else") is False


def test_the_text_is_passed_as_an_argument_never_built_into_the_script(monkeypatch):
    captured = {}

    def run(args, **_kwargs):
        captured["args"] = args
        return types.SimpleNamespace(returncode=0, stdout="Deny", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    nasty = 'x" & do shell script "touch /tmp/pwned'
    dialogs.ask_yes_no("title", nasty)

    args = captured["args"]
    script = args[args.index("-e") + 1]
    assert nasty not in script       # the script text never contains the input
    assert nasty in args             # it is a separate argument instead


def test_osascript_is_called_by_absolute_path(monkeypatch):
    captured = {}

    def run(args, **_kwargs):
        captured["binary"] = args[0]
        return types.SimpleNamespace(returncode=0, stdout="Deny", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    dialogs.ask_yes_no("t", "b")
    assert captured["binary"] == "/usr/bin/osascript"


def test_allow_is_read_from_a_named_variable_not_applescript_result(monkeypatch):
    """The script must bind the dialog answer to a name.

    AppleScript's implicit `result` is not reliably set inside an `on run`
    handler; reading it fails with "The variable result is not defined", which
    this module treats as a failed dialog and therefore a deny. Every click of
    Allow was silently a deny.
    """
    assert "set answer to display dialog" in dialogs._SCRIPT
    assert "of answer" in dialogs._SCRIPT
    assert "of result" not in dialogs._SCRIPT
