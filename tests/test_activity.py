from __future__ import annotations

import pytest

from voiceisland import activity


@pytest.mark.parametrize(
    ("tool", "arguments", "expected_icon", "expected_start"),
    [
        ("Bash", {"command": "pytest -q"}, "terminal", "Run: pytest -q"),
        ("Edit", {"file_path": "/a/b/pipeline.py"}, "pencil", "Edit pipeline.py"),
        ("Read", {"file_path": "/a/b/notes.md"}, "doc.text", "Read notes.md"),
        ("Grep", {"pattern": "TODO"}, "magnifyingglass", "Search TODO"),
        ("WebSearch", {"query": "swift notch"}, "globe", "Web search: swift notch"),
        ("TodoWrite", {}, "checklist", "Update the plan"),
    ],
)
def test_known_tools_read_like_sentences(tool, arguments, expected_icon, expected_start):
    icon, line = activity.describe(tool, arguments)
    assert icon == expected_icon
    assert line.startswith(expected_start)


def test_a_path_is_shown_as_a_filename_not_a_path():
    _icon, line = activity.describe("Write", {"file_path": "/Users/someone/deep/tree/app.py"})
    assert line == "Edit app.py"
    assert "/Users/someone" not in line


def test_a_long_command_is_cut_to_fit_the_pill():
    _icon, line = activity.describe("Bash", {"command": "echo " + "x" * 500})
    assert len(line) <= 51


def test_whitespace_in_a_command_is_collapsed():
    _icon, line = activity.describe("Bash", {"command": "ls   -la\n  /tmp"})
    assert line == "Run: ls -la /tmp"


def test_an_mcp_browser_tool_is_recognised():
    icon, line = activity.describe("mcp__chrome__navigate", {})
    assert icon == "safari"
    assert line == "Browsing the web"


def test_an_unknown_mcp_tool_shows_its_server():
    icon, line = activity.describe("mcp__weather__forecast", {})
    assert icon == "puzzlepiece.extension"
    assert line == "weather"


def test_an_unknown_tool_is_still_shown():
    icon, line = activity.describe("SomethingNew", {})
    assert icon == "wrench.and.screwdriver"
    assert line == "SomethingNew"


def test_missing_arguments_do_not_raise():
    assert activity.describe("Bash", None) == ("terminal", "Run: command")
    assert activity.describe("Read", {}) == ("doc.text", "Read a file")


def test_spoken_phrases_are_short_enough_to_say():
    for tool in ("Bash", "Read", "Edit", "WebSearch", "Unknown"):
        phrase = activity.spoken(tool)
        assert phrase.endswith(".")
        assert len(phrase.split()) <= 5
