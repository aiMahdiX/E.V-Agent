"""Interactive setup for local Ollama or a consented hosted LLM provider."""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from core.settings import SettingsStore
from models.cloud_providers import CLOUD_PROVIDERS, CUSTOM_PROVIDER


def _validate_api_key(api_key: str, base_url: str, model: str,
                      client_factory=None) -> tuple[bool, str]:
    """Send a tiny explicit test request; never include user data in it."""
    if client_factory is None:
        try:
            from openai import OpenAI
        except ImportError:
            return False, "The optional openai package is not installed."
        client_factory = OpenAI
    client = None
    try:
        client = client_factory(api_key=api_key, base_url=base_url,
                                timeout=30)
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=4,
        )
        return True, "API key and model accepted."
    except Exception as exc:  # noqa: BLE001 - provider SDK errors vary
        detail = str(exc).replace(api_key, "[REDACTED]")[:300]
        return False, detail or type(exc).__name__
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - cleanup must not mask validation
                    pass


def _install_openai(output_fn=print) -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        output_fn("Installing the OpenAI-compatible API client in .venv...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "openai>=1.0"],
        check=False,
    )
    return result.returncode == 0


def _valid_base_url(value: str) -> bool:
    parsed = urlparse(value)
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return parsed.hostname.casefold() == "localhost"


def run_provider_setup(config: dict, settings: SettingsStore, *,
                       input_fn=None, secret_input_fn=None, output_fn=None,
                       validator=_validate_api_key,
                       install_sdk=_install_openai,
                       selected_provider: str | None = None) -> dict:
    input_fn = input_fn or input
    secret_input_fn = secret_input_fn or getpass.getpass
    output_fn = output_fn or print

    output_fn("Cloud providers (OpenAI-compatible API):")
    choices = list(CLOUD_PROVIDERS)
    for index, provider_id in enumerate(choices, 1):
        output_fn(f"  {index}. {CLOUD_PROVIDERS[provider_id]['label']}")
    output_fn(f"  {len(choices) + 1}. Custom OpenAI-compatible endpoint")

    if selected_provider is None:
        choice = input_fn("Provider number or id [1]: ").strip() or "1"
        if choice.isdigit():
            index = int(choice)
            if not 1 <= index <= len(choices) + 1:
                output_fn("Invalid provider selection.")
                return {"saved": False, "reason": "invalid_selection"}
            provider_id = (choices[index - 1] if index <= len(choices)
                           else "custom")
        else:
            provider_id = choice.casefold()
    else:
        provider_id = selected_provider.casefold()

    if provider_id == "custom":
        provider = dict(CUSTOM_PROVIDER)
        base_url = input_fn("OpenAI-compatible API base URL: ").strip().rstrip("/")
        if not _valid_base_url(base_url):
            output_fn("Enter a valid http:// or https:// API base URL.")
            return {"saved": False, "reason": "invalid_base_url"}
        model = input_fn("Model id: ").strip()
        if not model:
            output_fn("Model id cannot be empty.")
            return {"saved": False, "reason": "missing_model"}
    elif provider_id in CLOUD_PROVIDERS:
        provider = dict(CLOUD_PROVIDERS[provider_id])
        config_provider = config.get("providers", {}).get(
            "instances", {}).get(provider_id, {})
        base_url = str(config_provider.get("base_url") or provider.get("base_url", ""))
        model = str(config_provider.get("model") or provider.get("model", ""))
        model = input_fn(f"Model id [{model}]: ").strip() or model
    else:
        output_fn("Unknown provider id.")
        return {"saved": False, "reason": "unknown_provider"}

    output_fn("The setup sends one short test prompt to this provider. It may incur a small API charge.")
    if input_fn("Continue with the API test? [y/N] ").strip().casefold() \
            not in {"y", "yes", "بله", "آره"}:
        return {"saved": False, "reason": "test_not_consented"}
    if not install_sdk(output_fn):
        output_fn("Could not install the optional openai package.")
        return {"saved": False, "reason": "sdk_install_failed"}

    api_key = secret_input_fn(f"{provider['label']} API key (hidden): ").strip()
    if not api_key:
        output_fn("No API key entered; configuration was not changed.")
        return {"saved": False, "reason": "empty_key"}
    okay, detail = validator(api_key, base_url, model)
    if not okay:
        output_fn(f"API validation failed: {detail}")
        output_fn("Configuration was not changed. Check the key, model, and account access.")
        return {"saved": False, "reason": "validation_failed"}

    try:
        settings.update_credentials({provider["api_key_env"]: api_key})
        updates = {
            "providers.default": provider_id,
            "operating_mode": "cloud",
            "cloud.allow_text": True,
            "model_selection.mode": "fixed",
            "model_selection.fixed": f"{provider_id}:{model}",
            "model_selection.include_cloud": True,
        }
        if provider_id == "custom":
            updates["providers.instances.custom.base_url"] = base_url
            updates["providers.instances.custom.model"] = model
        settings.update_config(updates)
    except (OSError, ValueError) as exc:
        output_fn(f"Could not save provider configuration: {exc}")
        return {"saved": False, "reason": "save_failed"}

    output_fn(f"Validated and configured {provider['label']} ({model}).")
    output_fn("Cloud text inference is enabled. Audio is not uploaded by this setup.")
    return {"saved": True, "provider": provider_id, "model": model}


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure a cloud LLM provider")
    parser.add_argument("provider", nargs="?", help="provider id or 'custom'")
    args = parser.parse_args()
    from main import ROOT, load_config

    config = load_config()
    settings = SettingsStore(config, ROOT / ".env")
    result = run_provider_setup(config, settings,
                                selected_provider=args.provider)
    return 0 if result.get("saved") else 1


if __name__ == "__main__":
    raise SystemExit(main())