"""Local-first briefing shared by the CLI and web HUD."""
from __future__ import annotations

import time
import os


def _mcp_messaging_tasks(mcp) -> list[dict]:
    platforms = []
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        platforms.append("telegram")
    if os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN"):
        platforms.append("slack")
    if os.getenv("DISCORD_BOT_TOKEN"):
        platforms.append("discord")
    messages = []
    for platform in platforms:
        channels_result = mcp.call("messaging_list_channels", {
            "platform": platform, "limit": 3})
        channels_content = (channels_result.get("content") or []) \
            if isinstance(channels_result, dict) else []
        if not channels_content:
            continue
        import json
        channels_payload = json.loads(channels_content[0].get("text", "{}"))
        for channel in (channels_payload.get("channels") or [])[:3]:
            channel_id = channel.get("id")
            if not channel_id and platform != "telegram":
                continue
            result = mcp.call("messaging_recent_messages", {
                "platform": platform, "channel_id": str(channel_id), "limit": 10})
            content = (result.get("content") or []) if isinstance(result, dict) else []
            if content:
                payload = json.loads(content[0].get("text", "{}"))
                messages.extend(payload.get("messages") or [])
    if not messages:
        return []
    result = mcp.call("messaging_extract_tasks", {"messages": messages})
    content = (result.get("content") or []) if isinstance(result, dict) else []
    if not content:
        return []
    import json
    return json.loads(content[0].get("text", "{}")) .get("tasks") or []


def build_brief(tasks=None, system: dict | None = None,
                include_external: bool = True, mcp=None) -> dict:
    """Return a concise local briefing with optional read-only integrations."""
    local_tasks = []
    for task in (tasks or []):
        if getattr(task, "status", "pending") in {"done", "failed"}:
            continue
        due = getattr(task, "next_run_at", None)
        priority = "high" if getattr(task, "due_count", 0) > 0 else "medium"
        local_tasks.append({
            "id": getattr(task, "id", None),
            "title": getattr(task, "description", "Untitled"),
            "source": "local",
            "status": getattr(task, "status", "pending"),
            "priority": priority,
            "due_at": due,
        })
    local_tasks.sort(key=lambda item: (0 if item["priority"] == "high" else 1,
                                      str(item["title"]).lower()))

    external = {}
    if include_external:
        try:
            from tools.integrations import daily_brief
            result = daily_brief()
            if result.get("ok"):
                external = result
        except Exception:  # noqa: BLE001 - briefing must never break the UI
            external = {}

    external_tasks = external.get("tasks") or []
    messaging_tasks = []
    if mcp is not None:
        try:
            messaging_tasks = _mcp_messaging_tasks(mcp)
        except Exception:  # noqa: BLE001 - MCP is optional and read-only
            messaging_tasks = []
    external_tasks = external_tasks + messaging_tasks
    all_tasks = local_tasks + external_tasks
    counts = {level: sum(item.get("priority") == level for item in all_tasks)
              for level in ("urgent", "high", "medium", "low")}
    lines = [f"Local briefing: {len(local_tasks)} local, "
             f"{len(external_tasks)} connected tasks"]
    if system:
        cpu = system.get("cpu")
        ram = (system.get("ram") or {}).get("percent")
        if cpu is not None or ram is not None:
            lines.append("System: " + ", ".join(
                value for value in (f"CPU {cpu:.1f}%" if isinstance(cpu, (int, float)) else None,
                                    f"RAM {ram:.1f}%" if isinstance(ram, (int, float)) else None)
                if value))
    lines.append("Priority: " + ", ".join(
        f"{name} {counts[name]}" for name in ("urgent", "high", "medium", "low")
        if counts[name]))
    if not all_tasks:
        lines.append("Next: no pending tasks")
    else:
        lines.append("Next: " + " | ".join(
            f"[{item.get('priority', 'medium')}] {item.get('title', 'Untitled')}"
            for item in all_tasks[:3]))
    return {
        "ok": True,
        "summary": "\n".join(lines),
        "tasks": all_tasks,
        "local_tasks": local_tasks,
        "external": external,
        "counts": counts,
        "ts": time.time(),
    }
