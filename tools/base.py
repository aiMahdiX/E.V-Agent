"""Tool base — a declarative Tool descriptor consumed by the Tool Router."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict              # JSON-schema (Ollama tool format)
    fn: Callable[..., Any]
    level: int = 0                # base permission level
    required: list[str] = field(default_factory=list)

    def schema(self) -> dict:
        """Return the Ollama-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    **self.parameters,
                    "required": self.required,
                },
            },
        }
