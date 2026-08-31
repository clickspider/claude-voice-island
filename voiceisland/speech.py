"""Speech in, speech out.

In: faster-whisper, running on the CPU of this Mac. The recording never leaves
the machine. The model file itself is downloaded once, on first use.

Out: two engines, chosen in Settings.
    edge  Microsoft's neural voices. Clearly the better voice, and it works by
          sending the reply text to Microsoft's speech endpoint.
    say   the macOS speech synthesiser. Nothing leaves the Mac, and it sounds
          like the macOS speech synthesiser.

Playback runs as a child process so it can be cut off mid-sentence. Speaking to
someone who cannot be interrupted is not a conversation.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from voiceisland import config

_log = logging.getLogger("voiceisland.speech")

SAMPLE_RATE = 16_000

# The voices offered in the menu: (label, edge voice id, closest macOS voice).
# Both engines are listed together so switching engine keeps the voice you chose
# roughly where you left it instead of resetting to a default.
VOICE_CHOICES = [
    ("Andrew (US, warm)", "en-US-AndrewNeural", "Tom"),
    ("Brian (US, casual)", "en-US-BrianNeural", "Alex"),
    ("Ava (US, female)", "en-US-AvaNeural", "Samantha"),
    ("Emma (US, female)", "en-US-EmmaNeural", "Karen"),
    ("Ryan (UK, male)", "en-GB-RyanNeural", "Daniel"),
]
_FALLBACK_MACOS_VOICE = "Samantha"

# Absolute paths: these are fixed parts of macOS, and resolving them through
# PATH would let a directory earlier in PATH answer instead.
AFPLAY = "/usr/bin/afplay"
SAY = "/usr/bin/say"

# Long replies are for reading, not listening. Past this the speech is cut and
# the pill still shows the full text.
_SPOKEN_LIMIT = 700

_model = None
_model_lock = threading.Lock()


def _load_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            name = config.load().get("whisper_model", "base.en")
            _log.info("loading whisper model %s", name)
            _model = WhisperModel(name, device="cpu", compute_type="int8")
        return _model


def transcribe(audio) -> str:
    """Turn a float32 mono 16 kHz numpy array into text."""
    segments, _info = _load_model().transcribe(audio, language="en", vad_filter=True)
    return " ".join(segment.text for segment in segments).strip()


def for_speech(text: str) -> str:
    """Strip anything a speech engine would read as punctuation soup.

    Claude is already asked for plain prose in the prompt. This is the second
    line of defence for when it answers with a code block anyway.
    """
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # [label](url) keeps the label
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)   # bullet markers
    text = re.sub(r"[#>*_~|`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_SPOKEN_LIMIT]


class _Channel:
    """One interruptible stream of speech.

    Two exist: the reply Claude gives you, and the short phrases announcing what
    it is doing. They stop independently, so cutting off narration does not cut
    off the answer you actually asked for.
    """

    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        # Raised by stop(), lowered by the next run(). Stopping can only
        # terminate a player that already exists, and with the edge voices the
        # audio takes a network round trip first, so for most of a second every
        # reply is un-interruptible unless the stop is remembered.
        self._stopped = False

    def run(self, text: str) -> None:
        """Speak `text` and block until it finishes or is stopped."""
        text = for_speech(text)
        if not text:
            return
        with self._lock:
            self._stopped = False
        settings = config.load()
        engine = settings.get("tts_engine", "edge")
        voice = settings.get("voice", "en-US-AndrewNeural")
        try:
            if engine == "say":
                self._run_process([SAY, "-v", _macos_voice(voice), "--", text])
            else:
                self._speak_edge(text, voice)
        except Exception:  # noqa: BLE001
            # Losing the voice should never lose the turn. The text is on screen.
            _log.exception("%s: speech failed", self.name)

    def _speak_edge(self, text: str, voice: str) -> None:
        import edge_tts

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            path = handle.name
        try:
            asyncio.run(edge_tts.Communicate(text, voice).save(path))
            self._run_process([AFPLAY, path])
        finally:
            Path(path).unlink(missing_ok=True)

    def _run_process(self, command: list[str]) -> None:
        with self._lock:
            if self._stopped:
                # You already cut this off while it was being synthesised.
                # Playing it now would read out an answer you interrupted.
                return
            self._process = subprocess.Popen(command)
            process = self._process
        try:
            process.wait()
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                _log.debug("%s: nothing to terminate", self.name, exc_info=True)


_reply = _Channel("reply")
_narration = _Channel("narration")

_narration_queue: queue.Queue[str] = queue.Queue()
_narration_worker: threading.Thread | None = None
_narration_lock = threading.Lock()


def _macos_voice(voice: str) -> str:
    """The macOS voice standing in for an edge voice id."""
    for _label, edge_id, macos_name in VOICE_CHOICES:
        if edge_id == voice:
            return macos_name
    return _FALLBACK_MACOS_VOICE


def speak(text: str) -> None:
    """Speak Claude's reply. Blocks until done, cut short by stop_speaking()."""
    stop_narration()  # never let a "running a command" phrase trail into the answer
    _reply.run(text)


def stop_speaking() -> None:
    """Cut off whatever is being spoken right now, including queued narration."""
    stop_narration()
    _reply.stop()


def narrate(text: str) -> None:
    """Say a short phrase about what Claude is doing, without blocking the caller.

    Phrases are dropped once two are already waiting. Narration that lags behind
    the work it describes is worse than no narration.
    """
    global _narration_worker
    with _narration_lock:
        if _narration_worker is None:
            _narration_worker = threading.Thread(
                target=_narration_loop, name="narration", daemon=True
            )
            _narration_worker.start()
    if _narration_queue.qsize() < 2:
        _narration_queue.put(text)


def stop_narration() -> None:
    """Drop everything queued and silence the phrase playing now."""
    while True:
        try:
            _narration_queue.get_nowait()
        except queue.Empty:
            break
    _narration.stop()


def _narration_loop() -> None:
    while True:
        _narration.run(_narration_queue.get())
