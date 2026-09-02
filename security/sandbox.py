"""Sandbox — optional isolation for tool execution (Phase 5+).

Placeholder interface. A future implementation can wrap command execution
with subprocess namespaces, cgroups, or container isolation (e.g. nsjail,
bubblewrap). For now it passes through to the host.
"""
from __future__ import annotations

import subprocess


class Sandbox:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def run(self, argv: list[str], **kwargs):
        if not self.enabled:
            return subprocess.run(argv, capture_output=True, text=True,
                                  **kwargs)
        raise NotImplementedError("Sandbox isolation not yet implemented")
