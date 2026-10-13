"""Offline smoke tests for the Telegram control gateway."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from security.approval import Approval, approval_context
from ui.telegram import TelegramGateway


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, text, session_id=""):
        self.calls.append((text, session_id))
        return f"received: {text}"


def main() -> int:
    agent = FakeAgent()
    gateway = TelegramGateway(agent, "fake-token", {101}, approval_timeout=1)
    sent = []
    gateway._send_message = lambda chat, text: sent.append((chat, text))
    gateway._process_update({"update_id": 1, "message": {
        "from": {"id": 999}, "chat": {"id": 999, "type": "private"},
        "text": "ignore me"}})
    gateway._process_update({"update_id": 2, "message": {
        "from": {"id": 101}, "chat": {"id": -12, "type": "group"},
        "text": "ignore group"}})
    assert not agent.calls and not sent

    gateway._process_update({"update_id": 3, "message": {
        "from": {"id": 101}, "chat": {"id": 101, "type": "private"},
        "text": "/start"}})
    assert sent and sent[-1][0] == 101

    gateway._process_update({"update_id": 4, "message": {
        "from": {"id": 101}, "chat": {"id": 101, "type": "private"},
        "text": "GPU status?"}})
    deadline = time.monotonic() + 2
    while not agent.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert agent.calls == [("GPU status?", "telegram:101")], agent.calls
    assert "received: GPU status?" in sent[-1][1]
    assert any("Request received" in message for _, message in sent)

    conflict = urllib.error.HTTPError(
        "https://api.telegram.org/redacted", 409, "Conflict", {},
        __import__("io").BytesIO(json.dumps({
            "description": "Conflict: webhook is active"}).encode()))
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", side_effect=conflict):
        error = gateway._api("getUpdates", {})
    assert error.get("error_code") == 409
    assert "webhook is active" in error.get("description", "")

    pending = {}
    approval_thread = threading.Thread(
        target=lambda: pending.setdefault("allowed", gateway._request_approval(
            101, 101, action="shell", level=3)))
    approval_thread.start()
    deadline = time.monotonic() + 2
    code = None
    while time.monotonic() < deadline:
        for _, message in reversed(sent):
            match = re.search(r"/approve ([0-9a-f]{6})", message)
            if match:
                code = match.group(1)
                break
        if code:
            break
        time.sleep(0.01)
    assert code
    gateway._resolve_approval(code, 999, 101, True)
    assert not pending
    gateway._resolve_approval(code, 101, 101, True)
    approval_thread.join(timeout=2)
    assert pending.get("allowed") is True, {
        "pending": pending, "code": code, "sent": sent,
        "thread_alive": approval_thread.is_alive(),
    }

    base_approval = Approval(confirm=False)
    with approval_context(lambda **_: True):
        assert base_approval.ask(3, "danger", {}, 2)
    assert not base_approval.ask(3, "danger", {}, 2)

    with tempfile.TemporaryDirectory() as tmp:
        token_path = Path(tmp) / "must-not-exist"
        assert not token_path.exists()
    print("ALL TELEGRAM SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
