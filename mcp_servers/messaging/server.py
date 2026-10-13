#!/usr/bin/env python3
"""Read-only MCP bridge for Telegram, Slack, and Discord.

Credentials are read only from environment variables. The server never sends
messages, edits channels, or persists tokens/data.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request


LIMIT = 20


def env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def http_json(url: str, headers: dict | None = None) -> dict:
    try:
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {exc}"}


def configured(platform: str) -> tuple[str | None, dict]:
    name = platform.lower().strip()
    if name == "telegram":
        token = env("TELEGRAM_BOT_TOKEN")
        return token, {"token": token} if token else {}
    if name == "slack":
        token = env("SLACK_BOT_TOKEN", "SLACK_TOKEN")
        return token, {"token": token} if token else {}
    if name == "discord":
        token = env("DISCORD_BOT_TOKEN")
        return token, {"token": token} if token else {}
    return None, {}


def list_channels(platform: str = "", limit: int = 10, **kwargs) -> dict:
    name = platform.lower().strip()
    token, values = configured(name)
    if not name:
        return {"ok": False, "error": "platform is required: telegram, slack, or discord"}
    if not token:
        return {"ok": False, "error": f"{name} credentials are not configured"}
    size = max(1, min(int(limit), LIMIT))
    if name == "telegram":
        return {"ok": True, "platform": name,
                "channels": [{"id": env("TELEGRAM_CHAT_ID"),
                               "name": "configured Telegram chat"}]}
    if name == "slack":
        data = http_json(f"https://slack.com/api/conversations.list?limit={size}",
                         {"Authorization": f"Bearer {values['token']}"})
        if data.get("ok") is False:
            return {"ok": False, "error": data.get("error", "slack api error")}
        return {"ok": True, "platform": name, "channels": [
            {"id": item.get("id"), "name": item.get("name")}
            for item in (data.get("channels") or [])[:size]]}
    data = http_json("https://discord.com/api/v10/users/@me/guilds",
                     {"Authorization": f"Bot {values['token']}"})
    if not data.get("ok", True) and data.get("error"):
        return data
    return {"ok": True, "platform": name, "channels": [
        {"id": item.get("id"), "name": item.get("name")}
        for item in (data or [])[:size]]}


def recent_messages(platform: str = "", channel_id: str | None = None,
                    limit: int = 10, **kwargs) -> dict:
    name = platform.lower().strip()
    token, values = configured(name)
    if not name:
        return {"ok": False, "error": "platform is required: telegram, slack, or discord"}
    if not token:
        return {"ok": False, "error": f"{name} credentials are not configured"}
    size = max(1, min(int(limit), LIMIT))
    if name == "telegram":
        params = {"limit": size}
        if channel_id:
            params["chat_id"] = channel_id
        data = http_json("https://api.telegram.org/bot%s/getUpdates?%s" %
                         (token, urllib.parse.urlencode(params)))
        if data.get("ok") is False:
            return data
        messages = []
        for item in (data.get("result") or [])[:size]:
            message = item.get("message") or {}
            messages.append({"id": message.get("message_id"),
                             "text": message.get("text") or message.get("caption", ""),
                             "channel_id": (message.get("chat") or {}).get("id")})
        return {"ok": True, "platform": name, "messages": messages}
    if not channel_id:
        return {"ok": False, "error": f"channel_id is required for {name} messages"}
    if name == "slack":
        url = "https://slack.com/api/conversations.history?" + urllib.parse.urlencode(
            {"channel": channel_id, "limit": size})
        data = http_json(url, {"Authorization": f"Bearer {values['token']}"})
        if data.get("ok") is False:
            return {"ok": False, "error": data.get("error", "slack api error")}
        return {"ok": True, "platform": name, "messages": [
            {"id": item.get("ts"), "text": item.get("text", ""),
             "channel_id": channel_id}
            for item in (data.get("messages") or [])[:size]]}
    data = http_json(f"https://discord.com/api/v10/channels/{urllib.parse.quote(channel_id)}/messages?limit={size}",
                     {"Authorization": f"Bot {values['token']}"})
    if data.get("ok") is False and data.get("error"):
        return data
    return {"ok": True, "platform": name, "messages": [
        {"id": item.get("id"), "text": item.get("content", ""),
         "channel_id": channel_id}
        for item in (data or [])[:size]]}


def extract_tasks(messages: list | None = None, **kwargs) -> dict:
    action_terms = ("please", "todo", "task", "follow up", "review", "fix",
                    "بررسی", "انجام", "پیگیری", "ارسال", "اصلاح")
    urgent_terms = ("urgent", "critical", "blocker", "p0", "فوری", "بحرانی")
    tasks = []
    for item in messages or []:
        text = " ".join(str(item.get("text", "")).split())
        lower = text.lower()
        if not text or not any(term in lower for term in action_terms):
            continue
        priority = "urgent" if any(term in lower for term in urgent_terms) else "medium"
        tasks.append({"id": item.get("id"), "title": text[:240],
                      "priority": priority, "channel_id": item.get("channel_id")})
    tasks.sort(key=lambda item: (0 if item["priority"] == "urgent" else 1,
                                 item["title"].lower()))
    return {"ok": True, "tasks": tasks}


def tool_call(name: str, arguments: dict) -> dict:
    if name == "messaging_list_channels":
        return list_channels(**arguments)
    if name == "messaging_recent_messages":
        return recent_messages(**arguments)
    if name == "messaging_extract_tasks":
        return extract_tasks(**arguments)
    return {"ok": False, "error": f"unknown tool {name}"}


def main() -> None:
    tools = [
        {"name": "messaging_list_channels", "description": "List read-only channels for Telegram, Slack, or Discord.",
         "inputSchema": {"type": "object", "properties": {"platform": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["platform"]}},
        {"name": "messaging_recent_messages", "description": "Read recent messages from a Telegram, Slack, or Discord channel.",
         "inputSchema": {"type": "object", "properties": {"platform": {"type": "string"}, "channel_id": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["platform"]}},
        {"name": "messaging_extract_tasks", "description": "Extract and prioritize actionable tasks from message objects without sending anything.",
         "inputSchema": {"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "object"}}}, "required": ["messages"]}},
    ]
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, ident = message.get("method"), message.get("id")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "MessagingReadOnly", "version": "1.0.0"}}
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            params = message.get("params", {})
            output = tool_call(params.get("name", ""), params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}]}
        else:
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
