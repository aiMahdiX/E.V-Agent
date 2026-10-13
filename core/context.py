"""Context Builder — assemble the prompt before each inference round.

Combines: system persona + relevant memory facts + live system state +
tool catalogue, to keep token usage tight (per architecture §17).
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time

from memory.long_term import LongTermMemory

PERSONA = """You are {name}, a local multimodal OS agent running on the user's
machine. You are helpful, precise and autonomous. Reply in the language used
in the user's current message, while keeping technical terms, commands and
code in English. Detect the response language independently on every turn;
the current message overrides stored profile facts and configured defaults.
You address the user as {user_name}.

You act, you do not just describe. When the user asks to fix or inspect
something, use the available tools (shell, files, processes, services, GPU)
to investigate and then act. You reason step by step, run one tool at a time,
check the result, and continue until the task is done. If a tool fails, try a
sensible next step instead of giving up immediately. If you cannot or should
not do something, say so clearly.

Rules:
- Never invent tool results; only report what the tools actually returned.
- Prefer local tools and the local LLM; go online only when required.
- For privileged/destructive actions the permission system may block you;
  if blocked, explain what would be needed.
- Keep responses concise and in the user's current language, with commands
    kept in English."""


class ContextBuilder:
    """Builds the agent system prompt, caching the static parts and
    throttling the (subprocess-heavy) live system state refresh."""

    _STATE_TTL = 30.0   # seconds before re-running OS probes

    def __init__(self, config: dict, memory: LongTermMemory,
                 tool_names: list[str]):
        self.config = config
        self.memory = memory
        self.tool_names = tool_names
        self._persona = self._build_persona()
        self._lang = config.get("agent", {}).get("language", "auto")
        self._state_cache = ("", 0.0)
        self._skills = None          # optional SkillEngine (Phase 7)

    def attach_skills(self, skill_engine) -> None:
        """Attach the SkillEngine so learned skills appear in the prompt."""
        self._skills = skill_engine

    def _build_persona(self) -> str:
        a = self.config.get("agent", {})
        return PERSONA.format(name=a.get("name", "E.V."),
                              user_name=a.get("user_name", "User"))

    def persona(self) -> str:
        return self._persona

    @staticmethod
    def _run(cmd: list[str]) -> list[str]:
        try:
            return subprocess.run(cmd, capture_output=True,
                                  text=True).stdout.splitlines()
        except OSError:
            return []

    def system_state(self, refresh: bool = False) -> str:
        now = time.time()
        if refresh or now - self._state_cache[1] >= self._STATE_TTL:
            lines = [f"platform: {platform.platform()}"]
            mem = self._run(["free", "-h"])
            if len(mem) > 1:
                lines.append("memory: " + mem[1])
            disk = self._run(["df", "-h", "/"])
            if disk:
                lines.append("disk: " + disk[-1])
            gpu = self._run(["nvidia-smi", "--query-gpu=name,memory.used,"
                             "memory.total,temperature.gpu",
                             "--format=csv,noheader"])
            if gpu and gpu[0].strip():
                lines.append("gpu: " + gpu[0].strip())
            self._state_cache = ("\n".join(lines), now)
        return self._state_cache[0]

    def facts_block(self) -> str:
        facts = self.memory.all_facts()
        if not facts:
            return "(no long-term facts recorded yet)"
        return "\n".join(f"- {k}: {v}" for k, v in facts.items())

    def profile_block(self) -> str:
        if hasattr(self.memory, "get_profile"):
            profile = self.memory.get_profile()
            if profile:
                return "\n".join(f"- {k}: {v}" for k, v in profile.items())
        return "(no user profile recorded yet)"

    def system_prompt(self, user_query: str = "") -> str:
        relevant = self.memory.search_events(user_query, limit=3) \
            if user_query else []
        past_events = ("\n".join(
            f"- {event['summary'][:240]}" for event in relevant)
            if relevant else "(no relevant past events)")

        semantic_memory = []
        if hasattr(self.memory, "search_semantic"):
            semantic_memory = self.memory.search_semantic(user_query or "", limit=3)
        semantic_block = ("\n".join(f"- {item}" for item in semantic_memory)
                          if semantic_memory else "(no relevant semantic memories)")

        body = [
            self._persona,
            "\n# Live system state",
            self.system_state(),
            "\n# Learned skills (reusable plans)",
            (self._skills.context_block(user_query)
             if self._skills is not None
             else "(no skills learned yet)"),
            "\n# Known long-term facts",
            self.facts_block(),
            "\n# User profile (local personalization)",
            self.profile_block(),
            "\n# Relevant past events (local memory)",
            past_events,
            "\n# Relevant semantic memories (local memory)",
            semantic_block,
            "\n# Available tools: " + ", ".join(self.tool_names),
            f"\nConfigured response language: {self._lang}",
            "Always answer in the language used in the current user message. "
            "This rule overrides the configured language and any older profile "
            "or memory preference.",
        ]
        return "\n".join(body)
