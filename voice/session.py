"""Voice session — utterance capture + the hands-free loop (architecture §1, §2).

Workflow:
    Idle -> Listening (after wake) -> STT -> Agent -> TTS -> Idle

``capture_utterance`` gathers a short clip of speech from the mic and
transcribes it. ``VoiceLoop`` drives the whole experience using the shared
wake-word + STT + TTS + Agent pipeline.
"""
from __future__ import annotations

import time

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

    def _say(self, text: str) -> None:
        if text:
            self.tts.speak(text, block=False)

    # ------------------------------------------------------------------ #
    def run(self, wake_timeout: float = 120.0) -> None:
        self.running = True
        self.on_status("listening for wake word…")
        while self.running:
            if not self.wake.wait_for_wake(timeout=wake_timeout):
                self.on_status("wake timeout, still listening…")
                continue
            self.on_status("woke up — listening…")
            cmd = capture_utterance(self.stt,
                                    vad=VAD(frame_ms=20), timeout=12.0)
            if not cmd:
                self.on_status("(silence)")
                continue
            self.on_status(f"Heard: {cmd}")
            reply = self.agent.run(cmd)
            self._say(reply)

    def stop(self) -> None:
        self.running = False


def capture_utterance(stt, vad: VAD | None = None, timeout: float = 15.0,
                      frame_ms: int = 20, sample_rate: int = mic.RATE,
                      max_silence_ms: int = 500) -> str:
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
        while time.time() - start < timeout:
            if saw_speech and silence_ms >= max_silence_ms:
                break
            time.sleep(0.02)
    finally:
        stream.stop()

    data = bytes(buffer)
    if len(data) < sample_rate * mic.WIDTH // 4:
        return ""                 # too short to be a real utterance
    return stt.transcribe_bytes(data) if len(data) else ""