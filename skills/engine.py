"""Skill Engine — the self-improvement loop (Phase 7).

After every agent turn the engine inspects the executed tool transcript:

- **consolidates**: a successful run with >=2 distinct tool calls that has no
  matching skill yet becomes a new skill (goal + observed tool steps);
- **strengthens**: the matching skill's counters update so frequently used
  skills rank first in the context block;
- **contextualizes**: ``context_block()`` injects top-k skills into the system
  prompt, so the model can replay a proven plan instead of re-deriving it;
- **replays**: ``run_skill`` re-executes the stored steps through the tool
  router, with per-step fallback to the LLM when parameters drift.

Everything is best-effort: consolidation failures never break the agent turn.
"""
from __future__ import annotations

import difflib
import json
import re

from skills.store import SkillStore, SkillError


class SkillEngine:
    def __init__(self, store: SkillStore, llm=None, router=None,
                 top_k: int = 5, min_tool_calls: int = 2,
                 match_threshold: float = 0.75):
        self.store = store
        self.llm = llm
        self.router = router
        self.top_k = top_k
        self.min_tool_calls = min_tool_calls
        self.match_threshold = match_threshold

    # -------------------------------------------------------------- #
    # consolidation                                                   #
    # -------------------------------------------------------------- #
    def consolidate(self, user_input: str, final_answer: str,
                    transcript: list) -> dict | None:
        """Turn a successful tool run into (or reinforce) a skill.

        Returns ``{"action": "created"|"reinforced", "id": ...}`` or None.
        Called by Agent.run on every successful tool-using turn.
        """
        steps = self._steps_from_transcript(transcript)
        if len(steps) < self.min_tool_calls:
            return None
        name, goal, tags = self._derive_name_goal_tags(user_input)
        existing = self.find_skill(user_input)
        if existing is not None:
            self.store.record_usage(existing["id"], success=True)
            return {"action": "reinforced", "id": existing["id"]}
        try:
            sid = self.store.create(
                name, goal,
                steps=[{"tool": s["tool"], "args": s["args"]} for s in steps],
                notes=self._notes(final_answer),
                tags=tags)
        except SkillError:
            return None
        return {"action": "created", "id": sid}

    def _steps_from_transcript(self, transcript: list) -> list[dict]:
        steps: list[dict] = []
        for entry in transcript or []:
            if not isinstance(entry, dict) or "tool" not in entry:
                continue
            steps.append({"tool": str(entry.get("tool") or ""),
                          "args": entry.get("args")
                          if isinstance(entry.get("args"), dict) else {}})
        # dedupe consecutive identical tool+args pairs
        deduped: list[dict] = []
        for s in steps:
            if (deduped
                    and deduped[-1]["tool"] == s["tool"]
                    and deduped[-1]["args"] == s["args"]):
                continue
            deduped.append(s)
        return deduped

    def _derive_name_goal_tags(self, user_input: str) -> tuple[str, str, list[str]]:
        user_input = (user_input or "").strip()
        goal = user_input[:200]
        words = re.findall(r"[\w\u0600-\u06ff]{3,}", user_input)
        # drop generic Persian stopwords so names like «وضعیت-gpu-گرفتن» stay readable
        stop = {"این", "that", "را", "رو", "کن", "بده", "بگو", "با", "برای",
                "what", "the", "and", "please", "لطفا", "لطفاً", "می", "به",
                "از", "در", "یک", "دور", "هر"}
        content = [w for w in words if w.casefold() not in stop]
        tags = [w.casefold() for w in content[:4]]
        name_words = content[:4] or words[:4] or ["skill"]
        name = "-".join(name_words)
        return name[:80], goal, tags

    def _notes(self, final_answer: str) -> str:
        return (final_answer or "").strip()[:200]

    # -------------------------------------------------------------- #
    # matching                                                        #
    # -------------------------------------------------------------- #
    def find_skill(self, query: str) -> dict | None:
        """Best skill for a user request, using token overlap + difflib."""
        q = re.findall(r"[\w\u0600-\u06ff]{2,}", (query or "").casefold())
        if not q:
            return None
        best, best_score = None, 0.0
        for skill in self.store.list():
            hay = " ".join([skill.get("name", ""), skill.get("goal", ""),
                            " ".join(skill.get("tags", []))]).casefold()
            h = re.findall(r"[\w\u0600-\u06ff]{2,}", hay)
            if not h:
                continue
            overlap = len(set(q) & set(h)) / len(set(q) | set(h))
            ratio = difflib.SequenceMatcher(None, " ".join(q),
                                            " ".join(h)).ratio()
            score = max(overlap, 0.6 * ratio)
            if score > best_score:
                best, best_score = skill, score
        if best_score < self.match_threshold:
            return None
        return best

    def relevant(self, query: str, k: int | None = None) -> list[dict]:
        """Return relevant skills, falling back to popular skills if unmatched."""
        k = k or self.top_k
        all_skills = self.store.list()
        if not all_skills:
            return []
        ranked: list[tuple[float, dict]] = []
        q = re.findall(r"[\w\u0600-\u06ff]{2,}", (query or "").casefold())
        for skill in all_skills:
            hay = " ".join([skill.get("name", ""), skill.get("goal", ""),
                            " ".join(skill.get("tags", []))]).casefold()
            h = re.findall(r"[\w\u0600-\u06ff]{2,}", hay) if q else []
            if q and h:
                overlap = len(set(q) & set(h)) / len(set(q) | set(h))
                ratio = difflib.SequenceMatcher(None, " ".join(q),
                                                " ".join(h)).ratio()
                score = max(overlap, 0.6 * ratio)
            else:
                score = 0.0
            ranked.append((score, skill))
        ranked.sort(key=lambda item: (-item[0], -item[1].get("success_count", 0)))
        relevant = [s for score, s in ranked if score >= 0.25][:k]
        if relevant:
            return relevant
        return [s for _, s in ranked[:k]]

    # -------------------------------------------------------------- #
    # prompt + replay                                                 #
    # -------------------------------------------------------------- #
    def context_block(self, query: str) -> str:
        skills = self.relevant(query)
        if not skills:
            return "(no skills learned yet)"
        lines = []
        for s in skills:
            goal = (s.get("goal") or "")[:80]
            n = int(s.get("success_count", 0))
            lines.append(f"- {s['name']} (id: {s['id']}, "
                         f"{n} successful runs) — {goal}")
        return "\n".join(lines)

    def run_skill(self, sid: str, user_input: str | None = None) -> dict:
        """Replay a skill: re-run stored steps through the tool router.

        When the current situation differs from when the skill was learned
        (e.g. a file path changed), the LLM adapts each step's arguments using
        the previous step results; the original args are only a starting point.
        """
        skill = self.store.get(sid)
        if skill is None:
            return {"error": f"skill not found: {sid}", "blocked": True}
        if not skill.get("enabled", True):
            return {"error": f"skill disabled: {sid}", "blocked": True}
        steps = skill.get("steps") or []
        if not steps:
            return {"error": f"skill has no steps: {sid}", "blocked": True}
        if self.router is None:
            return {"error": "tool router unavailable for skill replay",
                    "blocked": True}

        results = []
        ok_all = True
        context = {"goal": skill.get("goal", ""),
                   "request": user_input or skill.get("goal", "")}
        for i, step in enumerate(steps):
            tool = step.get("tool", "")
            args = dict(step.get("args") or {})
            args = self._adapt_args(skill, i, args, context)
            result = self.router.dispatch(tool, args)
            failed = self._failed(result)
            results.append({"tool": tool, "args": args, "result": result,
                            "failed": failed})
            context[f"step{i}_result"] = str(result)[:400]
            if failed:
                ok_all = False
                break
        self.store.record_usage(sid, success=ok_all)
        return {"skill": sid, "name": skill.get("name", ""),
                "ok": ok_all, "steps": results}

    def _adapt_args(self, skill: dict, index: int, args: dict,
                    context: dict) -> dict:
        """Ask the LLM to adjust replay args to the current situation."""
        if self.llm is None:
            return args
        try:
            prompt = (
                "You are replaying a saved skill. Adapt this step's arguments "
                "to the current situation; keep them unchanged if no update "
                "is needed. Return only a JSON object.\n"
                f"Skill: {skill.get('name')}\nGoal: {skill.get('goal')}\n"
                f"Step {index + 1}: tool "
                f"{skill['steps'][index].get('tool', '')}\n"
                f"Current arguments: {json.dumps(args, ensure_ascii=False)}\n"
                "Previous context: " + "; ".join(
                    f"{k}={v}" for k, v in context.items()
                    if k.startswith("step") or k in ("request",))[:300] + "\n"
                "Return only the updated JSON arguments."
            )
            resp = self.llm.chat(
                [{"role": "user", "content": prompt}], tools=None)
            content = ((resp.get("message") or {}).get("content") or "").strip()
            m = re.search(r"\{.*\}", content, re.S)
            if m:
                new_args = json.loads(m.group(0))
                if isinstance(new_args, dict):
                    return new_args
        except Exception:  # noqa: BLE001 — replay must never crash the agent
            pass
        return args

    def _failed(self, result) -> bool:
        return isinstance(result, dict) and bool(
            result.get("blocked") is True or result.get("error"))
