"""Offline smoke checks for hosted provider setup. Run: python3 _smoke_provider_setup.py"""
from __future__ import annotations

import tempfile
from pathlib import Path

from core.provider_setup import (_valid_base_url, _validate_api_key,
                                 run_provider_setup)
from core.settings import SettingsStore


def _config() -> dict:
    return {
        "operating_mode": "local",
        "cloud": {"allow_text": False},
        "providers": {
            "default": "ollama",
            "instances": {
                "openai": {
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4.1-mini",
                },
                "custom": {"base_url": "", "model": ""},
            },
        },
        "model_selection": {
            "mode": "auto", "fixed": None, "include_cloud": False,
        },
    }


def test_success_persists_only_after_validation() -> None:
    with tempfile.TemporaryDirectory() as temp:
        config = _config()
        env_path = Path(temp) / ".env"
        store = SettingsStore(config, env_path)
        prompts = iter(["", "y"])
        outputs = []
        calls = []

        def validator(key, base_url, model):
            calls.append((key, base_url, model))
            return True, "ok"

        result = run_provider_setup(
            config, store, selected_provider="openai",
            input_fn=lambda _prompt: next(prompts),
            secret_input_fn=lambda _prompt: "test-api-secret",
            output_fn=outputs.append, validator=validator,
            install_sdk=lambda _output: True,
        )
        assert result == {"saved": True, "provider": "openai",
                          "model": "gpt-4.1-mini"}
        assert calls == [("test-api-secret", "https://api.openai.com/v1",
                          "gpt-4.1-mini")]
        assert config["operating_mode"] == "cloud"
        assert config["providers"]["default"] == "openai"
        assert config["model_selection"]["fixed"] == "openai:gpt-4.1-mini"
        assert "test-api-secret" in env_path.read_text(encoding="utf-8")
        assert env_path.stat().st_mode & 0o777 == 0o600
        assert all("test-api-secret" not in output for output in outputs)


def test_invalid_key_does_not_change_config() -> None:
    with tempfile.TemporaryDirectory() as temp:
        config = _config()
        before = repr(config)
        env_path = Path(temp) / ".env"
        store = SettingsStore(config, env_path)
        prompts = iter(["", "y"])
        result = run_provider_setup(
            config, store, selected_provider="openai",
            input_fn=lambda _prompt: next(prompts),
            secret_input_fn=lambda _prompt: "bad-api-secret",
            output_fn=lambda _message: None,
            validator=lambda *_args: (False, "unauthorized"),
            install_sdk=lambda _output: True,
        )
        assert not result["saved"]
        assert repr(config) == before
        assert not env_path.exists()


def test_custom_endpoint_is_saved_after_successful_validation() -> None:
    assert _valid_base_url("https://llm.example.test/v1")
    assert _valid_base_url("http://127.0.0.1:1234/v1")
    assert not _valid_base_url("http://llm.example.test/v1")
    assert not _valid_base_url("https://user:pass@llm.example.test/v1")
    with tempfile.TemporaryDirectory() as temp:
        config = _config()
        store = SettingsStore(config, Path(temp) / ".env")
        prompts = iter([
            "https://llm.example.test/v1",
            "custom-model",
            "yes",
        ])
        result = run_provider_setup(
            config, store, selected_provider="custom",
            input_fn=lambda _prompt: next(prompts),
            secret_input_fn=lambda _prompt: "custom-secret",
            output_fn=lambda _message: None,
            validator=lambda *_args: (True, "ok"),
            install_sdk=lambda _output: True,
        )
        assert result["saved"]
        assert config["providers"]["instances"]["custom"] == {
            "base_url": "https://llm.example.test/v1",
            "model": "custom-model",
        }
        assert config["providers"]["default"] == "custom"


def test_validator_sends_only_test_prompt_and_redacts_errors() -> None:
    seen = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("bad key: test-secret")

    class FakeClient:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.chat = type("Chat", (), {
                "completions": FakeCompletions(),
            })()

        def close(self):
            seen["closed"] = True

    okay, detail = _validate_api_key(
        "test-secret", "https://api.example.test/v1", "test-model",
        client_factory=FakeClient,
    )
    assert not okay and "test-secret" not in detail
    assert seen["messages"] == [{"role": "user", "content": "Reply with OK."}]
    assert seen["model"] == "test-model"
    assert seen["closed"]


def main() -> int:
    test_success_persists_only_after_validation()
    test_invalid_key_does_not_change_config()
    test_custom_endpoint_is_saved_after_successful_validation()
    test_validator_sends_only_test_prompt_and_redacts_errors()
    print("provider setup validation, secret storage, and failure safety: ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())