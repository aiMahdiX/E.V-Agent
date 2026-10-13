"""Interactive first-run voice setup; cloud features remain opt-in."""
from __future__ import annotations

import getpass
import os
from pathlib import Path

from voice.config import normalize_voice_config
from voice.hardware import detect_hardware, recommend_configuration
from voice.installer import (InstallationCancelled, VoiceInstallError,
                             VoiceInstallManager)
from voice.secrets import SecretStoreError, VoiceSecretStore


_TEXT = {
    "en": {
        "title": "E.V. Voice & Live setup",
        "language": "Wizard language [en/fa]",
        "modes": "1. Local-only: no cloud inference.\n2. Cloud-only: remote reasoning and voice; internet and billing may apply.\n3. Hybrid: local by default; cloud features need separate consent.\n4. Custom: choose ASR, TTS, Live, and reasoning independently.",
        "mode": "Mode: 1 Local-only, 2 Cloud-only, 3 Hybrid, 4 Custom [1]",
        "languages": "Primary languages: fa, en, or both [fa]",
        "voice": "Voice preference: any, feminine, or masculine [any]",
        "purpose": "Main purpose: commands, conversation, coding, desktop, or all [all]",
        "custom_asr": "Custom ASR: vosk, faster-whisper, or auto [auto]",
        "custom_tts": "Custom TTS: piper, edge, or auto [piper]",
        "custom_reasoning": "Custom reasoning: local, configured-cloud, or auto [local]",
        "realtime": "Enable native real-time speech-to-speech? [y/N]",
        "barge": "Enable interruption/barge-in where supported? [Y/n]",
        "vad": "Enable local voice activity detection for fallback? [Y/n]",
        "vision": "Allow optional camera/screen input in voice sessions? [y/N]",
        "retention": "Retain local recordings? 0 keeps none; otherwise seconds [0]",
        "budget": "Budget preference: free, minimum-cost, or quality [free]",
        "cloud_text_consent": "May E.V. send text/transcripts to a cloud reasoning provider? [y/N]",
        "cloud_consent": "This sends live microphone audio to Google. Allow it? [y/N]",
        "budget_amounts": "Daily/monthly USD budget, separated by comma [1,5]",
        "gemini_details": (
            "Gemini Live uses native speech-to-speech over WebSockets. "
            "The service receives live audio; API billing/limits may apply.\n"
            "Official key: https://aistudio.google.com/apikey\n"
            "Official pricing: https://ai.google.dev/gemini-api/docs/pricing"
        ),
        "install_sdk": "Install the optional Gemini/keyring/crypto Python packages now? [y/N]",
        "install_en_model": "Download the official English Vosk model (~40 MiB)? [y/N]",
        "api_key": "Gemini API key (hidden; Enter skips)",
        "test_key": "Validate the key with a model metadata request? [y/N]",
        "vault_pass": "Encrypted vault passphrase (12+ characters)",
        "vault_confirm": "Confirm vault passphrase",
        "apply": "Save this configuration? [Y/n]",
        "saved": "Voice configuration saved.",
        "skipped": "Optional cloud setup skipped; local voice remains available.",
        "key_bad": "Connection test failed. The key remains securely stored; Live stays disabled.",
        "key_ok": "Gemini API key validated; native Live is enabled with explicit audio consent.",
        "no_cloud_llm": "Cloud-only needs a configured non-local text model provider. Keeping local mode.",
        "incomplete_languages": "Requested languages are not all installed for local ASR/TTS. See the recommendations below.",
        "recommendation": "Recommended components:",
        "privacy": "No audio is retained by default. Local mode does not call cloud inference.",
        "no_secure_store": "No secure keyring or encrypted vault is available; the key was not requested or stored.",
        "error": "Setup error",
    },
    "fa": {
        "title": "راه‌اندازی صوت و Live در E.V.",
        "language": "زبان راهنما [en/fa]",
        "modes": "1. فقط محلی: بدون inference ابری.\n2. فقط ابری: استدلال و صوت remote؛ اینترنت و احتمال هزینه لازم است.\n3. ترکیبی: پیش‌فرض محلی؛ قابلیت‌های ابری اجازهٔ جداگانه می‌خواهند.\n4. سفارشی: ASR، TTS، Live و استدلال را جدا انتخاب کن.",
        "mode": "حالت: 1 فقط محلی، 2 فقط ابری، 3 ترکیبی، 4 سفارشی [1]",
        "languages": "زبان‌های اصلی: fa، en یا both [fa]",
        "voice": "ترجیح صدا: any، feminine یا masculine [any]",
        "purpose": "کاربرد اصلی: commands، conversation، coding، desktop یا all [all]",
        "custom_asr": "ASR سفارشی: vosk، faster-whisper یا auto [auto]",
        "custom_tts": "TTS سفارشی: piper، edge یا auto [piper]",
        "custom_reasoning": "استدلال سفارشی: local، configured-cloud یا auto [local]",
        "realtime": "گفتگوی زندهٔ صوتی به صوتی فعال شود؟ [y/N]",
        "barge": "در صورت پشتیبانی، امکان قطع‌کردن و barge-in فعال شود؟ [Y/n]",
        "vad": "برای مسیر محلی VAD فعال باشد؟ [Y/n]",
        "vision": "ورودی اختیاری دوربین/صفحه در نشست صوتی مجاز باشد؟ [y/N]",
        "retention": "ضبط محلی نگه داشته شود؟ 0 یعنی هیچ‌چیز؛ وگرنه ثانیه [0]",
        "budget": "ترجیح هزینه: free، minimum-cost یا quality [free]",
        "cloud_text_consent": "اجازه می‌دهی متن/transcript برای استدلال به cloud فرستاده شود؟ [y/N]",
        "cloud_consent": "برای Live، صدای میکروفن به Google فرستاده می‌شود. اجازه می‌دهی؟ [y/N]",
        "budget_amounts": "بودجهٔ روزانه/ماهانه به USD، با ویرگول جدا کن [1,5]",
        "gemini_details": (
            "Gemini Live صوت را به‌صورت native speech-to-speech از WebSocket می‌فرستد. "
            "صدا به سرویس می‌رسد و ممکن است محدودیت/هزینهٔ API داشته باشد.\n"
            "کلید رسمی: https://aistudio.google.com/apikey\n"
            "قیمت رسمی: https://ai.google.dev/gemini-api/docs/pricing"
        ),
        "install_sdk": "بسته‌های اختیاری Gemini/keyring/crypto نصب شوند؟ [y/N]",
        "install_en_model": "مدل رسمی Vosk انگلیسی (حدود 40 MiB) دانلود شود؟ [y/N]",
        "api_key": "کلید Gemini (مخفی؛ Enter برای ردکردن)",
        "test_key": "کلید با درخواست metadata مدل بررسی شود؟ [y/N]",
        "vault_pass": "گذرواژهٔ vault رمزگذاری‌شده (حداقل ۱۲ نویسه)",
        "vault_confirm": "تکرار گذرواژهٔ vault",
        "apply": "این پیکربندی ذخیره شود؟ [Y/n]",
        "saved": "تنظیمات صوت ذخیره شد.",
        "skipped": "راه‌اندازی ابری رد شد؛ مسیر صوت محلی باقی می‌ماند.",
        "key_bad": "آزمون اتصال شکست خورد. کلید امن ذخیره شد؛ Live غیرفعال می‌ماند.",
        "key_ok": "کلید Gemini معتبر است؛ Live با اجازهٔ صریح ارسال صدا فعال شد.",
        "no_cloud_llm": "حالت فقط ابری به provider متنی غیرمحلی نیاز دارد؛ حالت محلی حفظ شد.",
        "incomplete_languages": "همهٔ زبان‌های درخواستی برای ASR/TTS محلی نصب نیستند؛ پیشنهادها پایین آمده‌اند.",
        "recommendation": "اجزای پیشنهادی:",
        "privacy": "به‌طور پیش‌فرض صدایی ذخیره نمی‌شود. حالت محلی inference ابری اجرا نمی‌کند.",
        "no_secure_store": "keyring امن یا vault رمزگذاری‌شده موجود نیست؛ کلید درخواست یا ذخیره نشد.",
        "error": "خطای راه‌اندازی",
    },
}


def _ask(input_fn, prompt: str, default: str = "") -> str:
    answer = input_fn(f"{prompt} ").strip()
    return answer or default


def _yes(input_fn, prompt: str, default: bool = False) -> bool:
    answer = _ask(input_fn, prompt, "y" if default else "n").casefold()
    return answer in {"y", "yes", "بله", "آره", "ب"}


def _language_set(value: str) -> list[str]:
    normalized = value.casefold().strip()
    if normalized in {"both", "fa+en", "en+fa", "هر دو", "دو"}:
        return ["fa", "en"]
    if normalized in {"en", "english", "انگلیسی"}:
        return ["en"]
    return ["fa"]


def _save(config: dict, updates: dict, update_config) -> None:
    if update_config is not None:
        update_config(updates)
        return
    for dotted, value in updates.items():
        parts = dotted.split(".")
        node = config
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


def _test_gemini_key(api_key: str, model: str) -> tuple[bool, str]:
    """Validate auth via model metadata only; never generate or upload audio."""
    try:
        from google import genai
    except ImportError:
        return False, "google-genai is not installed"
    client = None
    try:
        client = genai.Client(api_key=api_key)
        model_info = client.models.get(model=model)
        return True, str(getattr(model_info, "name", model))
    except Exception as exc:  # noqa: BLE001 — strip key from SDK errors
        detail = str(exc).replace(api_key, "[REDACTED]")[:400]
        return False, detail
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def run_setup_wizard(config: dict, installer: VoiceInstallManager,
                     secrets_store: VoiceSecretStore, *, update_config=None,
                     input_fn=None, secret_input_fn=None,
                     output_fn=None) -> dict:
    """Configure modes/languages; optional installs and cloud are consent gated."""
    input_fn = input_fn or input
    secret_input_fn = secret_input_fn or getpass.getpass
    output_fn = output_fn or print
    existing_language = str(config.get("voice", {}).get(
        "wizard_language", config.get("agent", {}).get("language", "auto"))).casefold()
    if existing_language in {"fa", "farsi", "persian"}:
        language_default = "fa"
    else:
        language_default = "en"
    choice = _ask(input_fn, _TEXT["en"]["language"], language_default)
    ui_language = "fa" if choice.casefold() in {"fa", "persian", "فارسی"} else "en"
    text = _TEXT[ui_language]
    output_fn(f"\n{text['title']}")
    output_fn(text["modes"])
    mode_value = _ask(input_fn, text["mode"], "1")
    mode = {"1": "local", "2": "cloud", "3": "hybrid", "4": "custom"}.get(
        mode_value, "local")
    languages = _language_set(_ask(input_fn, text["languages"], "fa"))
    voice_preference = _ask(input_fn, text["voice"], "any").casefold()
    purpose = _ask(input_fn, text["purpose"], "all")
    if mode == "custom":
        custom_asr = _ask(input_fn, text["custom_asr"], "auto").casefold()
        custom_tts = _ask(input_fn, text["custom_tts"], "piper").casefold()
        custom_reasoning = _ask(input_fn, text["custom_reasoning"], "local").casefold()
    else:
        custom_asr, custom_tts, custom_reasoning = "auto", "piper", "local"
    realtime = _yes(input_fn, text["realtime"], False)
    barge_in = _yes(input_fn, text["barge"], True)
    vad_enabled = _yes(input_fn, text["vad"], True)
    vision_enabled = _yes(input_fn, text["vision"], False)
    try:
        retention = int(_ask(input_fn, text["retention"], "0"))
        retention = max(0, min(retention, 30 * 86400))
    except ValueError:
        retention = 0
    budget_preference = _ask(input_fn, text["budget"], "free")

    text_consent = False
    audio_consent = False
    if mode in {"cloud", "hybrid", "custom"}:
        text_consent = _yes(input_fn, text["cloud_text_consent"], False)
        if realtime:
            audio_consent = _yes(input_fn, text["cloud_consent"], False)
    if mode == "cloud":
        provider_cfg = config.get("providers", {})
        default_provider = str(provider_cfg.get("default", "ollama")).split(":", 1)[0]
        cloud_settings = provider_cfg.get("instances", {}).get(default_provider, {})
        env_name = cloud_settings.get("api_key_env") if isinstance(
            cloud_settings, dict) else None
        if (not text_consent or default_provider == "ollama"
                or not env_name or not os.getenv(env_name)):
            output_fn(text["no_cloud_llm"])
            mode = "hybrid" if audio_consent else "local"

    report = detect_hardware(installer.models_dir)
    recommendation = recommend_configuration(
        report, languages=languages, purpose=purpose,
        budget=budget_preference)
    output_fn(text["recommendation"])
    output_fn(f"ASR: {recommendation['asr']['provider']} "
              f"({recommendation['asr']['state']}, {recommendation['asr_device']})")
    output_fn(f"TTS: {recommendation['tts']['provider']} "
              f"({recommendation['tts']['state']})")
    output_fn(f"Live: {'Gemini Live opt-in' if audio_consent and realtime else 'disabled'}")
    output_fn(text["privacy"])

    updates = {
        "operating_mode": mode,
        "cloud.allow_text": bool(text_consent and mode in {"cloud", "hybrid", "custom"}),
        "voice.mode": mode,
        "voice.wizard_language": ui_language,
        "voice.languages": languages,
        "voice.language": languages[0],
        "voice.voice_preference": voice_preference,
        "voice.purpose": purpose,
        "voice.asr_provider": custom_asr,
        "voice.tts_provider": custom_tts,
        "voice.reasoning_provider": custom_reasoning,
        "voice.barge_in": barge_in,
        "voice.vad_enabled": vad_enabled,
        "voice.vision_enabled": vision_enabled,
        "voice.audio_retention_seconds": retention,
        "voice.allow_cloud_audio": bool(audio_consent),
        "live.allow_audio_upload": bool(audio_consent),
        "live.enabled": False,
        "live.budget_preference": budget_preference,
    }
    if budget_preference == "free":
        updates["live.daily_budget_usd"] = 0.0
        updates["live.monthly_budget_usd"] = 0.0
    else:
        default_budgets = "5,25" if budget_preference == "quality" else "1,5"
        try:
            daily, monthly = [float(value.strip()) for value in
                              _ask(input_fn, text["budget_amounts"],
                                   default_budgets).split(",", 1)]
            if daily < 0 or monthly < 0:
                raise ValueError
            updates["live.daily_budget_usd"] = daily
            updates["live.monthly_budget_usd"] = monthly
        except (ValueError, TypeError):
            updates["live.daily_budget_usd"] = 0.0
            updates["live.monthly_budget_usd"] = 0.0

    available = set(recommendation["asr"].get("language", [])
                    if isinstance(recommendation["asr"].get("language"), list)
                    else [])
    selected_primary = languages[0]
    if recommendation["asr"]["state"] == "partial_language_coverage":
        available = set(recommendation["asr"].get("language", []))
        if available:
            selected_primary = next(
                (language for language in languages if language in available),
                languages[0])
            updates["voice.language"] = selected_primary
            output_fn(text["incomplete_languages"])
    elif recommendation["asr"]["state"] == "needs_model_or_runtime":
        output_fn(text["incomplete_languages"])

    if "en" in languages and "en" not in available \
            and not report["components"]["modules"].get("faster_whisper"):
        if _yes(input_fn, text["install_en_model"], False):
            try:
                installer.install_model(
                    "vosk_en_small",
                    confirm=lambda _name, _details: True,
                    progress=lambda _name, done, total: output_fn(
                        f"Download progress: {done}/{total} bytes"))
                updates["voice.language"] = selected_primary
            except (VoiceInstallError, InstallationCancelled) as exc:
                output_fn(f"{text['error']}: {exc}")

    if audio_consent and realtime and mode in {"hybrid", "cloud", "custom"}:
        output_fn(text["gemini_details"])
        sdk_ready = report["components"]["modules"].get("google.genai", False)
        secure_status = secrets_store.status()
        if not sdk_ready or not secure_status["available"]:
            if _yes(input_fn, text["install_sdk"], False):
                try:
                    installer.install_package(
                        "gemini_live",
                        confirm=lambda _name, details: _yes(
                            input_fn,
                            f"Install {details['requirements']} in .venv? "
                            "No model/audio data will be downloaded. [y/N]",
                            False),
                        progress=lambda _name, line: output_fn(line))
                except (VoiceInstallError, InstallationCancelled) as exc:
                    output_fn(f"{text['error']}: {exc}")
            secure_status = secrets_store.status()
        if (secure_status["backend"] == "unavailable"
                and not secure_status["available"]):
            output_fn(text["no_secure_store"])
        else:
            if secure_status["backend"] == "encrypted_vault" \
                    and not secure_status["unlocked"]:
                passphrase = secret_input_fn(text["vault_pass"] + ": ")
                create_vault = not secrets_store.vault_path.exists()
                if create_vault:
                    confirmation = secret_input_fn(
                        text["vault_confirm"] + ": ")
                    if passphrase != confirmation:
                        passphrase = ""
                        output_fn("Vault passphrases did not match; cloud setup skipped.")
                try:
                    if passphrase:
                        secrets_store.unlock_vault(passphrase,
                                                   create=create_vault)
                except SecretStoreError as exc:
                    output_fn(f"{text['error']}: {exc}")
                    passphrase = ""
            elif secure_status["backend"] == "unavailable" \
                    and secure_status["available"]:
                passphrase = secret_input_fn(text["vault_pass"] + ": ")
                confirmation = secret_input_fn(text["vault_confirm"] + ": ")
                try:
                    if passphrase and passphrase == confirmation:
                        secrets_store.unlock_vault(passphrase, create=True)
                    else:
                        passphrase = ""
                        output_fn("Vault passphrases did not match; cloud setup skipped.")
                except SecretStoreError as exc:
                    output_fn(f"{text['error']}: {exc}")
                    passphrase = ""
            else:
                passphrase = "ready"
            key = secret_input_fn(text["api_key"] + ": ").strip()
            if key and passphrase:
                try:
                    secrets_store.set("GEMINI_API_KEY", key)
                    if _yes(input_fn, text["test_key"], False):
                        okay, detail = _test_gemini_key(key, "gemini-3.8-live")
                        output_fn((text["key_ok"] + f" ({detail})") if okay
                                  else f"{text['key_bad']} {detail}")
                        if (okay and updates.get("live.daily_budget_usd", 0) > 0
                                and updates.get("live.monthly_budget_usd", 0) > 0):
                            updates["live.enabled"] = True
                        elif okay:
                            output_fn("Live remains disabled because no paid cloud budget was configured.")
                    else:
                        output_fn("Key saved securely; Live remains disabled until tested.")
                except SecretStoreError as exc:
                    output_fn(f"{text['error']}: {exc}")
                    status = secrets_store.status()
                    if status["backend"] == "os_keyring" and status["available"]:
                        vault_passphrase = secret_input_fn(
                            text["vault_pass"] + ": ")
                        confirmation = secret_input_fn(
                            text["vault_confirm"] + ": ")
                        if (vault_passphrase
                                and vault_passphrase == confirmation):
                            try:
                                secrets_store.unlock_vault(
                                    vault_passphrase, create=True)
                                secrets_store.set("GEMINI_API_KEY", key)
                                output_fn(
                                    "Stored in the encrypted local vault; "
                                    "unlock it on future launches.")
                            except SecretStoreError as vault_error:
                                output_fn(f"{text['error']}: {vault_error}")
    elif mode == "local":
        updates["voice.allow_cloud_audio"] = False
        updates["live.allow_audio_upload"] = False
        updates["live.enabled"] = False

    if not _yes(input_fn, text["apply"], True):
        return {"saved": False, "recommendation": recommendation,
                "mode": mode}
    _save(config, updates, update_config)
    output_fn(text["saved"])
    return {"saved": True, "mode": mode,
            "recommendation": recommendation, "updates": updates}


def main() -> int:
    from core.settings import SettingsStore
    from main import ROOT, load_config

    config = normalize_voice_config(load_config())
    settings = SettingsStore(config, ROOT / ".env")
    manager = VoiceInstallManager(ROOT)
    secrets_store = VoiceSecretStore(ROOT / "data" / "voice" / "secrets.json")
    run_setup_wizard(config, manager, secrets_store,
                     update_config=settings.update_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())