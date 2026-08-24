"""Microphone capture.

Records mono float32 at 16 kHz, which is what the speech model wants, so nothing
has to be resampled later.

The lock matters more than it looks. Push-to-talk means a stream can be asked to
open while the previous one is still closing, and PortAudio runs its callback on
its own IO thread. Dropping a stream out from under that thread crashes the
process rather than raising, so every open is preceded by a fully completed
close.
"""

from __future__ import annotations

import logging
import threading

import numpy as np

from voiceisland.speech import SAMPLE_RATE

_log = logging.getLogger("voiceisland.audio")


class MicrophoneUnavailableError(RuntimeError):
    """The microphone could not be opened: no device, or permission refused."""


class Recorder:
    """Captures audio while the button is held.

    `level` is a smoothed loudness between 0 and 1, read by the UI to draw the
    waveform and by the hands-free loop to notice when you stopped talking.
    """

    def __init__(self) -> None:
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self.level = 0.0

    def start(self) -> None:
        """Open the microphone and begin filling the buffer."""
        import sounddevice

        with self._lock:
            self._close_locked()
            self._frames = []
            self.level = 0.0
            try:
                self._stream = sounddevice.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    callback=self._on_audio,
                )
                self._stream.start()
            except Exception as exc:
                self._stream = None
                raise MicrophoneUnavailableError(str(exc)) from exc

    def _on_audio(self, indata, _frames, _time_info, _status) -> None:
        """PortAudio IO thread. Keep it short and allocation-light."""
        self._frames.append(indata.copy())
        rms = float(np.sqrt(np.mean(np.square(indata))))
        # Smoothed so the waveform moves like a voice rather than like a meter,
        # and scaled because speech RMS sits around 0.03 to 0.1.
        self.level = 0.55 * self.level + 0.45 * min(1.0, rms * 9.0)

    def stop(self) -> np.ndarray:
        """Close the microphone and return everything recorded, as one array."""
        with self._lock:
            self._close_locked()
            frames, self._frames = self._frames, []
        if not frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(frames, axis=0).flatten()

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.stop()  # returns only once the callback has finished
            self._stream.close()
        except Exception:  # noqa: BLE001
            # PortAudio raises several unrelated types here, and a stream that
            # will not close cleanly still has to be let go of.
            _log.exception("closing the audio stream failed")
        finally:
            self._stream = None


def duration_seconds(audio: np.ndarray) -> float:
    """How long a recording is, in seconds."""
    return len(audio) / float(SAMPLE_RATE)
