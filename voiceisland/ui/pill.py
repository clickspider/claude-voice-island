"""The pill itself: the view you hold to talk to.

State machine, in order:

    idle -> listening -> transcribing -> thinking -> speaking -> idle

`listening` is entered by pressing the pill or holding the push-to-talk key, and
left on release. `error` is reachable from anywhere and returns to idle on the
next attempt.

Threading. AppKit owns the main thread and everything that draws must run on it.
Transcription, the Claude run, and speech all take seconds, so they run on a
worker thread and hand results back with AppHelper.callAfter. Two things keep
that honest:

  * `generation` counts captures. Every worker carries the generation it was
    started for and stops the moment it no longer matches, which is what makes
    interrupting Claude mid-sentence to say something else work rather than
    produce two overlapping answers.
  * only the worker writes `heard` and `reply`, and only after checking its
    generation, so the drawing code always reads a consistent pair.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path

import objc
from AppKit import (
    NSAnimationContext,
    NSApp,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSEventMaskFlagsChanged,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSScreen,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
)
from Foundation import NSMakePoint, NSMakeRect, NSString
from PyObjCTools import AppHelper

from voiceisland import activity, claude, config, dialogs, sessions, speech
from voiceisland.audio import MicrophoneUnavailableError, Recorder, duration_seconds
from voiceisland.ui import menu, notch, symbols

try:
    from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
except ImportError:  # pragma: no cover - only on a stripped install
    AXIsProcessTrusted = None
    AXIsProcessTrustedWithOptions = None

_log = logging.getLogger("voiceisland.pill")

PTT_MODIFIERS = {
    "option": NSEventModifierFlagOption,
    "control": NSEventModifierFlagControl,
    "command": NSEventModifierFlagCommand,
}

SESSION_LIMIT = 25

# States that animate, and therefore hold the pill open.
ANIMATING = frozenset({"listening", "transcribing", "thinking", "speaking"})

_ACCENT = {
    "idle": (0.72, 0.72, 0.78),
    "listening": (0.98, 0.36, 0.42),
    "transcribing": (0.99, 0.78, 0.32),
    "thinking": (0.99, 0.78, 0.32),
    "speaking": (0.40, 0.88, 0.56),
    "error": (0.98, 0.36, 0.42),
}
_ICON = {
    "idle": "mic.fill",
    "listening": "mic.fill",
    "speaking": "waveform",
    "error": "exclamationmark.triangle.fill",
}

# Shorter than this and it was a stray click, not a sentence.
MIN_UTTERANCE_S = 0.35

# Hands-free mode watches the same loudness value the waveform draws. Speech
# pushes it past 0.16; a quiet room sits near zero. Once you have started
# talking, a gap of this long ends the sentence and sends it, which is what lets
# you keep both hands on what you were doing.
HANDSFREE_START_LEVEL = 0.16
HANDSFREE_STOP_LEVEL = 0.08
HANDSFREE_SILENCE_S = 1.3
HANDSFREE_WARMUP_S = 0.25    # ignore the moment the microphone stream spins up
HANDSFREE_MAX_UTTERANCE_S = 45.0

_FEED_LIMIT = 40  # activity rows kept in memory


class PillView(NSView):
    """The floating notch tab. Draws itself, records, and drives one voice turn."""

    def initWithFrame_(self, frame):  # noqa: N802
        self = objc.super(PillView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.state = "idle"
        self.status_text = ""
        self.heard = ""
        self.reply = ""
        self.recorder = Recorder()
        self.busy = False
        self.sessions = []
        self.current = None
        self.hovering = False
        self.phase = 0.0
        self.top_radius, self.bottom_radius = notch.RADII_CLOSED
        self.anim_timer = None
        self.proximity_timer = None
        self.ptt = "off"
        self.key_monitor = None
        self.local_key_monitor = None
        self._key_down = False
        self.generation = 0
        self.feed = []            # (icon, text, rgb, is_action)
        self.action_text = ""     # newest action, shown on the closed pill
        self.narrate = False
        self.handsfree = False
        self.permissions = "prompt"
        self.idle_width = notch.DEFAULT_NOTCH_WIDTH
        self.notch_height = 32.0
        self.panel = None
        self.notch_mode = True
        self.anchor_x = 756.0     # screen x of the pill's centre
        self.anchor_top = 900.0   # screen y of the pill's top edge
        self._dragging = False
        self._drag_origin = None
        self._drag_last = None
        self.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        return self

    def isFlipped(self):  # noqa: N802
        return True

    # ---- setup ------------------------------------------------------------
    @objc.python_method
    def load_settings(self):
        """Read settings and the chat list. Safe to call again to refresh."""
        settings = config.load()
        self.sessions = sessions.list_sessions(SESSION_LIMIT)
        saved = settings.get("session_id")
        self.current = next((s for s in self.sessions if s.id == saved), None) or (
            self.sessions[0] if self.sessions else None
        )
        self.status_text = self.current.name if self.current else "no chats"
        self.narrate = bool(settings.get("narrate", False))
        self.permissions = settings.get("permissions", "prompt")
        self.ptt = settings.get("ptt", "off")
        self._install_key_monitor()
        self.setNeedsDisplay_(True)

    @objc.python_method
    def attach(self, panel):
        self.panel = panel
        self.relayout()

    @objc.python_method
    def start_timers(self):
        """Poll the pointer to open, close, and hand over clicks.

        A tracking area would be the usual answer, but the window ignores mouse
        events while closed so it never blocks the app underneath. A window that
        does not receive events also does not receive mouse-entered, so the
        pointer is checked directly.
        """
        from AppKit import NSTimer

        self.proximity_timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.05, self, "proximityTick:", None, True
            )
        )

    def screensChanged_(self, _note):  # noqa: N802
        """A display was plugged in, unplugged, or rearranged."""
        self.relayout()

    @objc.python_method
    def relayout(self):
        """Place the window: merged into the notch, or floating on a screen without one."""
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        frame = screen.frame()
        height = notch.notch_height(screen)
        self.notch_mode = height > 0
        if self.notch_mode:
            self.notch_height = height
            self.idle_width = notch.measure_notch_width(screen)
            self.anchor_x = frame.origin.x + frame.size.width / 2.0
            self.anchor_top = frame.origin.y + frame.size.height
        else:
            self.notch_height = notch.FLOAT_HEIGHT
            self.idle_width = notch.FLOAT_CLOSED_WIDTH
            self.anchor_x, self.anchor_top = self._float_position(frame)
        self.hovering = False
        self._apply_size()
        self.setNeedsDisplay_(True)
        _log.info("layout: %s", "notch" if self.notch_mode else "floating")

    @objc.python_method
    def _float_position(self, frame):
        """Saved pill position, clamped so a screen change cannot strand it offscreen."""
        saved = config.load().get("float_pos")
        if saved and len(saved) == 2:
            x, top = float(saved[0]), float(saved[1])
        else:
            x = frame.origin.x + frame.size.width / 2.0
            top = frame.origin.y + frame.size.height - 10.0
        x = min(max(x, frame.origin.x + 40), frame.origin.x + frame.size.width - 40)
        top = min(max(top, frame.origin.y + 60), frame.origin.y + frame.size.height - 6)
        return x, top

    # ---- drawing ----------------------------------------------------------
    @objc.python_method
    def is_open(self) -> bool:
        return self.hovering or self.state in ANIMATING

    @objc.python_method
    def shows_feed(self) -> bool:
        """The activity card is for when you are looking at it, so: only on hover."""
        return bool(self.feed) and self.hovering

    def drawRect_(self, _rect):  # noqa: N802
        bounds = self.bounds()
        width = bounds.size.width
        NSColor.blackColor().set()
        if self.notch_mode:
            notch.notch_path(bounds, self.top_radius, self.bottom_radius).fill()
        else:
            radius = min(bounds.size.height / 2.0, 16.0)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, radius, radius
            ).fill()

        accent = _ACCENT.get(self.state, _ACCENT["idle"])
        if not self.is_open():
            if self.notch_mode:
                return  # closed on a notch screen means invisible, which is the point
            centre = bounds.size.height / 2.0
            self._draw_status_icon(20.0, centre, accent)
            symbols.draw("chevron.down", width - 18.0, centre, (0.62, 0.62, 0.66), 10.0)
            return

        centre_y = self.notch_height + notch.OPEN_HANG / 2
        icon_x = self.top_radius + 22.0
        self._draw_status_icon(icon_x, centre_y, accent)

        text_left = icon_x + 20.0
        text_right = width - 28.0
        if self.state == "listening":
            self._draw_waveform(text_left, text_right, centre_y, accent)
        else:
            label = self.header_text() if self.shows_feed() else self.pill_text()
            self._draw_text(label, text_left, text_right, centre_y, 12.5, 0.92)

        symbols.draw("chevron.down", width - 20.0, centre_y, (0.62, 0.62, 0.66), 11.0)

        if self.shows_feed():
            self._draw_feed(width)

    @objc.python_method
    def _draw_text(self, text, left, right, centre_y, size, brightness):
        attributes = {
            NSFontAttributeName: NSFont.systemFontOfSize_(size),
            NSForegroundColorAttributeName: NSColor.colorWithCalibratedWhite_alpha_(
                brightness, 1.0
            ),
        }
        string = NSString.stringWithString_(text)
        measured = string.sizeWithAttributes_(attributes)
        string.drawInRect_withAttributes_(
            NSMakeRect(
                left,
                centre_y - measured.height / 2,
                max(10.0, right - left),
                measured.height,
            ),
            attributes,
        )

    @objc.python_method
    def _draw_feed(self, width):
        top = self.notch_height + notch.OPEN_HANG
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.09).set()
        NSBezierPath.bezierPathWithRect_(NSMakeRect(16.0, top, width - 32.0, 1.0)).fill()
        rows = self.feed[-notch.FEED_MAX_ROWS:]
        y = top + 7.0
        for index, (icon, text, rgb, _is_action) in enumerate(rows):
            row_centre = y + notch.FEED_ROW_HEIGHT / 2.0
            if not symbols.draw(icon, 24.0, row_centre, rgb, 11.0):
                NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb, 1.0).set()
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(20.0, row_centre - 3.0, 6.0, 6.0)
                ).fill()
            newest = index == len(rows) - 1
            self._draw_text(
                _clip(text, 52), 40.0, width - 16.0, row_centre, 11.5,
                0.96 if newest else 0.78,
            )
            y += notch.FEED_ROW_HEIGHT

    @objc.python_method
    def _draw_status_icon(self, x, y, rgb):
        if self.state in ("thinking", "transcribing"):
            start = (self.phase * 150.0) % 360.0
            arc = NSBezierPath.bezierPath()
            arc.setLineWidth_(2.4)
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                NSMakePoint(x, y), 7.0, start, start + 260.0
            )
            NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb, 1.0).set()
            arc.stroke()
            return
        name = _ICON.get(self.state, "mic.fill")
        colour = rgb if self.state == "error" else (0.97, 0.97, 0.99)
        if not symbols.draw(name, x, y, colour, 15.0):
            NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb, 1.0).set()
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(x - 5, y - 5, 10, 10)
            ).fill()

    @objc.python_method
    def _draw_waveform(self, left, right, centre_y, rgb):
        """Six bars driven by live loudness, so you can see the microphone is live."""
        count, bar_width, gap, max_height = 6, 3.0, 5.0, 20.0
        amplitude = max(0.14, self.recorder.level)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb, 1.0).set()
        total = count * bar_width + (count - 1) * gap
        x = left + max(0.0, (right - left - total) / 2.0)
        for index in range(count):
            wave = 0.30 + 0.70 * abs(math.sin(self.phase * 1.2 + index * 0.7))
            height = 3.0 + max_height * amplitude * wave
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, centre_y - height / 2, bar_width, height),
                bar_width / 2, bar_width / 2,
            ).fill()
            x += bar_width + gap

    # ---- labels -----------------------------------------------------------
    @objc.python_method
    def pill_text(self) -> str:
        if self.state == "listening":
            return "Listening, hands-free" if self.handsfree else "Listening"
        if self.state == "transcribing":
            return f"You: {_clip(self.heard)}" if self.heard else "…"
        if self.state == "thinking":
            if self.action_text:
                return _clip(self.action_text, 42)
            return f"You: {_clip(self.heard)}" if self.heard else "Working"
        if self.state == "speaking":
            return _clip(self.reply, 52) if self.reply else "Speaking, tap to stop"
        if self.state == "error":
            return self.status_text or "Error"
        if not self.current:
            return "no chats · hold to talk"
        name = _clip(self.current.name, 24)
        if self.permissions == "auto":
            # Auto mode runs anything without asking, so it says so on the pill
            # rather than only in a menu you are not looking at.
            return f"{name} · auto, no prompts"
        if self.handsfree:
            return f"{name} · hands-free (tap to stop)"
        return f"{name} · hold to talk"

    @objc.python_method
    def header_text(self) -> str:
        name = _clip(self.current.name, 22) if self.current else "chat"
        phase = {
            "transcribing": "transcribing",
            "thinking": "working",
            "speaking": "speaking",
        }.get(self.state, "")
        return f"{name} · {phase}" if phase else name

    # ---- mouse ------------------------------------------------------------
    def acceptsFirstMouse_(self, _event):  # noqa: N802
        return True

    def mouseDown_(self, event):  # noqa: N802
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        if point.x >= self.bounds().size.width - 30:
            self._show_menu()
            return
        if self.handsfree:
            self._handsfree_stop()
            return
        self._dragging = False
        self._drag_origin = NSEvent.mouseLocation()
        self._drag_last = self._drag_origin
        if self.state == "speaking":
            self._interrupt()
            return
        self._begin_listen()

    def mouseDragged_(self, _event):  # noqa: N802
        if self.notch_mode or self._drag_origin is None:
            return  # the notch shape is fixed in place; only the floating pill moves
        location = NSEvent.mouseLocation()
        if not self._dragging:
            dx = location.x - self._drag_origin.x
            dy = location.y - self._drag_origin.y
            if dx * dx + dy * dy <= 36.0:
                return  # under six pixels is still a hold, not a drag
            self._dragging = True
            if self.state == "listening":
                self._cancel_listen()
        self.anchor_x += location.x - self._drag_last.x
        self.anchor_top += location.y - self._drag_last.y
        self._drag_last = location
        frame = self.panel.frame()
        self.panel.setFrameOrigin_(
            NSMakePoint(
                self.anchor_x - frame.size.width / 2.0,
                self.anchor_top - frame.size.height,
            )
        )

    def mouseUp_(self, _event):  # noqa: N802
        if self._dragging:
            self._dragging = False
            config.save({"float_pos": [self.anchor_x, self.anchor_top]})
            return
        self._end_listen()

    def proximityTick_(self, _timer):  # noqa: N802
        if self.panel is None or self._dragging:
            return
        location = NSEvent.mouseLocation()
        frame = self.panel.frame()
        margin = 12.0
        inside = (
            frame.origin.x - margin <= location.x <= frame.origin.x + frame.size.width + margin
            and frame.origin.y - margin <= location.y <= frame.origin.y + frame.size.height + margin
        )
        # Take mouse events only when the pointer is near or a turn is running.
        # The rest of the time the window is transparent to clicks, so whatever is
        # behind it keeps working normally.
        wants_events = inside or self.busy or self.state in ANIMATING
        if self.panel.ignoresMouseEvents() == wants_events:
            self.panel.setIgnoresMouseEvents_(not wants_events)
        if inside != self.hovering:
            self.hovering = inside
            self._apply_size()
            self.setNeedsDisplay_(True)

    # ---- recording --------------------------------------------------------
    @objc.python_method
    def _begin_listen(self):
        if self.state == "speaking":
            self._interrupt()
        if self.busy or self.current is None or self.state == "listening":
            return
        self.generation += 1
        self.heard = ""
        self.reply = ""
        self.feed = []
        self.action_text = ""
        self._set_state("listening", "")
        try:
            self.recorder.start()
        except MicrophoneUnavailableError:
            _log.exception("microphone unavailable")
            self._set_state("error", "allow microphone access")

    @objc.python_method
    def _end_listen(self):
        if self.state != "listening":
            return
        try:
            audio = self.recorder.stop()
        except Exception:  # noqa: BLE001
            # Whatever went wrong in the audio layer, the pill has to end up in a
            # state you can press again.
            _log.exception("stopping the recorder failed")
            self._set_state("error", "microphone error")
            return
        if duration_seconds(audio) < MIN_UTTERANCE_S:
            self._set_state("idle", "")
            if self.handsfree:
                self._handsfree_listen()  # too short to send, so keep the loop alive
            return
        self.busy = True
        self._set_state("transcribing", "…")
        threading.Thread(
            target=self._run_turn, args=(audio, self.generation),
            name="voice-turn", daemon=True,
        ).start()

    @objc.python_method
    def _cancel_listen(self):
        try:
            self.recorder.stop()
        except Exception:  # noqa: BLE001
            # This recording is being thrown away anyway.
            _log.exception("cancelling the recording failed")
        self.busy = False
        self._set_state("idle", "")

    @objc.python_method
    def _interrupt(self):
        """Cut Claude off mid-sentence."""
        speech.stop_speaking()
        self.busy = False
        self._set_state("idle", "")

    # ---- one voice turn ---------------------------------------------------
    @objc.python_method
    def _run_turn(self, audio, generation):
        """Worker thread: transcribe, ask Claude, speak the reply."""
        try:
            text = speech.transcribe(audio)
            if not text:
                AppHelper.callAfter(self._apply, generation, "idle", "didn't catch that", False)
                AppHelper.callAfter(self._handsfree_rearm, generation)
                return
            if generation != self.generation:
                return
            self.heard = text
            _log.info("heard %d characters", len(text))
            _log_transcript("heard", text)
            AppHelper.callAfter(
                self._push_row, generation, "person.wave.2", f"You: {text}",
                (0.90, 0.90, 0.96), False,
            )
            AppHelper.callAfter(self._apply, generation, "thinking", "", None)

            reply = claude.ask(
                self.current.id, self.current.cwd, text, self._stream_listener(generation)
            )
            if generation != self.generation:
                return
            if reply.session_id and self.current and reply.session_id != self.current.id:
                # A new chat only gets its id once it exists, so this is where a
                # "New chat" becomes a chat that can be resumed.
                self.current.id = reply.session_id
                config.save({"session_id": reply.session_id})
            self.reply = reply.text
            _log.info("replied %d characters in %d events", len(reply.text), reply.events)
            _log_transcript("reply", reply.text)
            AppHelper.callAfter(
                self._push_row, generation, "waveform", f"Claude: {reply.text}",
                (0.45, 0.85, 0.60), False,
            )
            AppHelper.callAfter(self._apply, generation, "speaking", "", None)
            speech.speak(reply.text)
            AppHelper.callAfter(self._apply, generation, "idle", "", False)
            AppHelper.callAfter(self._handsfree_rearm, generation)
        except Exception:  # noqa: BLE001
            # Last line of defence for the worker thread. Anything uncaught here
            # would leave the pill stuck mid-turn with no way back.
            _log.exception("voice turn failed")
            AppHelper.callAfter(self._apply, generation, "error", "something went wrong", False)
            AppHelper.callAfter(self._handsfree_rearm, generation)

    @objc.python_method
    def _stream_listener(self, generation):
        """Build the callback that turns stream events into activity rows."""
        def listener(kind, data):
            if kind == "assistant_text":
                AppHelper.callAfter(
                    self._push_row, generation, "text.bubble",
                    " ".join(str(data).split()), (0.66, 0.66, 0.74), True,
                )
            elif kind == "tool":
                name = data.get("name", "")
                icon, phrase = activity.describe(name, data.get("input", {}))
                AppHelper.callAfter(
                    self._push_row, generation, icon, phrase, (0.45, 0.72, 1.0), True
                )
                if self.narrate:
                    speech.narrate(activity.spoken(name))
            elif kind == "tool_result":
                failed = bool(data.get("is_error"))
                AppHelper.callAfter(
                    self._push_row, generation,
                    "xmark.circle" if failed else "checkmark.circle",
                    "Failed" if failed else "Done",
                    (0.98, 0.40, 0.42) if failed else (0.45, 0.80, 0.55),
                    False,
                )
        return listener

    @objc.python_method
    def _push_row(self, generation, icon, text, rgb, is_action):
        """Main thread: add one activity row. Action rows also update the pill."""
        if generation != self.generation:
            return
        self.feed.append((icon, text, rgb, is_action))
        if len(self.feed) > _FEED_LIMIT:
            del self.feed[:-_FEED_LIMIT]
        if is_action and text:
            self.action_text = text
        self._apply_size()
        self.setNeedsDisplay_(True)

    @objc.python_method
    def _apply(self, generation, state, text, busy=None):
        """Main thread: a state change from a worker, ignored once superseded."""
        if generation != self.generation:
            return
        if busy is not None:
            self.busy = busy
        self._set_state(state, text)

    @objc.python_method
    def _set_state(self, state, text):
        self.state = state
        self.status_text = text
        if state in ANIMATING:
            self._start_animation()
        else:
            self._stop_animation()
        self._apply_size()
        self.setNeedsDisplay_(True)

    # ---- hands-free -------------------------------------------------------
    @objc.python_method
    def _handsfree_start(self):
        if self.current is None:
            self._set_state("error", "no chat selected")
            return
        self.handsfree = True
        self._handsfree_listen()

    @objc.python_method
    def _handsfree_stop(self):
        self.handsfree = False
        if self.state == "speaking":
            speech.stop_speaking()
        elif self.state == "listening":
            try:
                self.recorder.stop()
            except Exception:  # noqa: BLE001
                # Stopping the loop must succeed even if the microphone does not.
                _log.exception("stopping hands-free recording failed")
        self.busy = False
        self._set_state("idle", "")

    @objc.python_method
    def _handsfree_listen(self):
        """Open the microphone for one hands-free turn and watch for the gap."""
        if not self.handsfree or self.busy or self.current is None:
            return
        if self.state == "speaking":
            return  # listening while it talks would record its own voice
        self._begin_listen()
        if self.state != "listening":
            self.handsfree = False
            return
        threading.Thread(
            target=self._handsfree_watch, args=(self.generation,),
            name="handsfree-vad", daemon=True,
        ).start()

    @objc.python_method
    def _handsfree_rearm(self, generation):
        if self.handsfree and generation == self.generation and not self.busy:
            self._handsfree_listen()

    @objc.python_method
    def _handsfree_watch(self, generation):
        """Worker thread: end the utterance after a gap, or at the hard limit."""
        started_at = time.monotonic()
        speaking = False
        silence_began = None
        while True:
            time.sleep(0.05)
            if (generation != self.generation or not self.handsfree
                    or self.state != "listening"):
                return
            now = time.monotonic()
            if now - started_at < HANDSFREE_WARMUP_S:
                continue
            level = self.recorder.level
            if level >= HANDSFREE_START_LEVEL:
                speaking = True
                silence_began = None
            elif speaking and level < HANDSFREE_STOP_LEVEL:
                if silence_began is None:
                    silence_began = now
                elif now - silence_began >= HANDSFREE_SILENCE_S:
                    AppHelper.callAfter(self._handsfree_end, generation)
                    return
            if now - started_at >= HANDSFREE_MAX_UTTERANCE_S:
                AppHelper.callAfter(self._handsfree_end, generation)
                return

    @objc.python_method
    def _handsfree_end(self, generation):
        if generation == self.generation and self.state == "listening":
            self._end_listen()

    # ---- push-to-talk key -------------------------------------------------
    @objc.python_method
    def _install_key_monitor(self):
        """Watch a modifier key globally, so you can talk without leaving your app."""
        for monitor in (self.key_monitor, self.local_key_monitor):
            if monitor is not None:
                NSEvent.removeMonitor_(monitor)
        self.key_monitor = self.local_key_monitor = None
        self._key_down = False
        flag = PTT_MODIFIERS.get(self.ptt)
        if flag is None:
            return
        self._request_accessibility()

        def handler(event):
            down = bool(event.modifierFlags() & flag)
            if down and not self._key_down:
                self._key_down = True
                self._begin_listen()
            elif not down and self._key_down:
                self._key_down = False
                self._end_listen()
            return event

        # Global sees the key while another app is focused; local sees it while
        # this app is. Both are needed to cover every case.
        self.key_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, lambda event: handler(event)
        )
        self.local_key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, handler
        )
        _log.info("push-to-talk key: %s", self.ptt)

    @objc.python_method
    def _request_accessibility(self) -> bool:
        """Watching keys outside this app needs Accessibility permission."""
        if AXIsProcessTrusted is None:
            return False
        if AXIsProcessTrusted():
            return True
        if AXIsProcessTrustedWithOptions is not None:
            try:
                AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
            except Exception:  # noqa: BLE001
                # Without the permission the key shortcut is simply unavailable,
                # which is not worth taking the app down for.
                _log.exception("could not ask for accessibility permission")
        return False

    # ---- window sizing ----------------------------------------------------
    @objc.python_method
    def _apply_size(self):
        if self.panel is None:
            return
        if self.shows_feed():
            rows = min(len(self.feed), notch.FEED_MAX_ROWS)
            width = notch.FEED_WIDTH
            height = self.notch_height + notch.OPEN_HANG + rows * notch.FEED_ROW_HEIGHT + 12.0
            self.top_radius, self.bottom_radius = notch.RADII_OPEN
        elif self.is_open():
            width = notch.OPEN_WIDTH
            height = self.notch_height + notch.OPEN_HANG
            self.top_radius, self.bottom_radius = notch.RADII_OPEN
        else:
            width, height = self.idle_width, self.notch_height
            self.top_radius, self.bottom_radius = notch.RADII_CLOSED
        x = self.anchor_x - width / 2.0
        y = self.anchor_top - height
        current = self.panel.frame()
        # Every activity row would otherwise restart the resize animation, which
        # looks like the window shivering.
        unchanged = (
            abs(current.origin.x - x) < 0.5 and abs(current.origin.y - y) < 0.5
            and abs(current.size.width - width) < 0.5
            and abs(current.size.height - height) < 0.5
        )
        if unchanged:
            return
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.22)
        self.panel.animator().setFrame_display_(NSMakeRect(x, y, width, height), True)
        NSAnimationContext.endGrouping()

    @objc.python_method
    def _start_animation(self):
        from AppKit import NSTimer

        if self.anim_timer is not None:
            return
        self.anim_timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / 30.0, self, "animationTick:", None, True
            )
        )

    @objc.python_method
    def _stop_animation(self):
        if self.anim_timer is not None:
            self.anim_timer.invalidate()
            self.anim_timer = None
        self.phase = 0.0

    def animationTick_(self, _timer):  # noqa: N802
        self.phase += 0.12
        self.setNeedsDisplay_(True)

    # ---- menu actions -----------------------------------------------------
    @objc.python_method
    def _show_menu(self):
        menu.build(self).popUpMenuPositioningItem_atLocation_inView_(
            None, NSMakePoint(0.0, self.notch_height + notch.OPEN_HANG + 2.0), self
        )

    def setPTT_(self, sender):  # noqa: N802
        self.ptt = sender.representedObject()
        config.save({"ptt": self.ptt})
        self._install_key_monitor()

    def setVoice_(self, sender):  # noqa: N802
        config.save({"voice": sender.representedObject()})

    def setEngine_(self, sender):  # noqa: N802
        config.save({"tts_engine": sender.representedObject()})

    def setPermissions_(self, sender):  # noqa: N802
        """Change what a spoken sentence is allowed to do.

        Turning off every prompt is the one setting here that can cost you
        something, so it is confirmed on screen before it takes effect.
        """
        choice = sender.representedObject()
        if choice == "auto" and not _confirm_auto_mode():
            return
        self.permissions = choice
        config.save({"permissions": choice})
        _log.warning("tool permissions set to %s", choice)
        self.setNeedsDisplay_(True)

    def resetPosition_(self, _sender):  # noqa: N802
        config.save({"float_pos": None})
        self.relayout()

    def toggleNarrate_(self, _sender):  # noqa: N802
        self.narrate = not self.narrate
        if not self.narrate:
            speech.stop_narration()
        config.save({"narrate": self.narrate})

    def toggleHandsFree_(self, _sender):  # noqa: N802
        if self.handsfree:
            self._handsfree_stop()
        else:
            self._handsfree_start()

    def toggleLogin_(self, _sender):  # noqa: N802
        from voiceisland import launchagent

        enabled = launchagent.set_enabled(not launchagent.is_enabled())
        config.save({"launch_at_login": enabled})

    def newChat_(self, _sender):  # noqa: N802
        """Start a fresh chat. Its id arrives with the first reply."""
        self.current = sessions.Session(
            id="", cwd=str(Path.home()), project="", title="New chat", mtime=0.0
        )
        self.heard = ""
        self.reply = ""
        self._set_state("idle", "")

    def selectSession_(self, sender):  # noqa: N802
        chosen = sender.representedObject()
        self.current = next((s for s in self.sessions if s.id == chosen), self.current)
        if self.current:
            config.save({"session_id": self.current.id})
            self._set_state("idle", "")

    def refresh_(self, _sender):
        self.load_settings()

    def quitApp_(self, _sender):  # noqa: N802
        speech.stop_speaking()
        self.recorder.close()
        NSApp().terminate_(None)


def _confirm_auto_mode() -> bool:
    return dialogs.ask_yes_no(
        title="Claude Voice Island: turn off all prompts?",
        body=(
            "In auto mode, anything you say can run commands, edit files, and "
            "reach the network without asking you first.\n\n"
            "Only use it in a directory where that is fine."
        ),
        allow_label="Turn off prompts",
        deny_label="Keep asking me",
        timeout_s=60,
    )


def _clip(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _log_transcript(kind: str, text: str) -> None:
    """Write what was said only when the setting asks for it.

    The log otherwise records lengths and timings. Everything you say to this
    thing would otherwise sit in a file in plain text forever, which is not a
    default anyone chose.
    """
    if config.load().get("log_transcripts"):
        _log.info("%s: %s", kind, text)
