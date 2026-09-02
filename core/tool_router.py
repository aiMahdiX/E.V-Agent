"""Tool Orchestrator — the Tool Decision Layer of the hybrid architecture.

The LLM only ever talks to this orchestrator. For each request it:

1. consults the Capability Manager to decide native (low latency) vs MCP
   (external/extensible) — priorities from config tilt the decision,
2. permission-gates the call (native rules / MCP approval) and audits it,
3. routes to the native ToolRouter or the MCPRegistry, and returns a result.

Exposes the same ``schemas()`` / ``dispatch()`` surface as before so the
Agent keeps working unchanged.
"""
from __future__ import annotations

from typing import Any
from pathlib import Path

from tools.router import ToolRouter
from tools.mcp.registry import MCPRegistry
from core.capability_manager import CapabilityManager
from security.permissions import PermissionDenied


class ToolOrchestrator:
    def __init__(self, native: ToolRouter, mcp: MCPRegistry,
                 capabilities: CapabilityManager, perm=None):
        self.native = native
        self.mcp = mcp
        self.caps = capabilities
        self.perm = perm
        self.last_route: tuple[str, str] = ("", "")   # tool -> (type, source)

    # ------------------------------------------------------------ #
    def schemas(self) -> list[dict]:
        """Native schemas plus MCP-only tool schemas (no duplicate names)."""
        schemas = self.native.schemas()
        owned = {s["function"]["name"] for s in schemas}
        for t in self.mcp.tool_schemas():
            if t["function"]["name"] not in owned:
                schemas.append(t)
        return schemas

    def names(self) -> list[str]:
        native = set(self.native.names())
        mcp = {t["function"]["name"] for t in self.mcp.tool_schemas()}
        return sorted(native | mcp)

    # ------------------------------------------------------------ #
    def dispatch(self, name: str, arguments: dict) -> Any:
        # Native tools take precedence; MCP only serves names that no
        # native tool owns.
        if name in self.native._tools:
            return self._dispatch_native(name, arguments)
        cap = self.caps.by_tool(name)
        if cap is not None and cap.tool_type == "mcp":
            return self._dispatch_mcp(cap, name, arguments)
        return {"error": f"unknown tool: {name}", "blocked": True}

    def _dispatch_native(self, name: str, arguments: dict) -> Any:
        self.last_route = (name, ("native", "system"))
        return self.native.dispatch(name, arguments)

    def _dispatch_mcp(self, cap, name: str, arguments: dict) -> Any:
        self.last_route = (name, ("mcp", cap.provider))
        if cap.needs_approval and self.perm is not None:
            try:
                self.perm.authorize(f"mcp::{name}", arguments)
            except PermissionDenied as e:
                return {"error": str(e), "blocked": True,
                        "route": "mcp", "provider": cap.provider}
        return self.mcp.call(name, arguments)

    # ------------------------------------------------------------ #
    def capabilities_summary(self) -> list[str]:
        return self.caps.summary_lines()