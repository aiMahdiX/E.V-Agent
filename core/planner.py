"""Intent Engine + lightweight Planner (architecture §4, §5).

Intent classification and step decomposition. For the MVP the powerful
planning happens inside the LLM's ReAct loop; this module provides the
intent signal used to route to the right model and a plain plan formatter.
"""
from __future__ import annotations

import re

INTENTS = ("question", "command", "task", "conversation", "observation",
           "emergency")

_TASK_HINTS = re.compile(
    r"\b(نصب|install|repair|تعمیر|درست کن|دیباگ|debug|fix|setup|پیکربندی|"
    r"configure|deploy|browser|گوش|watch|monitor|do|make|create|build|"
    r"update|پیدا|find|ببند|ببندش|باز کن|باز کنش|بزن|کشتن|کش|بنداز|"
    r"دوربین|وبکم|عکس بگیر|اسکرین|تصویر بگیر|چک کن|لیست کن|بیار|نگاه کن)\b",
    re.I)
_EMERGENCY_HINTS = re.compile(r"\b(crash|خطا|error|danger|فوری|فاجعه)\b", re.I)
_CONV_HINTS = re.compile(
    r"^(سلام|درود|صبح|صبح بخیر|شب بخیر|چه خبر|چطوری|چطوری|حالت|حال|"
    r"خوبم|ممنونم|ممنون|تشکر|بای|خداحافظ|ای.وی|هستیش)\b", re.I)
_QUESTION_HINTS = re.compile(
    r"(\?|؟|چیه|چرا|چطوری|what|why|how|چه|کدام|کجا|هست)", re.I)


def detect_intent(text: str) -> str:
    t = text.strip()
    if _EMERGENCY_HINTS.search(t):
        return "emergency"
    if _TASK_HINTS.search(t):
        return "task"
    if _CONV_HINTS.match(t):
        return "conversation"
    if _QUESTION_HINTS.search(t):
        return "question"
    if len(t) < 6:
        return "conversation"
    return "command"


def detect_complexity(text: str) -> float:
    """Rough 0..1 complexity score used by the model router."""
    score = 0.1
    words = text.split()
    score += min(len(words) / 40.0, 0.4)
    if _TASK_HINTS.search(text):
        score += 0.3
    if re.search(r"\b(دوباره|بعدش|و بعد|then|and then)\b", text, re.I):
        score += 0.2
    return round(min(score, 1.0), 2)


class IntentEngine:
    def detect(self, text: str) -> str:
        return detect_intent(text)


class Planner:
    """Builds a readable multi-step plan; execution is done by the agent."""

    def plan(self, task: str) -> list[str]:
        intent = detect_intent(task)
        steps = [f"1. Understand request ({intent})"]
        # generic scaffolding — the LLM refines this at runtime
        steps += [
            "2. Gather relevant system/tool state",
            "3. Execute smallest verifying step",
            "4. Check result and adjust",
            "5. Confirm and report to user",
        ]
        return steps
