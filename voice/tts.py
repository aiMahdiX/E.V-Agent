"""Text-to-speech (Phase 2) — thin wrapper over models.tts."""
from __future__ import annotations

from models.tts import EdgeTTS, EspeakTTS, PiperTTS
from voice.router import SpeechRouter


class VoiceTTS:
    def __init__(self, backend: str = "piper", model_path=None,
                 config: dict | None = None, data_root="data/models"):
        settings = dict(config or {})
        settings.setdefault("mode", "local")
        settings.setdefault("tts_backend", backend)
        if model_path is not None:
            settings.setdefault("tts_piper_model", str(model_path))
            settings.setdefault("tts_voices", {"fa": str(model_path)})
        self.router = SpeechRouter(settings, data_root=data_root)
        self.model = self.router

    def warm(self):
        """Preload the TTS model so the first reply is instant."""
        self.router.warm()

    def speak(self, text: str, block: bool = False,
              language: str | None = None) -> None:
        """Synthesize and speak text through the default audio device."""
        self.router.speak(text, language=language, block=block)

    def synthesize(self, text: str, out_path=None,
                   language: str | None = None):
        return self.router.synthesize(text, language=language,
                                      out_path=out_path)

    def stop(self) -> None:
        self.router.stop()
