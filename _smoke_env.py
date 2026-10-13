"""Smoke tests for typed .env overrides. Run: python3 _smoke_env.py"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from main import ROOT, load_config


def main() -> int:
    base_config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as clean_env:
        loaded_config = load_config(env_path=Path(clean_env) / ".env",
                                    environ={})
    assert loaded_config == base_config, "local .env does not mirror config.json"
    example_config = load_config(env_path=ROOT / ".env.example", environ={})
    assert example_config == base_config, ".env.example does not mirror config.json"

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        config_path = root / "config.json"
        env_path = root / ".env"
        config_path.write_text(json.dumps({
            "ollama": {"timeout": 10},
            "voice": {"wake_words": ["default"]},
            "model_selection": {"fixed": "local"},
        }), encoding="utf-8")
        env_path.write_text(
            'EV__OLLAMA__TIMEOUT=30\n'
            'EV__VOICE__WAKE_WORDS=["e.v","ای وی"]\n'
            'EV__MODEL_SELECTION__FIXED=null\n'
            'ASHNA_API_KEY="file-key"\n',
            encoding="utf-8")
        file_env = {}
        load_config(config_path, env_path, file_env)
        assert file_env["ASHNA_API_KEY"] == "file-key"
        process_env = {
            "EV__OLLAMA__TIMEOUT": "45",
            "ASHNA_API_KEY": "process-key",
        }
        config = load_config(config_path, env_path, process_env)
        bad_env = root / "bad.env"
        bad_env.write_text("EV__OLLAMA__MISSING=1\n", encoding="utf-8")
        try:
            load_config(config_path, bad_env, {})
        except ValueError as exc:
            assert "EV__OLLAMA__MISSING" in str(exc)
        else:
            raise AssertionError("Unknown EV__ config paths should fail")

    assert config["ollama"]["timeout"] == 45
    assert config["voice"]["wake_words"] == ["e.v", "ای وی"]
    assert config["model_selection"]["fixed"] is None
    assert process_env["ASHNA_API_KEY"] == "process-key"
    assert process_env["EV__OLLAMA__TIMEOUT"] == "45"
    print("typed .env mapping and precedence: ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())