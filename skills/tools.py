"""Skill tool surface — exposes replayable skills to the LLM + CLI.

Three tools are registered on the native ToolRouter so the model (and the
user, via ``/skills``) can work with learned skills directly:

- ``skill_list``    — list learned skills with usage stats
- ``skill_run``     — replay a skill's stored steps through the tool router
- ``skill_create``  — save an explicit skill from a name + goal + steps

Registration is opt-in at startup (main.py) so tests can build an
orchestrator without a skill engine.
"""
from __future__ import annotations

from typing import Any

from tools.base import Tool


def _skill_list(engine):
    def fn(**_kw) -> Any:
        skills = engine.store.list()
        if not skills:
            return {"ok": True, "skills": [],
                    "message": "No skills have been learned yet."}
        return {"ok": True, "skills": [
            {"id": s["id"], "name": s.get("name", ""),
             "goal": (s.get("goal") or "")[:120],
             "success_count": s.get("success_count", 0),
             "usage_count": s.get("usage_count", 0)}
            for s in skills[:20]]}
    return fn


def _skill_run(engine):
    def fn(**kw) -> Any:
        sid = str(kw.get("id") or kw.get("name") or "").strip()
        if not sid:
            return {"error": "A skill id or name is required",
                    "blocked": True}
        skill = engine.store.get(sid) or engine.store.find(sid)
        if skill is None:
            return {"error": f"Skill not found: {sid}", "blocked": True}
        return engine.run_skill(skill["id"])
    return fn


def _skill_create(engine):
    def fn(**kw) -> Any:
        name = str(kw.get("name") or "").strip()
        goal = str(kw.get("goal") or "").strip()
        if not name or not goal:
            return {"error": "name and goal are required", "blocked": True}
        steps = kw.get("steps")
        if not isinstance(steps, list):
            steps = []
        clean = [{"tool": str(s.get("tool") or ""),
                  "args": s.get("args") if isinstance(s.get("args"), dict)
                  else {}}
                 for s in steps if isinstance(s, dict) and s.get("tool")]
        sid = engine.store.create(
            name, goal, steps=clean,
            notes=str(kw.get("notes") or "")[:200])
        return {"ok": True, "id": sid,
                "message": f"Skill saved: {sid}"}
    return fn


def register(engine) -> None:
    """Register the skill_* tools on the orchestrator's native router."""
    if engine is None:
        return
    native = getattr(engine.router, "native", None)
    if native is None:
        return
    native.register(Tool(
        name="skill_list",
        description="List learned skills — reusable plans the agent has "
                    "memorized from past successful runs.",
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_skill_list(engine)))
    native.register(Tool(
        name="skill_run",
        description="Replay a learned skill by id or name: re-executes its "
                    "stored tool steps in order (with LLM adaptation of "
                    "arguments).",
        parameters={"type": "object", "properties": {
            "id": {"type": "string", "description": "skill id"},
            "name": {"type": "string", "description": "skill name"}},
            "required": []},
        fn=_skill_run(engine)))
    native.register(Tool(
        name="skill_create",
        description="Save a new reusable skill from a name, goal, and "
                    "ordered tool steps (each step: {tool, args}).",
        parameters={"type": "object", "properties": {
            "name": {"type": "string"},
            "goal": {"type": "string"},
            "notes": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "object",
                      "properties": {"tool": {"type": "string"},
                                     "args": {"type": "object"}}}}},
            "required": ["name", "goal"]},
        fn=_skill_create(engine)))
