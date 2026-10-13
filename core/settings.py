"""Shared settings storage for the CLI and local web HUD."""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from models.cloud_providers import CLOUD_PROVIDERS, CUSTOM_PROVIDER


CONNECTIONS = {
    "ashna": {
        "label": "Ashna AI",
        "fields": [("API key", "ASHNA_API_KEY", True)],
        "required": [("ASHNA_API_KEY",)],
    },
    "telegram": {
        "label": "Telegram",
        "fields": [
            ("Bot token", "TELEGRAM_BOT_TOKEN", True),
            ("Allowed user IDs", "TELEGRAM_ALLOWED_USER_IDS", False),
        ],
        "required": [("TELEGRAM_BOT_TOKEN",),
                     ("TELEGRAM_ALLOWED_USER_IDS",)],
        "restart": True,
    },
    "gmail": {
        "label": "Gmail",
        "fields": [("Access token", "GMAIL_ACCESS_TOKEN", True)],
        "required": [("GMAIL_ACCESS_TOKEN", "GOOGLE_ACCESS_TOKEN")],
    },
    "google_calendar": {
        "label": "Google Calendar",
        "fields": [("Access token", "GOOGLE_ACCESS_TOKEN", True)],
        "required": [("GOOGLE_ACCESS_TOKEN", "CALENDAR_ACCESS_TOKEN")],
    },
    "notion": {
        "label": "Notion",
        "fields": [
            ("API key", "NOTION_API_KEY", True),
            ("Database ID", "NOTION_DATABASE_ID", False),
        ],
        "required": [("NOTION_API_KEY",), ("NOTION_DATABASE_ID",)],
    },
    "slack": {
        "label": "Slack",
        "fields": [("Bot token", "SLACK_BOT_TOKEN", True)],
        "required": [("SLACK_BOT_TOKEN", "SLACK_TOKEN")],
    },
    "github": {
        "label": "GitHub",
        "fields": [
            ("Personal access token", "GITHUB_TOKEN", True),
            ("Owner", "GITHUB_OWNER", False),
            ("Repository (optional)", "GITHUB_REPO", False),
        ],
        "required": [("GITHUB_TOKEN",), ("GITHUB_OWNER",)],
    },
    "discord": {
        "label": "Discord",
        "fields": [("Bot token", "DISCORD_BOT_TOKEN", True)],
        "required": [("DISCORD_BOT_TOKEN",)],
    },
    "jira": {
        "label": "Jira",
        "fields": [
            ("Base URL", "JIRA_HOST", False),
            ("Account email", "JIRA_EMAIL", False),
            ("API token", "JIRA_TOKEN", True),
            ("Project key (optional)", "JIRA_PROJECT", False),
        ],
        "required": [("JIRA_HOST",), ("JIRA_EMAIL",),
                     ("JIRA_TOKEN", "JIRA_API_TOKEN")],
    },
    "linear": {
        "label": "Linear",
        "fields": [
            ("API key", "LINEAR_API_KEY", True),
            ("Team ID (optional)", "LINEAR_TEAM_ID", False),
        ],
        "required": [("LINEAR_API_KEY",)],
    },
    "trello": {
        "label": "Trello",
        "fields": [
            ("API key", "TRELLO_KEY", True),
            ("Token", "TRELLO_TOKEN", True),
            ("Board ID", "TRELLO_BOARD_ID", False),
        ],
        "required": [("TRELLO_KEY",), ("TRELLO_TOKEN",),
                     ("TRELLO_BOARD_ID",)],
    },
    "outlook": {
        "label": "Outlook Calendar",
        "fields": [("Access token", "OUTLOOK_ACCESS_TOKEN", True)],
        "required": [("OUTLOOK_ACCESS_TOKEN", "MICROSOFT_ACCESS_TOKEN")],
    },
}

_ENV_VALUE_KEYS = {
    key
    for definition in CONNECTIONS.values()
    for _, key, _ in definition["fields"]
}
_PROVIDER_KEY_ENV_NAMES = {
    provider["api_key_env"] for provider in CLOUD_PROVIDERS.values()
} | {CUSTOM_PROVIDER["api_key_env"]}
_ENV_ALIASES = {
    "GMAIL_ACCESS_TOKEN": ("GMAIL_ACCESS_TOKEN", "GOOGLE_ACCESS_TOKEN"),
    "GOOGLE_ACCESS_TOKEN": ("GOOGLE_ACCESS_TOKEN", "CALENDAR_ACCESS_TOKEN"),
    "SLACK_BOT_TOKEN": ("SLACK_BOT_TOKEN", "SLACK_TOKEN"),
    "JIRA_TOKEN": ("JIRA_TOKEN", "JIRA_API_TOKEN"),
    "OUTLOOK_ACCESS_TOKEN": ("OUTLOOK_ACCESS_TOKEN", "MICROSOFT_ACCESS_TOKEN"),
}


def _decode_env_value(raw: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return value if isinstance(value, str) else str(value)


class SettingsStore:
    """Owns validated config overrides and write-only integration credentials."""

    def __init__(self, config: dict, env_path: str | Path):
        self.config = config
        self.env_path = Path(env_path)
        self._lock = threading.RLock()

    def _env_values(self) -> dict[str, str]:
        if not self.env_path.is_file():
            return {}
        values = {}
        for line in self.env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, raw = line.partition("=")
            if separator and name.strip():
                values[name.strip()] = _decode_env_value(raw.strip())
        return values

    def _current_value(self, name: str, env_values: dict[str, str]) -> str:
        return os.environ.get(name) or env_values.get(name, "")

    def snapshot(self) -> dict:
        with self._lock:
            env_values = self._env_values()
            connections = []
            for connection_id, definition in CONNECTIONS.items():
                fields = []
                for label, name, secret in definition["fields"]:
                    aliases = _ENV_ALIASES.get(name, (name,))
                    current = next((self._current_value(alias, env_values)
                                    for alias in aliases
                                    if self._current_value(alias, env_values)), "")
                    fields.append({
                        "name": name,
                        "label": label,
                        "secret": secret,
                        "configured": bool(current),
                        "value": "" if secret else current,
                    })
                configured = all(any(self._current_value(name, env_values)
                                     for name in alternatives)
                                 for alternatives in definition["required"])
                connections.append({
                    "id": connection_id,
                    "label": definition["label"],
                    "configured": configured,
                    "restart_required": bool(definition.get("restart")),
                    "fields": fields,
                })
            return {"config": deepcopy(self.config),
                    "connections": connections}

    def update_config(self, updates: dict[str, Any]) -> dict:
        if not isinstance(updates, dict):
            raise ValueError("config updates must be an object")
        encoded = {}
        normalized = []
        with self._lock:
            for dotted_path, value in updates.items():
                if not isinstance(dotted_path, str) or not dotted_path.strip():
                    raise ValueError("config path must be a non-empty string")
                path = dotted_path.split(".")
                parent, key = self._find_config_leaf(path)
                previous = parent[key]
                self._validate_type(dotted_path, previous, value)
                if (dotted_path.casefold() ==
                    "security.auto_approve_until_level"
                    and (isinstance(value, bool) or not isinstance(value, int)
                         or not 0 <= value <= 4)):
                    raise ValueError(
                        "security.auto_approve_until_level must be between 0 and 4")
                encoded_name = "EV__" + "__".join(part.upper()
                                                   for part in path)
                encoded[encoded_name] = json.dumps(value, ensure_ascii=False)
                normalized.append((parent, key, value))
            self._write_env(encoded)
            for (parent, key, value), (name, raw) in zip(
                    normalized, encoded.items()):
                parent[key] = value
                os.environ[name] = raw
        return self.snapshot()

    def update_credentials(self, updates: dict[str, str]) -> dict:
        if not isinstance(updates, dict):
            raise ValueError("credentials must be an object")
        normalized = {}
        for name, value in updates.items():
            if name not in _ENV_VALUE_KEYS | _PROVIDER_KEY_ENV_NAMES:
                raise ValueError(f"Unsupported connection field: {name}")
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError(f"Invalid value for {name}")
            if len(value) > 8192:
                raise ValueError(f"Value for {name} is too long")
            normalized[name] = value
        with self._lock:
            self._write_env({name: json.dumps(value, ensure_ascii=False)
                             if value else None
                             for name, value in normalized.items()})
            for name, value in normalized.items():
                if value:
                    os.environ[name] = value
                else:
                    os.environ.pop(name, None)
        return self.snapshot()

    def _find_config_leaf(self, path: list[str]) -> tuple[dict, str]:
        current = self.config
        for part in path[:-1]:
            key = next((candidate for candidate in current
                        if candidate.casefold() == part.casefold()), None)
            if key is None or not isinstance(current[key], dict):
                raise ValueError(f"Unknown setting: {'.'.join(path)}")
            current = current[key]
        key = next((candidate for candidate in current
                    if candidate.casefold() == path[-1].casefold()), None)
        if key is None:
            raise ValueError(f"Unknown setting: {'.'.join(path)}")
        return current, key

    @staticmethod
    def _validate_type(path: str, previous: Any, value: Any) -> None:
        valid = True
        if isinstance(previous, bool):
            valid = isinstance(value, bool)
        elif isinstance(previous, int):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(previous, float):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif isinstance(previous, str):
            valid = isinstance(value, str)
        elif isinstance(previous, list):
            valid = isinstance(value, list)
        elif isinstance(previous, dict):
            valid = isinstance(value, dict)
        elif previous is None:
            valid = value is None or isinstance(value, (str, int, float, bool))
        if not valid:
            raise ValueError(f"Wrong value type for {path}")

    def _write_env(self, updates: dict[str, str | None]) -> None:
        existing = (self.env_path.read_text(encoding="utf-8").splitlines()
                    if self.env_path.is_file() else [])
        output = []
        seen = set()
        for line in existing:
            candidate = line.strip()
            if candidate.startswith("export "):
                candidate = candidate[7:].lstrip()
            name, separator, _ = candidate.partition("=")
            if separator and name.strip() in updates:
                key = name.strip()
                if key not in seen and updates[key] is not None:
                    output.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                output.append(line)
        for name, value in updates.items():
            if name not in seen and value is not None:
                output.append(f"{name}={value}")
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.env_path.with_name(self.env_path.name + ".tmp")
        temp_path.write_text("\n".join(output).rstrip() + "\n",
                             encoding="utf-8")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.env_path)
