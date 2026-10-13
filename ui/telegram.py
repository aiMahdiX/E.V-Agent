"""Private Telegram polling gateway for remote E.V. control.

The bot token and allowed Telegram user IDs are supplied through environment
variables. Unauthorized users and non-private chats are ignored.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import urllib.error
import urllib.request

from security.approval import approval_context

_LOG = logging.getLogger("ev.telegram")


class TelegramGateway:
    def __init__(self, agent, token: str, allowed_user_ids: set[int],
                 poll_timeout: int = 20, approval_timeout: int = 120):
        if not token.strip():
            raise ValueError("Telegram bot token is required")
        if not allowed_user_ids:
            raise ValueError("At least one Telegram user ID must be allowed")
        self.agent = agent
        self._token = token.strip()
        self.allowed_user_ids = set(allowed_user_ids)
        self.poll_timeout = max(1, min(int(poll_timeout), 45))
        self.approval_timeout = max(10, min(int(approval_timeout), 300))
        self._stop = threading.Event()
        self._agent_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._thread: threading.Thread | None = None
        self._last_poll_error = ""

    @classmethod
    def from_environment(cls, agent):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        raw_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        user_ids = set()
        for value in raw_ids.split(","):
            value = value.strip()
            if value:
                try:
                    user_ids.add(int(value))
                except ValueError:
                    continue
        if not token or not user_ids:
            return None
        return cls(agent, token, user_ids)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._poll, name="ev-telegram",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.poll_timeout + 2)

    def _api(self, method: str, payload: dict) -> dict:
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.poll_timeout + 5) as response:
                result = json.loads(response.read().decode("utf-8"))
            return result if isinstance(result, dict) else {"ok": False}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", errors="replace"))
                description = str(body.get("description") or exc.reason)
            except (ValueError, AttributeError):
                description = str(exc.reason)
            return {"ok": False, "error_code": exc.code,
                    "description": description[:300]}
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return {"ok": False, "description": str(exc)[:300]}

    def _poll(self) -> None:
        offset = 0
        while not self._stop.is_set():
            result = self._api("getUpdates", {
                "offset": offset, "timeout": self.poll_timeout,
                "allowed_updates": ["message"],
            })
            if not result.get("ok"):
                error = str(result.get("description") or "Telegram API request failed")
                if error != self._last_poll_error:
                    _LOG.error("Telegram polling failed: %s", error)
                    self._last_poll_error = error
                self._stop.wait(3)
                continue
            if self._last_poll_error:
                _LOG.info("Telegram polling recovered")
                self._last_poll_error = ""
            for update in result.get("result", []):
                if not isinstance(update, dict):
                    continue
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                self._process_update(update)

    def _process_update(self, update: dict) -> None:
        message = update.get("message") or {}
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        try:
            user_id = int(sender.get("id"))
        except (TypeError, ValueError):
            return
        if user_id not in self.allowed_user_ids or chat.get("type") != "private":
            return
        chat_id = chat.get("id")
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if text.startswith("/start") or text.startswith("/help"):
            self._send_message(chat_id,
                               "E.V. is connected. Send a request. "
                               "For sensitive actions, reply with "
                               "/approve <code> or /deny <code>.")
            return
        if text.startswith("/approve "):
            self._resolve_approval(text.split(maxsplit=1)[1], user_id,
                                   chat_id, True)
            return
        if text.startswith("/deny "):
            self._resolve_approval(text.split(maxsplit=1)[1], user_id,
                                   chat_id, False)
            return
        if text.startswith("/"):
            self._send_message(chat_id, "Unknown command. Send /help for commands.")
            return
        threading.Thread(target=self._run_message,
                         args=(chat_id, user_id, text),
                         name="ev-telegram-request", daemon=True).start()

    def _run_message(self, chat_id: int, user_id: int, text: str) -> None:
        try:
            self._send_message(chat_id, "Request received. Working on it…")
            with self._agent_lock:
                approval = lambda **details: self._request_approval(
                    chat_id, user_id, **details)
                with approval_context(approval):
                    answer = self.agent.run(
                        text, session_id=f"telegram:{user_id}")
            self._send_message(chat_id, str(answer or "(No response received)"))
        except Exception:
            _LOG.exception("Telegram agent request failed for user_id=%s", user_id)
            self._send_message(chat_id, "Request failed. Check the local logs.")

    def _request_approval(self, chat_id: int, user_id: int, **details) -> bool:
        code = secrets.token_hex(3)
        pending = {"event": threading.Event(), "user_id": user_id,
                   "chat_id": chat_id, "decision": False}
        with self._pending_lock:
            self._pending[code] = pending
        action = str(details.get("action", "sensitive action"))[:100]
        level = details.get("level", "?")
        self._send_message(
            chat_id, f"Approval required: {action} (level {level}). "
            f"Approve: /approve {code} | deny: /deny {code}")
        try:
            pending["event"].wait(self.approval_timeout)
            return bool(pending["decision"])
        finally:
            with self._pending_lock:
                self._pending.pop(code, None)

    def _resolve_approval(self, code: str, user_id: int, chat_id: int,
                          decision: bool) -> None:
        with self._pending_lock:
            pending = self._pending.get(code.strip())
            if (pending is None or pending["user_id"] != user_id
                    or pending["chat_id"] != chat_id):
                self._send_message(chat_id, "Approval code is invalid or expired.")
                return
            pending["decision"] = decision
            pending["event"].set()
        self._send_message(chat_id, "Approved." if decision else "Action denied.")

    def _send_message(self, chat_id: int, text: str) -> None:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
        for chunk in chunks:
            result = self._api("sendMessage", {"chat_id": chat_id, "text": chunk})
            if not result.get("ok"):
                _LOG.error("Telegram sendMessage failed: %s",
                           result.get("description", "unknown error"))
