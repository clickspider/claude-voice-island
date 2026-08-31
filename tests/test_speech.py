from __future__ import annotations

from typing import ClassVar

from voiceisland import speech


def test_code_blocks_are_not_dictated():
    cleaned = speech.for_speech("Try this:\n```python\nprint('hi')\n```\nthen run it")
    assert "print" not in cleaned
    assert "code omitted" in cleaned


def test_inline_code_keeps_the_word_and_drops_the_backticks():
    assert speech.for_speech("run `pytest` now") == "run pytest now"


def test_a_link_becomes_the_words_a_link():
    assert speech.for_speech("see https://example.com/x?y=1") == "see a link"


def test_a_markdown_link_keeps_only_its_label():
    assert speech.for_speech("[the docs](https://example.com)") == "the docs"


def test_bullets_and_headings_lose_their_markers():
    cleaned = speech.for_speech("## Steps\n- first\n* second")
    assert cleaned == "Steps first second"


def test_whitespace_is_collapsed():
    assert speech.for_speech("too    many\n\n\nspaces") == "too many spaces"


def test_a_very_long_reply_is_cut_rather_than_read_for_a_minute():
    assert len(speech.for_speech("word " * 500)) <= 700


def test_nothing_to_say_stays_nothing():
    assert speech.for_speech("   ") == ""
    assert speech.for_speech("###") == ""


def test_every_offered_voice_has_an_offline_equivalent():
    for _label, voice_id, macos_name in speech.VOICE_CHOICES:
        assert speech._macos_voice(voice_id) == macos_name


def test_an_unknown_voice_falls_back_rather_than_failing():
    assert speech._macos_voice("something-made-up") == "Samantha"


class _FakePopen:
    """Stands in for a player process that was actually started."""

    started: ClassVar[list[list[str]]] = []

    def __init__(self, command):
        _FakePopen.started.append(command)

    def wait(self):
        return 0

    def poll(self):
        return None

    def terminate(self):
        pass


def test_a_stop_during_synthesis_is_not_forgotten(monkeypatch):
    """Interrupting before the player starts has to still interrupt.

    stop() can only terminate a process that exists, and an edge voice spends a
    network round trip building the audio first. A tap in that window used to
    find nothing to stop, and then the reply you cut off played in full.
    """
    monkeypatch.setattr(speech.subprocess, "Popen", _FakePopen)
    _FakePopen.started = []
    channel = speech._Channel("test")
    channel.stop()
    channel._run_process(["/usr/bin/afplay", "/tmp/x.mp3"])
    assert _FakePopen.started == []


def test_the_next_reply_is_not_silenced_by_the_last_interruption(monkeypatch):
    monkeypatch.setattr(speech.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(speech, "_macos_voice", lambda _voice: "Samantha")
    _FakePopen.started = []
    channel = speech._Channel("test")
    channel.stop()
    from voiceisland import config

    config.save({"tts_engine": "say"})
    channel.run("the next answer")
    assert len(_FakePopen.started) == 1
