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

PERSONA = """You are {name}, a local multimodal OS agent running on Mahdi's
machine. You are helpful, precise and autonomous. You communicate in Persian
but keep technical terms, commands and code in English. You address the user
as {user_name}.

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
- Keep responses concise and in Persian, with commands kept in English."""


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
        self._lang = config.get("agent", {}).get("language", "Persian")
        self._state_cache = ("", 0.0)

    def _build_persona(self) -> str:
        a = self.config.get("agent", {})
        return PERSONA.format(name=a.get("name", "E.V."),
                              user_name=a.get("user_name", "Mahdi"))

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

    def system_prompt(self) -> str:
        body = [
            self._persona,
            "\n# Live system state",
            self.system_state(),
            "\n# Known long-term facts",
            self.facts_block(),
            "\n# Available tools: " + ", ".join(self.tool_names),
            f"\nPreferred language: {self._lang}",
        ]
        return "\n".join(body)
