"""Voice Activity Detection (architecture §1, §2).

Two modes, selected by ``mode``:

- ``energy`` : pure-Python RMS with an adaptive threshold. Robust and
  dependency-free; tuned for a laptop internal microphone.
- ``webrtc`` : wraps the WebRTC VAD (``webrtcvad-wheels``) when installed,
  frame-based and very fast.

The state machine (idle -> maybe_in -> in_speech -> maybe_out) is driven
here; the caller uses ``feed()`` and reads ``is_speech`` each chunk.
"""
from __future__ import annotations

import math


def _energy(frame: bytes) -> float:
    """Mean square of the s16le samples (0..32768^2)."""
    n = len(frame) // 2
    if n == 0:
        return 0.0
    total = 0.0
    for i in range(n):
        sample = int.from_bytes(frame[i * 2:i * 2 + 2],
                                "little", signed=True)
        total += sample * sample
    return total / n


class EnergyVAD:
    """Adaptive-threshold energy VAD with hysteresis.

    Parameters
    ----------
    frame_ms   : chunk duration fed to `feed`
    threshold  : starting speech threshold (RMS squared)
    adapt_rate : how fast the noise floor follows non-speech regions
    """

    def __init__(self, frame_ms: int = 20, threshold: float = 180.0,
                 adapt_rate: float = 0.05, hangover_ms: int = 240):
        self.frame_ms = frame_ms
        self.threshold = threshold
        self.adapt_rate = adapt_rate
        self.hangover_frames = max(1, (hangover_ms + frame_ms - 1) // frame_ms)
        self._silence_frames = 0
        self.noise_floor = threshold
        self.active = False

    def feed(self, frame: bytes) -> bool:
        e = _energy(frame)
        if self.active:
            if e > self.threshold:
                self._silence_frames = 0
                return True
            self._silence_frames += 1
            if self._silence_frames < self.hangover_frames:
                return True
            self.active = False
            self._silence_frames = 0
        if e < self.noise_floor:
            self.noise_floor = self.noise_floor * (1 - self.adapt_rate) + \
                e * self.adapt_rate
        self.active = e > self.threshold
        if self.active:
            self._silence_frames = 0
        return self.active

    def reset(self) -> None:
        self.active = False
        self._silence_frames = 0


class WebRTCVAD:
    """Optional WebRTC VAD (needs webrtcvad-wheels installed)."""

    def __init__(self, mode: int = 1):
        import webrtcvad  # lazy import keeps E.V. usable without it
        self._vad = webrtcvad.Vad(mode)
        self.active = False

    def feed(self, frame: bytes) -> bool:
        # WebRTC expects exactly 10/20/30 ms frames at 16 kHz mono
        self.active = bool(self._vad.is_speech(frame, 16000))
        return self.active

    def reset(self) -> None:
        self.active = False


class VAD:
    """Unified VAD façade that auto-falls-back between modes."""

    def __init__(self, mode: str = "energy", frame_ms: int = 20,
                 threshold: float = 180.0):
        self.mode = mode
        self.frame_ms = frame_ms
        self._impl = EnergyVAD(frame_ms=frame_ms, threshold=threshold)
        if mode == "webrtc":
            try:
                self._impl = WebRTCVAD()
            except ImportError:
                self.mode = "energy"

    @property
    def is_speech(self) -> bool:
        return self._impl.active

    def feed(self, frame: bytes) -> bool:
        return self._impl.feed(frame)

    def reset(self) -> None:
        self._impl.reset()


def has_speech(data: bytes, threshold: float = 300.0) -> bool:
    """Convenience one-shot check (used by tests / mic pre-check)."""
    return _energy(data) > threshold
