"""Semantic memory — local embedding index over facts, episodes, and skills.

Dependency-free and on-device: vectors come from ``memory.embeddings.Embedder``
(hash n-gram always; true neural embeddings automatically when a local Ollama
embedding model such as ``nomic-embed-text`` is available). Retrieval blends
cosine similarity with a TF-IDF lexical score, which keeps exact-keyword hits
(filenames, command names) precise while still matching paraphrases.

Entries are labeled (``fact`` / ``episode`` / ``skill`` / ``note``) so the
caller can show the source of a remembered item.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import Counter

from memory.embeddings import Embedder

_WORD_RE = re.compile(r"[\w\u0600-\u06ff]+")


class SemanticMemory:
    def __init__(self, embedder: Embedder | None = None):
        self._index: list[dict] = []
        self._lock = threading.Lock()
        self._embedder = embedder or Embedder()

    # -------------------------------------------------------------- #
    @property
    def neural(self) -> bool:
        return self._embedder.neural

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [m.group(0).casefold() for m in _WORD_RE.finditer(text or "")
                if len(m.group(0)) > 1]

    def embed(self, text: str) -> list[float]:
        return self._embedder.embed(text)

    # -------------------------------------------------------------- #
    def add(self, text: str, kind: str = "note",
            meta: dict | None = None) -> bool:
        if not text or not text.strip():
            return False
        tokens = self._tokens(text)
        if not tokens:
            return False
        entry = {
            "text": text.strip(),
            "kind": kind,
            "meta": meta or {},
            "tokens": Counter(tokens),
            "embedding": self.embed(text),
            "ts": time.time(),
        }
        with self._lock:
            self._index.append(entry)
        return True

    def add_bulk(self, items: list[tuple[str, str]]) -> int:
        """Add many ``(text, kind)`` pairs at once; returns count added."""
        n = 0
        for text, kind in items:
            if self.add(text, kind):
                n += 1
        return n

    def clear(self) -> None:
        with self._lock:
            self._index.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._index)

    # -------------------------------------------------------------- #
    def search(self, query: str, k: int = 5,
               kinds: list[str] | None = None) -> list[dict]:
        """Top-k entries by blended cosine + TF-IDF score."""
        if not query or not query.strip():
            return []
        with self._lock:
            candidates = [dict(e) for e in self._index
                          if not kinds or e.get("kind") in kinds]
        if not candidates:
            return []
        k = max(1, int(k))
        doc_count = len(candidates)
        df: dict[str, int] = {}
        for entry in candidates:
            for token in entry["tokens"]:
                df[token] = df.get(token, 0) + 1

        def idf(token: str) -> float:
            if token not in df:
                return 1.0
            return math.log((1 + doc_count) / (1 + df[token])) + 1.0

        q_tokens = self._tokens(query)
        if not q_tokens:
            return []
        q_counts = Counter(q_tokens)
        q_vec = self.embed(query)
        q_norm = math.sqrt(sum(v * v for v in q_vec)) or 1.0
        q_weight = {t: c * idf(t) for t, c in q_counts.items()}
        q_l2 = math.sqrt(sum(w * w for w in q_weight.values())) or 1.0

        scored: list[tuple[float, dict]] = []
        for entry in candidates:
            # cosine on embeddings (already L2-normalized -> dot product)
            cos = sum(a * b for a, b in zip(q_vec, entry["embedding"]))
            # lexical TF-IDF cosine
            dot = sum(q_weight.get(t, 0.0) * c * idf(t)
                      for t, c in entry["tokens"].items()
                      if t in q_weight)
            e_norm = math.sqrt(sum((c * idf(t)) ** 2
                                   for t, c in entry["tokens"].items())) or 1.0
            lex = dot / (q_l2 * e_norm)
            score = 0.6 * max(0.0, cos) + 0.4 * max(0.0, lex)
            scored.append((score, entry))
        scored.sort(key=lambda item: -item[0])
        return [{"text": e["text"], "kind": e.get("kind", "note"),
                 "meta": e.get("meta", {}), "ts": e.get("ts", 0.0),
                 "score": round(score, 4)}
                for score, e in scored[:k]]

    # convenience: plain strings (backwards-compatible signature)
    def search_texts(self, query: str, k: int = 5,
                     kinds: list[str] | None = None) -> list[str]:
        return [r["text"] for r in self.search(query, k, kinds)]
