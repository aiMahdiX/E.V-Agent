"""Episodic memory — past actions/events (Phase 6 enhancer)."""
from __future__ import annotations

from memory.long_term import LongTermMemory


class EpisodicMemory:
    def __init__(self, base: LongTermMemory):
        self.base = base

    def record(self, summary: str, detail: dict | None = None) -> int:
        return self.base.remember_event(summary, detail)

    def query(self, limit: int = 50) -> list[dict]:
        return self.base.episodes(limit)
