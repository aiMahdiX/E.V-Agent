"""Semantic memory — embeddings + vector search (Phase 6)."""
from __future__ import annotations


class SemanticMemory:
    """Placeholder for embedding-based retrieval.

    Future: store embeddings from a local embedding model (e.g. nomic-embed)
    and do cosine similarity search over long-term facts.
    """

    def __init__(self):
        self._index: list[tuple[str, list[float]]] = []

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Embeddings not implemented (Phase 6)")

    def add(self, text: str) -> None:
        pass

    def search(self, query: str, k: int = 5) -> list[str]:
        return []
