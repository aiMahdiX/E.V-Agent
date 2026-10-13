"""Voice configuration defaults and backward-compatible migration."""
from __future__ import annotations

from copy import deepcopy


VOICE_DEFAULTS = {
    "enabled": True,
    "mode": "local",
    "wizard_language": "auto",
    "languages": ["fa"],
    "language": "fa",
    "asr_provider": "auto",
    "tts_provider": "piper",
    "reasoning_provider": "local",
    "voice_preference": "any",
    "purpose": "all",
    "barge_in": True,
    "vad_enabled": True,
    "vision_enabled": False,
    "stt_backend": "vosk",
    "stt_model": "data/models/vosk-model-small-fa-0.5",
    "asr_device": "auto",
    "faster_whisper_model_path": None,
    "microphone_device": None,
    "speaker_device": None,
    "vad_mode": "energy",
    "vad_frame_ms": 20,
    "vad_threshold": 180,
    "vad_hangover_ms": 240,
    "tts_backend": "piper",
    "tts_voice": "fa_IR-amir-medium",
    "tts_piper_model": "data/models/piper/fa_IR-amir-medium.onnx",
    "tts_voices": {"fa": "data/models/piper/fa_IR-amir-medium.onnx",
                    "en": None},
    "allow_cloud_audio": False,
    "audio_retention_seconds": 0,
}

LIVE_DEFAULTS = {
    "enabled": False,
    "provider": "gemini",
    "model": "gemini-3.8-live",
    "allow_audio_upload": False,
    "max_session_seconds": 600,
    "idle_timeout_seconds": 60,
    "daily_budget_usd": 0.0,
    "monthly_budget_usd": 0.0,
    "estimated_input_usd_per_minute": 0.005,
    "estimated_output_usd_per_minute": 0.018,
    "pricing_verified_date": "2026-10-09",
    "budget_preference": "free",
    "credentials_validated": False,
    "audio_retention_seconds": 0,
}


def normalize_voice_config(config: dict) -> dict:
    """Fill voice defaults without discarding older flat settings or user data."""
    if not isinstance(config, dict):
        raise ValueError("application config must be an object")
    config.setdefault("operating_mode", "local")
    if not isinstance(config["operating_mode"], str) or \
            config["operating_mode"] not in {
                "local", "cloud", "hybrid", "custom"}:
        config["operating_mode"] = "local"
    cloud = config.setdefault("cloud", {})
    if not isinstance(cloud, dict):
        raise ValueError("cloud config must be an object")
    cloud.setdefault("allow_text", False)
    voice = config.setdefault("voice", {})
    if not isinstance(voice, dict):
        raise ValueError("voice config must be an object")
    defaults = deepcopy(VOICE_DEFAULTS)
    defaults.update(voice)
    if "asr_provider" not in voice and voice.get("stt_backend"):
        defaults["asr_provider"] = voice["stt_backend"]
    if "tts_provider" not in voice and voice.get("tts_backend"):
        defaults["tts_provider"] = voice["tts_backend"]
    voices = dict(VOICE_DEFAULTS["tts_voices"])
    if isinstance(voice.get("tts_voices"), dict):
        voices.update(voice["tts_voices"])
    voices.setdefault("fa", voice.get("tts_piper_model"))
    defaults["tts_voices"] = voices
    defaults["languages"] = list(defaults.get("languages") or ["fa"])
    config["voice"] = defaults

    live = config.setdefault("live", {})
    if not isinstance(live, dict):
        raise ValueError("live config must be an object")
    normalized_live = deepcopy(LIVE_DEFAULTS)
    normalized_live.update(live)
    config["live"] = normalized_live
    return config