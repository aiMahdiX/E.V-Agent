"""Long-term memory — durable facts and episodic events in SQLite.

Thread-safe: the web UI runs in a background thread and shares this
instance with the CLI, so every statement goes through a lock and the
connection allows cross-thread use.

Episodes get an FTS5 full-text index (with triggers keeping it in sync) and a
deprecated-in-favor-of-semantic semantic-retrieval hook: when a
``SemanticMemory`` is attached (``attach_semantic``), ``search_semantic``
blends neural/hash embeddings with the lexical FTS hits.
"""
from __future__ import annotations

import json
import re
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
        self._conn.execute("""CREATE TABLE IF NOT EXISTS session_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, ts REAL NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL)""")
        self._conn.commit()
        # FTS5 full-text index over episodes (falls back silently to LIKE
        # when the sqlite build lacks FTS5).
        self._fts = False
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts "
                "USING fts5(summary, content='episodes', content_rowid='id')")
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON "
                "episodes BEGIN INSERT INTO episodes_fts(rowid, summary) "
                "VALUES (new.id, new.summary); END")
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON "
                "episodes BEGIN INSERT INTO episodes_fts(episodes_fts, "
                "rowid, summary) VALUES ('delete', old.id, old.summary); END")
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON "
                "episodes BEGIN INSERT INTO episodes_fts(episodes_fts, "
                "rowid, summary) VALUES ('delete', old.id, old.summary); "
                "INSERT INTO episodes_fts(rowid, summary) "
                "VALUES (new.id, new.summary); END")
            self._conn.execute(
                "INSERT INTO episodes_fts(episodes_fts) VALUES('rebuild')")
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS session_messages_fts "
                "USING fts5(content, content='session_messages', "
                "content_rowid='id')")
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS session_messages_ai "
                "AFTER INSERT ON session_messages BEGIN "
                "INSERT INTO session_messages_fts(rowid, content) "
                "VALUES (new.id, new.content); END")
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS session_messages_ad "
                "AFTER DELETE ON session_messages BEGIN "
                "INSERT INTO session_messages_fts(session_messages_fts, "
                "rowid, content) VALUES ('delete', old.id, old.content); END")
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS session_messages_au "
                "AFTER UPDATE ON session_messages BEGIN "
                "INSERT INTO session_messages_fts(session_messages_fts, "
                "rowid, content) VALUES ('delete', old.id, old.content); "
                "INSERT INTO session_messages_fts(rowid, content) "
                "VALUES (new.id, new.content); END")
            self._conn.execute(
                "INSERT INTO session_messages_fts(session_messages_fts) "
                "VALUES('rebuild')")
            self._conn.commit()
            self._fts = True
        except sqlite3.Error:
            self._fts = False
        self._session_fts = self._fts
        self._semantic = None

    def attach_semantic(self, semantic) -> None:
        """Attach a SemanticMemory instance for embedding-based retrieval."""
        self._semantic = semantic

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

    def remember_preference(self, key: str, value: str) -> None:
        self.remember(f"profile:{key}", value)

    def get_profile(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM facts WHERE key LIKE 'profile:%'"
            ).fetchall()
        return {k.replace("profile:", "", 1): v for k, v in rows}

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

    def remember_session_message(self, session_id: str, role: str,
                                 content: str) -> int | None:
        session_id = str(session_id or "cli")[:120]
        role = str(role or "")
        content = str(content or "").strip()
        if role not in ("user", "assistant") or not content:
            return None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO session_messages(session_id, ts, role, content) "
                "VALUES (?, ?, ?, ?)",
                (session_id, time.time(), role, content[:10000]))
            self._conn.commit()
        return cur.lastrowid

    def search_session_messages(self, query: str, session_id: str | None = None,
                                limit: int = 10) -> list[dict]:
        terms = list(dict.fromkeys(
            term for term in re.findall(r"[\w\u0600-\u06ff]+", query.casefold())
            if len(term) > 1))
        limit = max(1, min(int(limit), 50))
        if not terms:
            return []
        session_filter = " AND m.session_id=?" if session_id else ""
        params: list = [" OR ".join(f'"{term}"*' for term in terms)]
        if session_id:
            params.append(str(session_id)[:120])
        params.append(limit)
        if self._session_fts:
            try:
                with self._lock:
                    rows = self._conn.execute(
                        "SELECT m.id, m.session_id, m.ts, m.role, m.content "
                        "FROM session_messages_fts f JOIN session_messages m "
                        "ON m.id=f.rowid WHERE session_messages_fts MATCH ?" +
                        session_filter + " ORDER BY bm25(session_messages_fts) "
                        "LIMIT ?", params).fetchall()
                return [self._session_row(row) for row in rows]
            except sqlite3.Error:
                pass
        clauses = " OR ".join("content LIKE ?" for _ in terms)
        params = [f"%{term}%" for term in terms]
        if session_id:
            params.append(str(session_id)[:120])
        params.append(limit)
        where = f"({clauses})" + (" AND session_id=?" if session_id else "")
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, ts, role, content "
                f"FROM session_messages WHERE {where} "
                "ORDER BY ts DESC LIMIT ?", params).fetchall()
        return [self._session_row(row) for row in rows]

    def delete_session_messages(self, session_id: str) -> int:
        session_id = str(session_id or "")[:120]
        if not session_id:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM session_messages WHERE session_id=?",
                (session_id,))
            self._conn.commit()
        return cur.rowcount

    @staticmethod
    def _session_row(row) -> dict:
        return {"id": row[0], "session_id": row[1], "ts": row[2],
                "role": row[3], "content": row[4]}

    def episodes(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, summary, detail FROM episodes "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "ts": r[1], "summary": r[2],
                 "detail": r[3]} for r in rows]

    def search_events(self, query: str, limit: int = 5) -> list[dict]:
        terms = list(dict.fromkeys(
            term for term in re.findall(r"\w+", query.casefold())
            if len(term) > 1))
        if not terms or limit < 1:
            return []
        # FTS5 path: prefix-match query terms, ranked by bm25.
        if self._fts:
            try:
                match = " OR ".join(f'"{t}"*' for t in terms)
                with self._lock:
                    rows = self._conn.execute(
                        "SELECT e.id, e.ts, e.summary, e.detail "
                        "FROM episodes_fts f JOIN episodes e ON e.id = f.rowid "
                        "WHERE episodes_fts MATCH ? "
                        "ORDER BY bm25(episodes_fts) LIMIT ?",
                        (match, limit * 4)).fetchall()
                if rows:
                    return [{"id": r[0], "ts": r[1], "summary": r[2],
                             "detail": r[3], "score": 1.0}
                            for r in rows[:limit]]
            except sqlite3.Error:
                pass  # fall through to the LIKE scan below
        clauses = " OR ".join("summary LIKE ?" for _ in terms)
        values = [f"%{term}%" for term in terms]
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, summary, detail FROM episodes WHERE "
                f"{clauses} ORDER BY id DESC LIMIT 500", values).fetchall()
        ranked = []
        for row in rows:
            summary = row[2] or ""
            normalized = summary.casefold()
            score = sum(term in normalized for term in terms)
            ranked.append((score, row[0], row))
        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        return [{"id": row[0], "ts": row[1], "summary": row[2],
                 "detail": row[3], "score": score}
                for score, _, row in ranked[:limit]]

    def search_semantic(self, query: str, limit: int = 5,
                        kinds: list[str] | None = None) -> list[str]:
        """Embedding-based retrieval over the attached SemanticMemory.

        Returns display-ready strings (``[kind] text``) for the system prompt.
        Falls back to FTS summaries when no semantic index is attached.
        """
        if self._semantic is None:
            return [f"[episode] {e['summary']}"
                    for e in self.search_events(query, limit=limit)]
        results = self._semantic.search(query, k=limit, kinds=kinds)
        return [f"[{r['kind']}] {r['text']}" for r in results]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
