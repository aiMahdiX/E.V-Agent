"""Model Router — pick any model present in Ollama (architecture §14).

The user wants E.V. to use *any* model installed in Ollama, not just one
pre-configured name. This router:

- lists all models actually available in Ollama at runtime,
- keeps config *preferences* (fast / main / vision) but only uses names
  that actually exist locally,
- picks: smallest available for simple/chat, largest available for
  planning/coding/troubleshooting,
- can be forced to a specific model (CLI ``/model <name>`` or config
  ``model_selection.fixed``).
"""
from __future__ import annotations

import re

from core.planner import detect_complexity, detect_intent


def model_size(name: str) -> float:
    """Heuristic size from the model name, e.g. 'qwen3:8b' -> 8.0."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*b", str(name).lower())
    return float(m.group(1)) if m else 0.0


def _flatten(values) -> list[str]:
    """Flatten a name or names into a list (handles str/list/dict-valued)."""
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    if isinstance(values, dict):
        out = []
        for v in values.values():
            out += _flatten(v)
        return out
    out = []
    for v in values:
        out += _flatten(v)
    return out


class ModelRouter:
    def __init__(self, client=None, preferred: dict | None = None,
                 mode: str = "auto", fixed: str | None = None,
                 available: list[str] | None = None,
                 include_cloud: bool = True):
        self.client = client
        self.preferred = preferred or {}
        self.mode = mode              # "auto" | "fixed"
        self.fixed = fixed
        self.override: str | None = None      # runtime choice (CLI)
        self.available = list(available or [])
        self.include_cloud = include_cloud
        self._last_error: str | None = None

    # ------------------------------------------------------------ #
    def refresh(self) -> list[str]:
        """Re-query Ollama for the current model set."""
        try:
            if self.client is not None:
                self.available = self.client.list_models()
                self._last_error = None
        except Exception as e:  # noqa: BLE001
            self._last_error = str(e)
        return self.available

    def _cloud_ok(self, name: str) -> bool:
        return self.include_cloud or "cloud" not in str(name).lower()

    def pool(self) -> list[str]:
        """The actual pool this router may choose from.

        Real available models when present; configured preferences are
        always considered reachable (cloud models may not appear in the
        local /api/tags listing but still work through Ollama). Cloud
        models are only filtered out when ``include_cloud`` is False.
        """
        out: list[str] = []
        if self.available:
            out += [m for m in self.available if self._cloud_ok(m)]
            # cloud preferences are always reachable through Ollama even
            # when absent from the local tags listing; local preferences
            # must actually be installed to be eligible.
            for key in ("fast", "main", "vision"):
                for m in _flatten(self.preferred.get(key)):
                    if self._cloud_ok(m) and ("cloud" in str(m).lower()
                                              or m in out):
                        out.append(m)
        else:
            for key in ("fast", "main", "vision"):
                out += [m for m in _flatten(self.preferred.get(key))
                        if self._cloud_ok(m)]
        return list(dict.fromkeys(out))

    # ------------------------------------------------------------ #
    def set_override(self, model: str | None) -> str | None:
        self.override = model
        return self.override

    def current(self) -> str | None:
        return self.override or self.fixed or None

    # ------------------------------------------------------------ #
    def choose(self, text: str, intent: str | None = None) -> str:
        if self.mode == "fixed" and self.fixed:
            return self.fixed
        if self.override:
            return self.override

        intent = intent or detect_intent(text)
        complexity = detect_complexity(text)
        pool = self.pool()
        if not pool:
            return ""

        # exact preferred match wins if that model exists locally
        if intent == "observation":
            pref = self.preferred.get("vision")
        elif complexity >= 0.45 or intent in ("task", "emergency"):
            pref = self.preferred.get("main")
        else:
            pref = self.preferred.get("fast")
        for candidate in _flatten(pref):
            if candidate in pool:
                return candidate

        # no preference available -> pick by size (small for fast,
        # largest for complex work).  LOCAL models come first: cloud
        # models may require a paid ollama.com account (HTTP 402), so
        # they are only eligible when nothing local is available.
        local = [m for m in pool if "cloud" not in str(m).lower()] or pool
        sized = sorted(local, key=model_size)
        if complexity >= 0.45 or intent in ("task", "emergency"):
            return sized[-1]      # biggest available
        return sized[0]           # smallest available
