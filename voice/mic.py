"""Microphone capture — records 16 kHz mono s16le audio.

Primary backend is ``arecord`` (ALSA, almost always present on Ubuntu).
The shared format for the whole voice pipeline is:
    rate = 16000, channels = 1, sample_width = 2 bytes (s16le)
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

RATE = 16000
CHANNELS = 1
WIDTH = 2                     # s16le = 2 bytes per sample
SECOND_BYTES = RATE * CHANNELS * WIDTH   # bytes for 1 second


def arecord_available() -> bool:
    return shutil.which("arecord") is not None


def record_wav(seconds: int, out_path: str,
               device: str | None = None) -> Path:
    """Record *seconds* seconds to a WAV file with arecord.

    Returns the created path. Raises CalledProcessError on failure.
    """
    out = Path(out_path)
    if out.suffix.lower() != ".wav":
        out = out.with_suffix(".wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE),
           "-c", str(CHANNELS), "-d", str(max(1, int(seconds)))]
    if device:
        cmd += ["-D", device]
    cmd.append(str(out))
    subprocess.run(cmd, check=True, capture_output=True)
    return out


class MicStream:
    """Background thread that yields audio frames (s16le, 16 kHz mono).

    Callers subscribe with ``on_frame(cb)``; each callback receives a fixed
    20 ms (configurable) frame. Call ``start()`` then ``stop()``.
    """

    def __init__(self, frame_ms: int = 20, device: str | None = None):
        self.frame_ms = frame_ms
        self.device = device
        self._running = False
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._callbacks: list = []

    def on_frame(self, cb) -> None:
        """Register a callback ``cb(bytes)`` invoked per audio frame."""
        self._callbacks.append(cb)

    def start(self) -> None:
        if self._running:
            return
        if not arecord_available():
            raise RuntimeError("arecord not found; cannot capture audio")
        cmd = ["arecord", "-q", "-t", "raw", "-f", "S16_LE",
               "-r", str(RATE), "-c", str(CHANNELS)]
        if self.device:
            cmd += ["-D", self.device]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        want = max(1, (RATE * WIDTH * self.frame_ms) // 1000)
        frame = bytearray()
        assert self._proc and self._proc.stdout
        try:
            while self._running:
                chunk = self._proc.stdout.read(want - len(frame))
                if not chunk:
                    break
                frame.extend(chunk)
                while len(frame) >= want:
                    payload = bytes(frame[:want])
                    del frame[:want]
                    for cb in self._callbacks:
                        cb(payload)
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        proc, thread = self._proc, self._thread
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    pass
            except OSError:
                pass
        if proc and proc.stdout:
            try:
                proc.stdout.close()
            except OSError:
                pass
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._proc = None
        self._thread = None