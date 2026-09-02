"""Short-term memory — rolling window of recent conversation turns."""
from __future__ import annotations

from collections import deque


class ShortTermMemory:
    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self.messages: deque[dict] = deque(maxlen=max_messages)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def add_message(self, msg: dict) -> None:
        self.messages.append(msg)

    def to_list(self) -> list[dict]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()

    def recent(self, n: int | None = None) -> list[dict]:
        msgs = list(self.messages)
        return msgs[-n:] if n else msgs
