"""Read-only platform connectors for messaging and productivity apps.

These are intentionally conservative and local-first: they never store
credentials in the repo, and they only expose read patterns that are safe by
default. Each connector returns a structured payload when the corresponding
API token/env-var is configured; otherwise it fails with a clear
"not configured" error instead of crashing.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from tools.base import Tool


def _read_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _http_json(url: str, headers: dict | None = None, timeout: int = 15) -> dict:
    try:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if not body:
                return {"ok": True, "data": {}}
            payload = json.loads(body)
            return {"ok": True, "data": payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {exc}"}


def telegram_get_messages(chat_id: str | None = None, bot_token: str | None = None,
                         limit: int = 5, **kwargs) -> dict:
    token = bot_token or _read_env("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not configured"}
    params = {"limit": max(1, min(int(limit), 20))}
    if chat_id:
        params["chat_id"] = chat_id
    url = "https://api.telegram.org/bot%s/getUpdates?%s" % (
        token, urllib.parse.urlencode(params))
    resp = _http_json(url)
    if not resp["ok"]:
        return resp
    items = resp["data"].get("result") or []
    messages = []
    for item in items[:max(1, min(int(limit), 20))]:
        msg = item.get("message") or {}
        text = msg.get("text") or msg.get("caption") or ""
        chat = (msg.get("chat") or {})
        messages.append({
            "chat_id": chat.get("id"),
            "chat_title": chat.get("title") or chat.get("username"),
            "from": (msg.get("from") or {}).get("username") or (msg.get("from") or {}).get("first_name"),
            "text": text,
            "message_id": msg.get("message_id"),
        })
    return {"ok": True, "count": len(messages), "messages": messages}


def gmail_get_recent_messages(query: str = "", max_results: int = 5,
                             access_token: str | None = None, **kwargs) -> dict:
    token = access_token or _read_env("GMAIL_ACCESS_TOKEN", "GOOGLE_ACCESS_TOKEN")
    if not token:
        return {"ok": False, "error": "GMAIL_ACCESS_TOKEN is not configured"}
    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=%d&q=%s" % (
        max(1, min(int(max_results), 20)), urllib.parse.quote_plus(query or ""))
    headers = {"Authorization": f"Bearer {token}"}
    resp = _http_json(url, headers=headers)
    if not resp["ok"]:
        return resp
    message_ids = (resp["data"].get("messages") or [])[:max(1, min(int(max_results), 20))]
    items = []
    for entry in message_ids:
        msg_id = entry.get("id")
        meta = _http_json(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}?format=metadata&metadataHeaders=From&metadataHeaders=Subject",
            headers=headers,
        )
        if not meta["ok"]:
            items.append({"id": msg_id, "error": meta.get("error")})
            continue
        payload = meta["data"].get("payload") or {}
        headers_list = payload.get("headers") or []
        sender = next((h.get("value") for h in headers_list if h.get("name", "").lower() == "from"), "")
        subject = next((h.get("value") for h in headers_list if h.get("name", "").lower() == "subject"), "")
        items.append({"id": msg_id, "from": sender, "subject": subject})
    return {"ok": True, "count": len(items), "messages": items}


def google_calendar_list_events(calendar_id: str = "primary", max_results: int = 10,
                               access_token: str | None = None, **kwargs) -> dict:
    token = access_token or _read_env("GOOGLE_ACCESS_TOKEN", "CALENDAR_ACCESS_TOKEN")
    if not token:
        return {"ok": False, "error": "GOOGLE_ACCESS_TOKEN is not configured"}
    encoded_id = urllib.parse.quote_plus(calendar_id or "primary")
    url = (
        f"https://www.googleapis.com/calendar/v3/calendars/{encoded_id}/events"
        f"?maxResults={max(1, min(int(max_results), 20))}&singleEvents=true&orderBy=startTime"
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = _http_json(url, headers=headers)
    if not resp["ok"]:
        return resp
    items = []
    for event in (resp["data"].get("items") or [])[:max(1, min(int(max_results), 20))]:
        start = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date") or ""
        end = (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date") or ""
        items.append({
            "id": event.get("id"),
            "summary": event.get("summary") or "(no title)",
            "start": start,
            "end": end,
            "location": event.get("location"),
            "status": event.get("status"),
        })
    return {"ok": True, "count": len(items), "events": items}


def notion_list_pages(database_id: str | None = None, notion_token: str | None = None,
                     page_size: int = 5, **kwargs) -> dict:
    token = notion_token or _read_env("NOTION_API_KEY")
    db_id = database_id or _read_env("NOTION_DATABASE_ID")
    if not token:
        return {"ok": False, "error": "NOTION_API_KEY is not configured"}
    if not db_id:
        return {"ok": False, "error": "NOTION_DATABASE_ID is not configured"}
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {"page_size": max(1, min(int(page_size), 20))}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {exc}"}
    entries = []
    for item in (data.get("results") or [])[:max(1, min(int(page_size), 20))]:
        props = item.get("properties") or {}
        title = ""
        for key, val in props.items():
            if isinstance(val, dict) and val.get("type") == "title":
                title = "".join(p.get("plain_text", "") for p in val.get("title", []))
                break
        entries.append({"id": item.get("id"), "title": title or "Untitled"})
    return {"ok": True, "count": len(entries), "pages": entries}


def slack_get_channels(limit: int = 10, token: str | None = None, **kwargs) -> dict:
    auth_token = token or _read_env("SLACK_BOT_TOKEN", "SLACK_TOKEN")
    if not auth_token:
        return {"ok": False, "error": "SLACK_BOT_TOKEN/SLACK_TOKEN is not configured"}
    url = "https://slack.com/api/conversations.list?limit=%d" % max(1, min(int(limit), 50))
    headers = {"Authorization": f"Bearer {auth_token}"}
    resp = _http_json(url, headers=headers)
    if not resp["ok"]:
        return resp
    data = resp["data"]
    if data.get("ok") is False:
        return {"ok": False, "error": data.get("error", "slack api error")}
    channels = []
    for ch in (data.get("channels") or [])[:max(1, min(int(limit), 50))]:
        channels.append({"id": ch.get("id"), "name": ch.get("name"), "purpose": (ch.get("purpose") or {}).get("value")})
    return {"ok": True, "count": len(channels), "channels": channels}


def github_list_repos(owner: str | None = None, token: str | None = None, **kwargs) -> dict:
    auth_token = token or _read_env("GITHUB_TOKEN")
    repo_owner = owner or _read_env("GITHUB_OWNER")
    if not auth_token:
        return {"ok": False, "error": "GITHUB_TOKEN is not configured"}
    if not repo_owner:
        return {"ok": False, "error": "GITHUB_OWNER is not configured"}
    url = f"https://api.github.com/users/{repo_owner}/repos?per_page=5"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = _http_json(url, headers=headers)
    if not resp["ok"]:
        return resp
    repos = [{"name": r.get("name"), "description": r.get("description"), "html_url": r.get("html_url")} for r in (resp["data"] or [])[:5]]
    return {"ok": True, "count": len(repos), "repositories": repos}


def github_triage_tasks(owner: str | None = None, repo: str | None = None,
                      token: str | None = None, limit: int = 10, **kwargs) -> dict:
    auth_token = token or _read_env("GITHUB_TOKEN")
    repo_owner = owner or _read_env("GITHUB_OWNER")
    repo_name = repo or _read_env("GITHUB_REPO")
    if not auth_token:
        return {"ok": False, "error": "GITHUB_TOKEN is not configured"}
    if not repo_owner:
        return {"ok": False, "error": "GITHUB_OWNER is not configured"}
    if not repo_name:
        return {"ok": False, "error": "GITHUB_REPO is not configured"}
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    issues_url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues"
        f"?state=all&per_page={max(1, min(int(limit), 20))}"
    )
    issues_resp = _http_json(issues_url, headers=headers)
    if not issues_resp["ok"]:
        return issues_resp
    items = []
    for issue in (issues_resp["data"] or [])[:max(1, min(int(limit), 20))]:
        if "pull_request" in issue:
            continue
        items.append({
            "id": issue.get("number"),
            "title": issue.get("title"),
            "state": issue.get("state"),
            "labels": [label.get("name") for label in (issue.get("labels") or [])],
            "assignee": (issue.get("assignee") or {}).get("login"),
            "html_url": issue.get("html_url"),
            "created_at": issue.get("created_at"),
        })
    open_items = [it for it in items if it["state"] == "open"]
    closed_items = [it for it in items if it["state"] == "closed"]
    summary = {
        "total": len(items),
        "open": len(open_items),
        "closed": len(closed_items),
        "priority": "low",
    }
    if open_items:
        summary["priority"] = "medium" if len(open_items) < 5 else "high"
    if any(label.lower() in {"urgent", "p0", "critical", "bug"} for it in items for label in (it.get("labels") or [])):
        summary["priority"] = "high"
    return {"ok": True, "repository": f"{repo_owner}/{repo_name}", "summary": summary, "tasks": items}


def discord_get_channels(token: str | None = None, limit: int = 10, **kwargs) -> dict:
    auth_token = token or _read_env("DISCORD_BOT_TOKEN")
    if not auth_token:
        return {"ok": False, "error": "DISCORD_BOT_TOKEN is not configured"}
    url = "https://discord.com/api/v10/users/@me/guilds"
    headers = {"Authorization": f"Bot {auth_token}"}
    resp = _http_json(url, headers=headers)
    if not resp["ok"]:
        return resp
    guilds = []
    for guild in (resp["data"] or [])[:max(1, min(int(limit), 20))]:
        guilds.append({"id": guild.get("id"), "name": guild.get("name")})
    return {"ok": True, "count": len(guilds), "guilds": guilds}


def jira_get_issues(host: str | None = None, email: str | None = None,
                   token: str | None = None, project: str | None = None,
                   limit: int = 10, **kwargs) -> dict:
    jira_host = host or _read_env("JIRA_HOST")
    jira_email = email or _read_env("JIRA_EMAIL")
    jira_token = token or _read_env("JIRA_TOKEN", "JIRA_API_TOKEN")
    if not jira_host:
        return {"ok": False, "error": "JIRA_HOST is not configured"}
    if not jira_email or not jira_token:
        return {"ok": False, "error": "JIRA_EMAIL/JIRA_TOKEN are not configured"}
    query = f"project={project or _read_env('JIRA_PROJECT', '')}"
    if project is None and not _read_env("JIRA_PROJECT"):
        query = ""
    url = f"{jira_host.rstrip('/')}/rest/api/2/search?maxResults={max(1, min(int(limit), 20))}"
    if query:
        url = f"{url}&jql={urllib.parse.quote_plus(query)}"
    auth = urllib.request.HTTPBasicAuthHandler()
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, jira_host, jira_email, jira_token)
        opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(password_mgr))
        with opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {exc}"}
    issues = []
    for issue in (data.get("issues") or [])[:max(1, min(int(limit), 20))]:
        fields = issue.get("fields") or {}
        issues.append({
            "id": issue.get("key"),
            "summary": fields.get("summary"),
            "status": (fields.get("status") or {}).get("name"),
            "priority": (fields.get("priority") or {}).get("name"),
            "assignee": ((fields.get("assignee") or {}).get("displayName") if fields.get("assignee") else None),
        })
    return {"ok": True, "count": len(issues), "issues": issues}


def linear_get_issues(api_key: str | None = None, team_id: str | None = None,
                     limit: int = 10, **kwargs) -> dict:
    key = api_key or _read_env("LINEAR_API_KEY")
    if not key:
        return {"ok": False, "error": "LINEAR_API_KEY is not configured"}
    query = '{ issues(first: %d, filter: { team: { id: { eq: "%s" } } }) { nodes { identifier title state { name } priorityLabel assignee { name } } } }' % (
        max(1, min(int(limit), 20)), team_id or _read_env("LINEAR_TEAM_ID", ""))
    if not (team_id or _read_env("LINEAR_TEAM_ID")):
        query = '{ issues(first: %d) { nodes { identifier title state { name } priorityLabel assignee { name } } } }' % max(1, min(int(limit), 20))
    headers = {"Authorization": key, "Content-Type": "application/json"}
    req = urllib.request.Request(
        "https://api.linear.app/graphql",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {exc}"}
    issues = []
    for item in ((data.get("data") or {}).get("issues") or {}).get("nodes", [])[:max(1, min(int(limit), 20))]:
        issues.append({
            "id": item.get("identifier"),
            "title": item.get("title"),
            "status": (item.get("state") or {}).get("name"),
            "priority": item.get("priorityLabel"),
            "assignee": ((item.get("assignee") or {}).get("name")) if item.get("assignee") else None,
        })
    return {"ok": True, "count": len(issues), "issues": issues}


def trello_get_cards(board_id: str | None = None, key: str | None = None,
                    token: str | None = None, limit: int = 10, **kwargs) -> dict:
    trello_key = key or _read_env("TRELLO_KEY")
    trello_token = token or _read_env("TRELLO_TOKEN")
    if not trello_key or not trello_token:
        return {"ok": False, "error": "TRELLO_KEY/TRELLO_TOKEN are not configured"}
    board = board_id or _read_env("TRELLO_BOARD_ID")
    if not board:
        return {"ok": False, "error": "TRELLO_BOARD_ID is not configured"}
    url = (
        f"https://api.trello.com/1/boards/{board}/cards?key={trello_key}&token={trello_token}"
        f"&limit={max(1, min(int(limit), 20))}"
    )
    resp = _http_json(url)
    if not resp["ok"]:
        return resp
    cards = []
    for card in (resp["data"] or [])[:max(1, min(int(limit), 20))]:
        cards.append({
            "id": card.get("id"),
            "name": card.get("name"),
            "url": card.get("url"),
            "list_id": card.get("idList"),
        })
    return {"ok": True, "count": len(cards), "cards": cards}


def outlook_calendar_events(calendar_id: str = "primary", max_results: int = 10,
                           access_token: str | None = None, **kwargs) -> dict:
    token = access_token or _read_env("OUTLOOK_ACCESS_TOKEN", "MICROSOFT_ACCESS_TOKEN")
    if not token:
        return {"ok": False, "error": "OUTLOOK_ACCESS_TOKEN is not configured"}
    url = (
        f"https://graph.microsoft.com/v1.0/me/calendars/{urllib.parse.quote_plus(calendar_id)}/events"
        f"?$top={max(1, min(int(max_results), 20))}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = _http_json(url, headers=headers)
    if not resp["ok"]:
        return resp
    items = []
    for event in (resp["data"].get("value") or [])[:max(1, min(int(max_results), 20))]:
        items.append({
            "id": event.get("id"),
            "subject": event.get("subject"),
            "start": (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date"),
            "end": (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date"),
            "location": ((event.get("location") or {}).get("displayName")) if event.get("location") else None,
        })
    return {"ok": True, "count": len(items), "events": items}


_PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
_URGENT_TERMS = {"urgent", "critical", "blocker", "p0", "emergency", "فوری", "بحرانی"}
_HIGH_TERMS = {"high", "important", "bug", "p1", "asap", "deadline", "مهم", "باگ"}
_ACTION_TERMS = {
    "action", "please", "review", "fix", "follow up", "follow-up", "reply",
    "send", "update", "prepare", "check", "call", "مراجعه", "بررسی", "انجام",
    "پیگیری", "ارسال", "اصلاح",
}


def _priority_for(text: str, explicit: str | None = None) -> str:
    value = (explicit or "").strip().lower()
    if value in _PRIORITY_ORDER:
        return value
    words = f"{text} {value}".lower()
    if any(term in words for term in _URGENT_TERMS):
        return "urgent"
    if any(term in words for term in _HIGH_TERMS):
        return "high"
    return "medium" if any(term in words for term in _ACTION_TERMS) else "low"


def _task_item(source: str, item_id: str | int | None, title: str,
               priority: str | None = None, url: str | None = None,
               actionable: bool = True) -> dict:
    clean_title = " ".join(str(title or "Untitled").split())
    return {
        "id": str(item_id) if item_id is not None else None,
        "source": source,
        "title": clean_title,
        "priority": _priority_for(clean_title, priority),
        "actionable": bool(actionable),
        "url": url,
    }


def extract_tasks(sections: dict) -> list[dict]:
    """Extract actionable work items from structured integration results.

    This is deliberately deterministic: no external model call, no mutation,
    and identical inputs always produce the same priority-ordered output.
    """
    tasks: list[dict] = []
    for issue in (sections.get("github", {}).get("tasks") or []):
        if str(issue.get("state", "")).lower() == "closed":
            continue
        labels = " ".join(str(label) for label in (issue.get("labels") or []))
        tasks.append(_task_item("github", issue.get("id"), issue.get("title"),
                                labels, issue.get("html_url")))

    for issue in (sections.get("jira", {}).get("issues") or []):
        status = str(issue.get("status") or "").lower()
        if status in {"done", "closed", "resolved"}:
            continue
        tasks.append(_task_item("jira", issue.get("id"), issue.get("summary"),
                                issue.get("priority")))

    for issue in (sections.get("linear", {}).get("issues") or []):
        status = str(issue.get("status") or "").lower()
        if status in {"done", "completed", "canceled", "cancelled"}:
            continue
        tasks.append(_task_item("linear", issue.get("id"), issue.get("title"),
                                issue.get("priority")))

    for card in (sections.get("trello", {}).get("cards") or []):
        tasks.append(_task_item("trello", card.get("id"), card.get("name"),
                                url=card.get("url")))

    for message in (sections.get("gmail", {}).get("messages") or []):
        subject = str(message.get("subject") or "").strip()
        actionable = any(term in subject.lower() for term in _ACTION_TERMS)
        if subject and actionable:
            tasks.append(_task_item("gmail", message.get("id"), subject,
                                    url=message.get("url"), actionable=True))

    for page in (sections.get("notion", {}).get("pages") or []):
        title = str(page.get("title") or "").strip()
        if title:
            tasks.append(_task_item("notion", page.get("id"), title,
                                    url=page.get("url"), actionable=True))

    unique: dict[tuple[str, str], dict] = {}
    for task in tasks:
        unique[(task["source"], task["title"].lower())] = task
    return sorted(unique.values(), key=lambda item: (
        _PRIORITY_ORDER[item["priority"]], item["source"], item["title"].lower()))


def daily_brief(days: int = 1, include: list[str] | None = None, **kwargs) -> dict:
    """Build a read-only, low-noise daily brief from available productivity services.

    The function never writes to any external system; it simply concatenates
    whatever safe, configured integrations are available and returns a concise
    summary tailored for a morning briefing.
    """
    configured: list[str] = []
    sections: dict[str, dict] = {}
    wants = set((include or ["calendar", "gmail", "github", "notion"]))

    token = _read_env("GOOGLE_ACCESS_TOKEN", "CALENDAR_ACCESS_TOKEN")
    if token and "calendar" in wants:
        calendar = google_calendar_list_events(max_results=5, access_token=token)
        configured.append("calendar")
        sections["calendar"] = calendar

    gmail_token = _read_env("GMAIL_ACCESS_TOKEN", "GOOGLE_ACCESS_TOKEN")
    if gmail_token and "gmail" in wants:
        gmail = gmail_get_recent_messages(max_results=5, access_token=gmail_token)
        configured.append("gmail")
        sections["gmail"] = gmail

    gh_token = _read_env("GITHUB_TOKEN")
    gh_owner = _read_env("GITHUB_OWNER")
    gh_repo = _read_env("GITHUB_REPO")
    if gh_token and gh_owner and gh_repo and "github" in wants:
        github = github_triage_tasks(owner=gh_owner, repo=gh_repo, token=gh_token, limit=5)
        configured.append("github")
        sections["github"] = github

    notion_token = _read_env("NOTION_API_KEY")
    notion_db = _read_env("NOTION_DATABASE_ID")
    if notion_token and notion_db and "notion" in wants:
        notion = notion_list_pages(database_id=notion_db, notion_token=notion_token, page_size=5)
        configured.append("notion")
        sections["notion"] = notion

    if not configured:
        return {"ok": False, "error": "No configured productivity integrations for a daily brief"}

    summary_lines = [f"Daily brief ({len(configured)} sources active):"]

    if "calendar" in sections:
        events = sections["calendar"].get("events") or []
        upcoming = [e.get("summary") or "Untitled" for e in events[:3]]
        summary_lines.append(f"- Upcoming: {', '.join(upcoming) if upcoming else 'No events'}")

    if "gmail" in sections:
        msgs = sections["gmail"].get("messages") or []
        if msgs:
            summary_lines.append(f"- Emails: {len(msgs)} recent messages")
        else:
            summary_lines.append("- Emails: no recent messages")

    if "github" in sections:
        gh = sections["github"]
        if gh.get("ok"):
            summary = gh.get("summary") or {}
            summary_lines.append(f"- GitHub: {summary.get('open', 0)} open issues")

    if "notion" in sections:
        pages = sections["notion"].get("pages") or []
        summary_lines.append(f"- Notion: {len(pages)} recent pages")

    tasks = extract_tasks(sections)
    if tasks:
        counts = {level: sum(item["priority"] == level for item in tasks)
                  for level in _PRIORITY_ORDER}
        summary_lines.append(
            "- Tasks: %d actionable (%d urgent, %d high, %d medium)" %
            (len(tasks), counts["urgent"], counts["high"], counts["medium"]))

    return {
        "ok": True,
        "sources": configured,
        "days": max(1, int(days)),
        "summary": "\n".join(summary_lines),
        "sections": sections,
        "tasks": tasks,
    }


INTEGRATION_TOOLS = [
    Tool("telegram_get_messages", "Read recent Telegram messages from the configured bot.",
         {"type": "object", "properties": {
             "chat_id": {"type": "string"},
             "limit": {"type": "integer", "default": 5},
         }},
         fn=telegram_get_messages,
         required=["chat_id"]),
    Tool("gmail_get_recent_messages", "Read recent Gmail messages via OAuth bearer token.",
         {"type": "object", "properties": {
             "query": {"type": "string"},
             "max_results": {"type": "integer", "default": 5},
         }}, fn=gmail_get_recent_messages),
    Tool("google_calendar_list_events", "List upcoming calendar events from the configured Google Calendar.",
         {"type": "object", "properties": {
             "calendar_id": {"type": "string", "default": "primary"},
             "max_results": {"type": "integer", "default": 10},
         }}, fn=google_calendar_list_events),
    Tool("notion_list_pages", "List pages in a configured Notion database.",
         {"type": "object", "properties": {
             "database_id": {"type": "string"},
             "page_size": {"type": "integer", "default": 5},
         }}, fn=notion_list_pages),
    Tool("slack_get_channels", "List recent Slack channels available to the configured bot.",
         {"type": "object", "properties": {"limit": {"type": "integer", "default": 10}}},
         fn=slack_get_channels),
    Tool("github_list_repos", "List the latest public/private repos for a configured GitHub owner.",
         {"type": "object", "properties": {
             "owner": {"type": "string"},
         }}, fn=github_list_repos),
    Tool("github_triage_tasks", "Read the latest GitHub issues for a repo and summarize them by priority.",
         {"type": "object", "properties": {
             "owner": {"type": "string"},
             "repo": {"type": "string"},
             "limit": {"type": "integer", "default": 10},
         }}, fn=github_triage_tasks),
    Tool("discord_get_channels", "List Discord guilds available to the configured bot.",
         {"type": "object", "properties": {"limit": {"type": "integer", "default": 10}}},
         fn=discord_get_channels),
    Tool("jira_get_issues", "List latest Jira issues for the configured project and host.",
         {"type": "object", "properties": {
             "host": {"type": "string"},
             "project": {"type": "string"},
             "limit": {"type": "integer", "default": 10},
         }}, fn=jira_get_issues),
    Tool("linear_get_issues", "List latest Linear issues for the configured team.",
         {"type": "object", "properties": {
             "team_id": {"type": "string"},
             "limit": {"type": "integer", "default": 10},
         }}, fn=linear_get_issues),
    Tool("trello_get_cards", "List cards on a configured Trello board.",
         {"type": "object", "properties": {
             "board_id": {"type": "string"},
             "limit": {"type": "integer", "default": 10},
         }}, fn=trello_get_cards),
    Tool("outlook_calendar_events", "List upcoming Outlook calendar events from the configured Microsoft account.",
         {"type": "object", "properties": {
             "calendar_id": {"type": "string", "default": "primary"},
             "max_results": {"type": "integer", "default": 10},
         }}, fn=outlook_calendar_events),
    Tool("daily_brief", "Assemble a read-only daily summary from any configured productivity services.",
         {"type": "object", "properties": {
             "days": {"type": "integer", "default": 1},
             "include": {"type": "array", "items": {"type": "string"}, "default": ["calendar", "gmail", "github", "notion"]},
         }}, fn=daily_brief),
    Tool("extract_tasks", "Extract and prioritize actionable tasks from integration results.",
         {"type": "object", "properties": {
             "sections": {"type": "object"},
         }, "required": ["sections"]}, fn=lambda sections, **kwargs: {
             "ok": True, "tasks": extract_tasks(sections),
         }),
]
