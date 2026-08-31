from __future__ import annotations

import json
import os

import pytest

from voiceisland import sessions


def write_chat(root, project, chat_id, records, mtime=None):
    directory = root / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{chat_id}.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def user_message(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


@pytest.fixture
def projects(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(sessions, "PROJECTS_DIR", root)
    return root


def test_a_chat_is_named_by_its_first_prompt(projects):
    write_chat(projects, "-Users-x-app", "abc", [
        {"cwd": "/Users/x/app"},
        user_message("fix the login bug"),
    ])
    found = sessions.list_sessions()
    assert len(found) == 1
    assert found[0].id == "abc"
    assert found[0].title == "fix the login bug"
    assert found[0].cwd == "/Users/x/app"
    assert found[0].project == "app"


def test_newest_chats_come_first(projects):
    write_chat(projects, "p", "old", [user_message("first")], mtime=1_000)
    write_chat(projects, "p", "new", [user_message("second")], mtime=2_000)
    assert [s.id for s in sessions.list_sessions()] == ["new", "old"]


def test_the_limit_is_respected(projects):
    for index in range(6):
        write_chat(projects, "p", f"chat{index}", [user_message(f"prompt {index}")],
                   mtime=1_000 + index)
    assert len(sessions.list_sessions(limit=3)) == 3


def test_machine_written_lines_are_not_treated_as_a_prompt(projects):
    write_chat(projects, "p", "abc", [
        user_message("<command-name>/compact</command-name>"),
        user_message("Caveat: this was generated"),
        user_message("what does this function do"),
    ])
    assert sessions.list_sessions()[0].title == "what does this function do"


def test_content_blocks_are_read_as_well_as_plain_strings(projects):
    write_chat(projects, "p", "abc", [
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "image"},
            {"type": "text", "text": "look at this screenshot"},
        ]}},
    ])
    assert sessions.list_sessions()[0].title == "look at this screenshot"


def test_a_chat_with_no_prompt_is_still_listed(projects):
    write_chat(projects, "p", "empty", [{"cwd": "/Users/x/app"}])
    assert sessions.list_sessions()[0].title == "(no prompt yet)"


def test_broken_lines_are_skipped_not_fatal(projects):
    path = write_chat(projects, "p", "abc", [user_message("real prompt")])
    path.write_text("not json\n" + path.read_text())
    assert sessions.list_sessions()[0].title == "real prompt"


def test_a_long_prompt_is_cut_and_collapsed(projects):
    write_chat(projects, "p", "abc", [user_message("word  \n  " * 40)])
    title = sessions.list_sessions()[0].title
    assert len(title) <= 70
    assert "\n" not in title


def test_no_projects_directory_means_no_chats(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "PROJECTS_DIR", tmp_path / "missing")
    assert sessions.list_sessions() == []


def test_the_project_name_is_dropped_for_chats_started_at_home():
    home = sessions.Session(id="a", cwd=sessions._HOME, project="someone",
                            title="a question", mtime=0)
    assert home.label() == "a question"

    repo = sessions.Session(id="b", cwd="/Users/someone/code/app", project="app",
                            title="a question", mtime=0)
    assert "app" in repo.label()


# ---- hiding what you typed ----------------------------------------------
# The picker names every chat after the first thing you said to it, which is
# also the reason you cannot share your screen while it is open. These check
# that turning that off actually gives nothing away.


def test_a_private_label_repeats_nothing_you_typed():
    chat = sessions.Session(id="9f3c1d22-aaaa", cwd="/Users/x/lawsuit-marchetti",
                            project="lawsuit-marchetti", title="draft the settlement offer",
                            mtime=0, rank=2)
    label = chat.private_label()
    assert "settlement" not in label
    # The project name is not safe either: a directory gets named after a person,
    # a case, or a diagnosis just as often as after a repository.
    assert "marchetti" not in label.lower()
    assert "2." in label
    assert "9f3c" in label


def test_the_private_label_is_what_the_picker_asks_for():
    chat = sessions.Session(id="abc123", cwd="/Users/x/app", project="app",
                            title="medical results", mtime=0)
    assert "medical" not in chat.label(private=True)
    assert "medical" in chat.label(private=False)


def test_a_chat_with_no_file_yet_does_not_invent_an_age():
    chat = sessions.Session(id="abc123", cwd="", project="", title="x", mtime=0.0)
    assert "ago" not in chat.private_label()


def test_a_brand_new_chat_has_nothing_to_hide():
    fresh = sessions.Session(id="", cwd="", project="", title="New chat", mtime=0.0)
    assert fresh.private_label() == "New chat"


def test_chats_are_ranked_so_a_hidden_list_is_still_readable(projects):
    # Two chats touched in the same minute read as the same "19m ago", so the
    # rank is the only thing telling them apart once the titles are gone.
    for index in range(3):
        write_chat(projects, "p", f"chat{index}", [user_message(f"prompt {index}")],
                   mtime=1_000 + index)
    found = sessions.list_sessions()
    assert [chat.rank for chat in found] == [1, 2, 3]
    assert found[0].id == "chat2"
