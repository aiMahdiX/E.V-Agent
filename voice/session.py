"""Voice session — utterance capture + the hands-free loop (architecture §1, §2).

Workflow:
    Idle -> Listening (after wake) -> STT -> Agent -> TTS -> Idle

``capture_utterance`` gathers a short clip of speech from the mic and
transcribes it. ``VoiceLoop`` drives the whole experience using the shared
wake-word + STT + TTS + Agent pipeline.
"""
from __future__ import annotations

import time
import threading

from voice import mic
from voice.vad import VAD
from voice.wakeword import WakeWord
from voice.stt import VoskSTT
from voice.tts import VoiceTTS


class VoiceLoop:
    """Hands-free session:

        Wake-word -> capture utterance -> STT -> agent.run -> TTS reply

    `agent` is any object with ``run(text) -> str`` (the E.V. Agent).
    `on_status` is an optional ``(msg) -> None`` callback for UI/logging.
    """

    def __init__(self, agent, stt: VoskSTT | None = None,
                 tts: VoiceTTS | None = None,
                 wake: WakeWord | None = None,
                 on_status=None):
        self.agent = agent
        self.stt = stt or VoskSTT()
        self.tts = tts or VoiceTTS()
        self.wake = wake or WakeWord(stt=self.stt, vad=VAD(frame_ms=20))
        self.on_status = on_status or (lambda m: print(f"[voice] {m}"))
        self.running = False
        self._stop_event = threading.Event()

    def _say(self, text: str) -> None:
        if text:
            try:
                self.tts.speak(text, block=False)
            except Exception as exc:  # noqa: BLE001 — speech failure must not stop text agent
                self.on_status(f"voice output unavailable: {exc}")

    # ------------------------------------------------------------------ #
    def run(self, wake_timeout: float = 120.0) -> None:
        self.running = True
        self._stop_event.clear()
        self.on_status("listening for wake word…")
        while self.running and not self._stop_event.is_set():
            try:
                woke = self.wake.wait_for_wake(
                    timeout=wake_timeout, stop_event=self._stop_event)
            except TypeError:  # compatibility with existing wake adapters
                woke = self.wake.wait_for_wake(timeout=wake_timeout)
            except Exception as exc:  # noqa: BLE001 — text mode remains usable
                self.on_status(f"microphone unavailable: {exc}")
                break
            if self._stop_event.is_set():
                break
            if not woke:
                self.on_status("wake timeout, still listening…")
                continue
            self.on_status("woke up — listening…")
            try:
                cmd = capture_utterance(self.stt,
                                        vad=VAD(frame_ms=20), timeout=12.0,
                                        stop_event=self._stop_event)
            except Exception as exc:  # noqa: BLE001 — ASR failure is recoverable
                self.on_status(f"speech recognition failed: {exc}")
                continue
            if self._stop_event.is_set():
                break
            if not cmd:
                self.on_status("(silence)")
                continue
            self.on_status("Speech recognized; processing through E.V.…")
            try:
                reply = self.agent.run(cmd)
            except Exception as exc:  # noqa: BLE001 — return to listening after agent errors
                self.on_status(f"agent request failed: {exc}")
                continue
            self._say(reply)
        self.running = False
        self.on_status("voice session stopped")

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()
        stop_tts = getattr(self.tts, "stop", None)
        if callable(stop_tts):
            stop_tts()


def capture_utterance(stt, vad: VAD | None = None, timeout: float = 15.0,
                      frame_ms: int = 20, sample_rate: int = mic.RATE,
                      max_silence_ms: int = 500,
                      stop_event: threading.Event | None = None) -> str:
    """Record one utterance and transcribe it.

    Returns the transcript (possibly empty). `stt` is any object with a
    ``transcribe_bytes(bytes) -> str`` method (e.g. VoskSTT).
    """
    if vad is None:
        vad = VAD(frame_ms=frame_ms)
    stream = mic.MicStream(frame_ms=frame_ms)
    buffer = bytearray()
    silence_ms = 0
    saw_speech = False
    start = time.time()

    def on_frame(frame: bytes) -> None:
        nonlocal silence_ms, saw_speech
        speaking = vad.feed(frame)
        buffer.extend(frame)
        if speaking:
            saw_speech = True
            silence_ms = 0
        else:
            silence_ms += frame_ms

    stream.on_frame(on_frame)
    stream.start()
    try:
        while time.time() - start < timeout \
            and not (stop_event and stop_event.is_set()):
            if saw_speech and silence_ms >= max_silence_ms:
                break
            time.sleep(0.02)
    finally:
        stream.stop()

    data = bytes(buffer)
    if len(data) < sample_rate * mic.WIDTH // 4:
        return ""                 # too short to be a real utterance
    return stt.transcribe_bytes(data) if len(data) else ""