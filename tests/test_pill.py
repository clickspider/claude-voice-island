"""The pill's state machine, without a window.

Everything interesting on the view is an `objc.python_method`, which is a plain
function on the class, so it can be called against a stand-in object. That keeps
these tests away from AppKit's drawing and window code while still exercising the
part that decides whether a turn still counts.
"""

from __future__ import annotations

import types

import pytest

pytest.importorskip("AppKit")

from voiceisland import speech
from voiceisland.ui.pill import PillView


def view(**overrides):
    """A stand-in with only what the method under test touches."""
    states: list[tuple[str, str]] = []
    stub = types.SimpleNamespace(
        handsfree=True,
        generation=7,
        state="thinking",
        busy=True,
        states=states,
        recorder=types.SimpleNamespace(stop=lambda: None),
    )
    stub._set_state = lambda state, text: states.append((state, text))
    for key, value in overrides.items():
        setattr(stub, key, value)
    return stub


def test_stopping_hands_free_abandons_the_turn_that_is_still_running(monkeypatch):
    """Stopping while Claude is thinking must not speak the answer later.

    The worker checks its generation once the run comes back and returns if it no
    longer matches. Stopping used to leave the generation alone, so the check
    passed, and the reply to a question you had already abandoned arrived a
    minute later and read itself out loud.
    """
    monkeypatch.setattr(speech, "stop_speaking", lambda: None)
    stub = view(state="thinking")
    PillView.__dict__["_handsfree_stop"](stub)
    assert stub.generation == 8       # the running turn no longer matches
    assert stub.handsfree is False
    assert stub.busy is False
    assert stub.states[-1] == ("idle", "")


def test_stopping_hands_free_silences_whatever_is_talking(monkeypatch):
    stopped = []
    monkeypatch.setattr(speech, "stop_speaking", lambda: stopped.append(True))
    PillView.__dict__["_handsfree_stop"](view(state="speaking"))
    assert stopped == [True]


def test_stopping_hands_free_closes_the_microphone(monkeypatch):
    monkeypatch.setattr(speech, "stop_speaking", lambda: None)
    closed = []
    stub = view(state="listening",
                recorder=types.SimpleNamespace(stop=lambda: closed.append(True)))
    PillView.__dict__["_handsfree_stop"](stub)
    assert closed == [True]


def test_a_microphone_that_will_not_close_does_not_block_stopping(monkeypatch):
    """Stopping the loop has to succeed even when the audio layer will not."""
    monkeypatch.setattr(speech, "stop_speaking", lambda: None)

    def explode():
        raise RuntimeError("portaudio is unhappy")

    stub = view(state="listening", recorder=types.SimpleNamespace(stop=explode))
    PillView.__dict__["_handsfree_stop"](stub)
    assert stub.handsfree is False
    assert stub.states[-1] == ("idle", "")
