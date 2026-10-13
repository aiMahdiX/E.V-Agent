"""Local embeddings — hash-based n-gram character vectors + optional neural.

Two backends behind one interface:

- ``hash`` (default, dependency-free): deterministic character n-gram hashing
  into a fixed-width vector. Works for Persian and English, no model download,
  no GPU. Much stronger than plain word TF-IDF for fuzzy semantic similarity.
- ``ollama``: true neural embeddings through the local Ollama server
  (``/api/embed``, e.g. ``nomic-embed-text``). Used automatically when the
  server answers and the model is pulled; falls back to hash otherwise.

Both produce L2-normalized vectors, so cosine similarity is a plain dot
product.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.request

DIM = 384
_NGRAM_RE = re.compile(r"[\w\u0600-\u06ff]+")


class HashEmbedder:
    """Dependency-free character n-gram embedding (Persian + Latin)."""

    def __init__(self, dim: int = DIM):
        self.dim = dim
        self.model = "local-hash-ngram"

    def _tokens(self, text: str) -> list[str]:
        words = _NGRAM_RE.findall((text or "").casefold())
        grams: list[str] = []
        for w in words:
            if len(w) <= 3:
                grams.append(w)
                continue
            grams.append(f"<{w}>")
            for i in range(len(w) - 1):
                grams.append(w[i:i + 3])
        return grams

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for g in self._tokens(text or ""):
            h = hashlib.sha1(g.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


class OllamaEmbedder:
    """Neural embeddings from the local Ollama server (/api/embed)."""

    def __init__(self, host: str = "http://localhost:11434",
                 model: str = "nomic-embed-text", timeout: float = 4.0):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.available = self._probe()

    def _probe(self) -> bool:
        try:
            with urllib.request.urlopen(
                    f"{self.host}/api/tags", timeout=self.timeout) as resp:
                tags = json.loads(resp.read().decode("utf-8"))
            names = {m.get("name", "") for m in tags.get("models", [])}
            for name in names:
                base = name.split(":")[0]
                if base == self.model or base.startswith(self.model):
                    return True
            # model not pulled — try the embed endpoint anyway (cloud/alias)
            return self._try_embed("test") is not None
        except Exception:  # noqa: BLE001 — no server / no network
            return False

    def _try_embed(self, text: str) -> list[float] | None:
        try:
            req = urllib.request.Request(
                f"{self.host}/api/embed",
                data=json.dumps({"model": self.model,
                                 "input": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            embeddings = data.get("embeddings") or []
            return embeddings[0] if embeddings else None
        except Exception:  # noqa: BLE001
            return None

    def embed(self, text: str) -> list[float]:
        vec = self._try_embed(text or "")
        if vec:
            norm = math.sqrt(sum(v * v for v in vec))
            return [v / norm for v in vec] if norm else vec
        raise RuntimeError("ollama embed unavailable")


class Embedder:
    """Facade: neural (Ollama) when reachable, hash fallback otherwise."""

    def __init__(self, host: str = "http://localhost:11434",
                 model: str = "nomic-embed-text"):
        self._ollama: OllamaEmbedder | None = None
        try:
            candidate = OllamaEmbedder(host=host, model=model)
            if candidate.available:
                self._ollama = candidate
        except Exception:  # noqa: BLE001
            self._ollama = None
        self._hash = HashEmbedder()
        self.model = self._ollama.model if self._ollama else self._hash.model

    @property
    def neural(self) -> bool:
        return self._ollama is not None

    def embed(self, text: str) -> list[float]:
        if self._ollama is not None:
            try:
                return self._ollama.embed(text)
            except Exception:  # noqa: BLE001 — degrade, never crash
                self._ollama = None
                self.model = self._hash.model
        return self._hash.embed(text)
