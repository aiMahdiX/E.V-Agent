"""Reasoning helpers — structured planning prompts and utilities."""
from __future__ import annotations


def plan_prompt(task: str) -> str:
    return (
        f"Break the following request into a numbered sequence of concrete "
        f"steps using the available tools. Output only the numbered list.\n"
        f"TASK: {task}"
    )


def decide_prompt(question: str, evidence: str) -> str:
    return (
        f"Given this evidence, answer the question decisively and briefly.\n"
        f"QUESTION: {question}\nEVIDENCE:\n{evidence}"
    )
