"""Wake-word engine — triggers the voice session (architecture §2).

Runs a lightweight continuous mic listener and uses a dedicated small
speech-to-text model only for wake detection, so the main LLM stays idle.

"E.V." (ای وی) is the default; synonyms and wake words list are configurable.
Detection is robust to Vosk's imperfect Farsi transcription: it accepts
exact matches, phonetic variants, and fuzzy edit-distance proximity.
"""
from __future__ import annotations

import time

from voice import mic
from voice.stt import VoskSTT
from voice.vad import VAD


class WakeWord:
    """Continuous wake-word listener built on Vosk STT + energy VAD."""

    WAKE_TOKENS = ("ای وی", "ایوی", "ای ویو", "e.v", "ev")
    _CLEAN = str.maketrans("", "", ".,!؟?،\u200c")

    # phonetic variants: Vosk's fa model may hear "ای وی" as "eye vee" etc.
    _PHONETIC = ("e v", "i v", "eye vee", "ay vee",
                 "a vee", "eh vee", "a v", "i vee", "iv")

    def __init__(self, words=None, stt=None, vad=None,
                 frame_ms=500, sample_rate=mic.RATE, sensitivity=1):
        self.words = tuple(w.lower() for w in (words or WakeWord.WAKE_TOKENS))
        self.stt = stt or VoskSTT()  # lazily built — needs data/models model
        self.vad = vad or VAD(frame_ms=frame_ms)
        self.frame_ms = frame_ms
        self.sample_rate = sample_rate
        self.model_path = getattr(self.stt, "model_path", None)
        self.last_activity = 0.0
        self.hits = []
        self.sensitivity = sensitivity

    @staticmethod
    def _normalize(text):
        return text.translate(WakeWord._CLEAN).strip().lower()

    @staticmethod
    def _edit_distance(a, b):
        """Fuzzy edit-distance proxy to tolerate Vosk character noise."""
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, a, b).ratio()
        return int(round((1 - ratio) * max(len(a), len(b), 1)))

    def is_wake(self, transcript):
        """Return True if transcript contains any configured wake word.

        Robust to Vosk Farsi model errors: exact substring, phonetic
        variants, and edit-distance proximity matching.
        """
        if not transcript:
            return False
        norm = WakeWord._normalize(transcript)
        joined = norm.replace(" ", "")
        # exact substring check (handles "ایوی" vs "ای وی")
        for w in self.words:
            wjoin = w.replace(" ", "")
            if wjoin and (wjoin in joined or joined in wjoin):
                return True
        # phonetic fallback
        for p in WakeWord._PHONETIC:
            pjoin = p.replace(" ", "")
            if pjoin and (pjoin in joined or joined in pjoin):
                return True
        # fuzzy edit distance — Vosk often splits/merges Persian chars
        tokens = joined.split() if joined else []
        for w in self.words:
            wjoin = w.replace(" ", "")
            for tok in tokens:
                if self._edit_distance(wjoin, tok) <= self.sensitivity:
                    return True
        return False

    def listen_once(self, timeout=12.0):
        """Capture one utterance from the mic; return transcript."""
        from voice.session import capture_utterance  # circular-safe import
        return capture_utterance(
            stt=self.stt, vad=self.vad, timeout=timeout,
            sample_rate=self.sample_rate)

    def wait_for_wake(self, timeout=120.0):
        """Continuous listening loop; returns True when wake word is heard.

        Uses Vosk streaming ``PartialResult`` for fast wake-word detection:
        partial hypotheses are scored continuously as speech unfolds, so a
        wake word is caught before the speaker finishes. A VAD gate prevents
        transcribing silence; a debounce avoids re-checking identical text.
        """
        import json
        from voice.stt import _load
        from vosk import KaldiRecognizer

        start = time.time()
        model = _load(self.model_path) if self.model_path else _load()
        rec = KaldiRecognizer(model, self.sample_rate)
        vad = self.vad  # may be None

        stream = mic.MicStream(frame_ms=40)  # 40ms frames — good latency/CPU
        outcome = False
        last_partial = ""

        def on_frame(frame):
            nonlocal outcome, last_partial
            if outcome:
                return
            # VAD gate: skip frames that contain no speech energy
            if vad is not None and not vad.feed(frame):
                return
            if not rec.AcceptWaveform(frame):
                try:
                    partial = json.loads(rec.PartialResult()).get("partial", "")
                except Exception:
                    partial = ""
                if partial != last_partial:
                    last_partial = partial
                    if partial and self.is_wake(partial):
                        self.hits.append({"ts": time.time(), "text": partial})
                        outcome = True
                        stream.stop()
            else:
                try:
                    text = json.loads(rec.Result()).get("text", "")
                except Exception:
                    text = ""
                last_partial = ""
                if text and self.is_wake(text):
                    self.hits.append({"ts": time.time(), "text": text})
                    outcome = True
                    stream.stop()

        stream.on_frame(on_frame)
        stream.start()
        try:
            while not outcome and time.time() - start < timeout:
                time.sleep(0.02)
        finally:
            stream.stop()
        return outcome
