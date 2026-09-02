"""Text-to-speech (Phase 2) — thin wrapper over models.tts."""
from __future__ import annotations

from models.tts import TTSModel, EdgeTTS, EspeakTTS, PiperTTS


class VoiceTTS:
    def __init__(self, backend: str = "piper", model_path=None):
        self.model = TTSModel(backend=backend, model_path=model_path)

    def warm(self):
        """Preload the TTS model so the first reply is instant."""
        if self.model is not None:
            self.model.warm()

    def speak(self, text: str, block: bool = False) -> None:
        """Synthesize and speak text through the default audio device."""
        self.model.speak(text, block=block)

    def synthesize(self, text: str, out_path=None):
        return self.model.synthesize(text, out_path)
