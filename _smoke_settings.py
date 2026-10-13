"""Settings store, CLI, and HUD API smoke. Run: python3 _smoke_settings.py"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from core.settings import SettingsStore
from ui.cli.repl import CLI
from ui.web.server import create_app


def test_cli(store: SettingsStore) -> None:
    cli = CLI(
        object(), store.config,
        on_settings=store.snapshot,
        on_settings_update=store.update_config,
        on_credentials_update=store.update_credentials,
    )
    cli._settings_command('/settings set agent.name "Terminal E.V."')
    assert store.config["agent"]["name"] == "Terminal E.V."
    with patch("ui.cli.repl.getpass.getpass", return_value="terminal-token"):
        cli._settings_command("/settings secret GITHUB_TOKEN")
    assert os.environ["GITHUB_TOKEN"] == "terminal-token"


async def test_hud(store: SettingsStore) -> None:
    app = create_app(object(), store.config, settings=store)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/settings")
        assert response.status == 200
        snapshot = await response.json()
        github = next(item for item in snapshot["connections"]
                      if item["id"] == "github")
        token = next(field for field in github["fields"]
                     if field["name"] == "GITHUB_TOKEN")
        assert not token["configured"] and token["value"] == ""

        response = await client.post("/api/settings", json={
            "config": {"agent.name": "HUD E.V."},
            "credentials": {
                "TELEGRAM_BOT_TOKEN": "hud-secret-token",
                "TELEGRAM_ALLOWED_USER_IDS": "123,456",
            },
        })
        assert response.status == 200
        body_text = await response.text()
        body = json.loads(body_text)
        assert body["config"]["agent"]["name"] == "HUD E.V."
        assert body["restart_required"] is True
        assert "hud-secret-token" not in body_text
        telegram = next(item for item in body["connections"]
                        if item["id"] == "telegram")
        assert telegram["configured"] and telegram["restart_required"]

        response = await client.post("/api/settings", json={
            "credentials": {"NOT_ALLOWED_SECRET": "bad"},
        })
        assert response.status == 400


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        config = {"agent": {"name": "E.V."}, "voice": {"enabled": True}}
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        env_path = root / ".env"
        store = SettingsStore(config, env_path)
        original_env = {key: os.environ.get(key) for key in (
            "GITHUB_TOKEN", "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_USER_IDS")}
        try:
            for key in original_env:
                os.environ.pop(key, None)
            asyncio.run(test_hud(store))
            test_cli(store)
            assert env_path.stat().st_mode & 0o777 == 0o600
            print("settings store, terminal, HUD API, secret masking: ALL PASSED")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
