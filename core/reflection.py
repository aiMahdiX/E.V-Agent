"""Reflection — post-hoc critique used to improve results (architecture §6)."""
from __future__ import annotations

from models.llm import OllamaClient


class Reflector:
    def __init__(self, llm: OllamaClient, model: str | None = None):
        self.llm = llm
        self.model = model

    def critique(self, transcript: str) -> str:
        """Ask the model to review a task transcript and suggest fixes."""
        prompt = (
            "You are a strict reviewer. Below is a transcript of an agent's "
            "task. Identify mistakes, missed verification steps, or unsafe "
            "actions, and give concise corrective advice. Respond in the "
            "language used by the user in the transcript.\n\nTRANSCRIPT:\n"
            + transcript
        )
        return self.llm.generate(prompt, model=self.model)
