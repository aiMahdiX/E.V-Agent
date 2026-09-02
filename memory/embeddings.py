"""Embeddings helper (Phase 6 placeholder)."""
from __future__ import annotations


class Embedder:
    def __init__(self, model: str = "nomic-embed-text"):
        self.model = model

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Embedder not implemented (Phase 6)")
