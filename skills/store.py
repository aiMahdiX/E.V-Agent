"""Skill Store — durable storage for reusable skills (Phase 7).

A *skill* is a reusable, versioned unit of procedural memory: a natural
language goal, optional explicit steps, tags, and the tool sequence observed
when the agent previously completed that goal successfully.

Storage is a single human-readable JSON file (``data/skills.json``) with an
internal write lock, so the web HUD, CLI, and agent threads can share one
instance safely.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class SkillStore:
    def __init__(self, path: str = "data/skills.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._skills: dict[str, dict] = {}
        self._load()

    # -------------------------------------------------------------- #
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
            for skill in raw.get("skills", []):
                if isinstance(skill, dict) and skill.get("id"):
                    self._skills[skill["id"]] = skill
        except (OSError, json.JSONDecodeError, AttributeError):
            # corrupted store: start empty rather than crash the agent
            self._skills = {}

    def _persist(self) -> None:
        payload = {"skills": list(self._skills.values())}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8")
        tmp.replace(self.path)

    # -------------------------------------------------------------- #
    def create(self, name: str, goal: str, steps: list[dict] | None = None,
               notes: str = "", tags: list[str] | None = None,
               success_count: int = 1) -> str:
        """Create a new skill; if the name already exists, bump usage instead
        (no duplicate rows). Returns the skill id."""
        sid = self._slug(name)
        with self._lock:
            existing = self._skills.get(sid)
            if existing is not None:
                existing["success_count"] += success_count
                existing["updated_at"] = time.time()
                self._persist()
                return sid
            skill = {
                "id": sid,
                "name": name,
                "goal": goal,
                "steps": steps or [],
                "notes": notes,
                "tags": tags or [],
                "enabled": True,
                "success_count": success_count,
                "fail_count": 0,
                "usage_count": 0,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._skills[sid] = skill
            self._persist()
        return sid

    def get(self, sid: str) -> dict | None:
        with self._lock:
            skill = self._skills.get(sid)
            return dict(skill) if skill else None

    def list(self, include_disabled: bool = False) -> list[dict]:
        with self._lock:
            items = [dict(s) for s in self._skills.values()]
        if not include_disabled:
            items = [s for s in items if s.get("enabled", True)]
        return sorted(items, key=lambda s: (-int(s.get("success_count", 0)),
                                            int(s.get("usage_count", 0)),
                                            s.get("id", "")))

    def find(self, name: str) -> dict | None:
        return self.get(self._slug(name))

    # -------------------------------------------------------------- #
    def record_usage(self, sid: str, success: bool) -> None:
        with self._lock:
            skill = self._skills.get(sid)
            if skill is None:
                return
            skill["usage_count"] = int(skill.get("usage_count", 0)) + 1
            if success:
                skill["success_count"] = int(skill.get("success_count", 0)) + 1
            else:
                skill["fail_count"] = int(skill.get("fail_count", 0)) + 1
            skill["updated_at"] = time.time()
            self._persist()

    def delete(self, sid: str) -> bool:
        with self._lock:
            if sid not in self._skills:
                return False
            del self._skills[sid]
            self._persist()
        return True

    def set_enabled(self, sid: str, enabled: bool) -> bool:
        with self._lock:
            skill = self._skills.get(sid)
            if skill is None:
                return False
            skill["enabled"] = bool(enabled)
            skill["updated_at"] = time.time()
            self._persist()
        return True

    def count(self) -> int:
        with self._lock:
            return len(self._skills)

    # -------------------------------------------------------------- #
    @staticmethod
    def _slug(name: str) -> str:
        # latin slug + keep persian letters so «باز کردن دوربین» works
        out = []
        for ch in (name or "").strip().casefold():
            if ch.isalnum() or ch in "-_ \u200c":
                out.append(ch)
            else:
                out.append("-")
        slug = "".join(out).strip("-_ ")
        slug = "-".join(p for p in slug.split() if p) or "skill"
        return slug[:80]


class SkillError(Exception):
    pass
