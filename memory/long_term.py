"""Long-term memory — durable facts and episodic events in SQLite.

Thread-safe: the web UI runs in a background thread and shares this
instance with the CLI, so every statement goes through a lock and the
connection allows cross-thread use.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class LongTermMemory:
    def __init__(self, db_path: str = "data/ev.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("""CREATE TABLE IF NOT EXISTS facts (
            key TEXT PRIMARY KEY, value TEXT, updated_at REAL)""")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, summary TEXT, detail TEXT)""")
        self._conn.commit()

    def remember(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO facts(key, value, updated_at) "
                "VALUES (?,?,?)", (key, value, time.time()))
            self._conn.commit()

    def recall(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM facts WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def all_facts(self) -> dict:
        with self._lock:
            return {k: v for k, v in self._conn.execute(
                "SELECT key, value FROM facts")}

    def remember_event(self, summary: str, detail: dict | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO episodes(ts, summary, detail) VALUES (?,?,?)",
                (time.time(), summary,
                 json.dumps(detail or {}, ensure_ascii=False)))
            self._conn.commit()
        return cur.lastrowid

    def episodes(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, summary, detail FROM episodes "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "ts": r[1], "summary": r[2],
                 "detail": r[3]} for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
