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

from tools.router import ToolRouter
from tools.mcp.registry import MCPRegistry
from core.capability_manager import Capability, CapabilityManager
from security.permissions import PermissionDenied, PermissionEngine


class ToolOrchestrator:
    DEFAULT_NATIVE_PRIORITY = 50

    def __init__(self, native: ToolRouter, mcp: MCPRegistry,
                 capabilities: CapabilityManager,
                 perm: PermissionEngine | None = None):
        self.native = native
        self.mcp = mcp
        self.caps = capabilities
        self.perm = perm
        self.last_route: tuple[str, tuple[str, str]] = ("", ("", ""))

    def _mcp_route(self, name: str, has_native: bool) -> Capability | None:
        capability = self.caps.by_tool(name, "mcp")
        if capability is None:
            return None
        native = self.caps.by_tool(name, "native")
        native_priority = (native.priority if native else
                           self.DEFAULT_NATIVE_PRIORITY)
        if not has_native or capability.priority > native_priority:
            return capability
        return None

    # ------------------------------------------------------------ #
    def schemas(self) -> list[dict]:
        """Expose the schema belonging to the selected provider per tool."""
        native = {schema["function"]["name"]: schema
                  for schema in self.native.schemas()}
        mcp_tools = self.mcp.tool_schemas()
        names = set(native) | {tool["function"]["name"]
                               for tool in mcp_tools}
        schemas = []
        for name in sorted(names):
            capability = self._mcp_route(name, name in native)
            if capability is None:
                if name in native:
                    schemas.append(native[name])
                continue
            candidates = self.mcp.tool_schemas(
                provider=capability.provider)
            selected = next((tool for tool in candidates
                             if tool["function"]["name"] == name), None)
            if selected is not None:
                schemas.append(selected)
        return schemas

    def names(self) -> list[str]:
        native = set(self.native.names())
        mcp = {t["function"]["name"] for t in self.mcp.tool_schemas()}
        return sorted(native | mcp)

    # ------------------------------------------------------------ #
    def dispatch(self, name: str, arguments: dict) -> Any:
        has_native = self.native.has_tool(name)
        cap = self._mcp_route(name, has_native)
        if cap is not None:
            return self._dispatch_mcp(cap, name, arguments)
        if has_native:
            return self._dispatch_native(name, arguments)
        return {"error": f"unknown tool: {name}", "blocked": True}

    def _dispatch_native(self, name: str, arguments: dict) -> Any:
        self.last_route = (name, ("native", "system"))
        return self.native.dispatch(name, arguments)

    def _dispatch_mcp(self, cap: Capability, name: str,
                      arguments: dict) -> Any:
        self.last_route = (name, ("mcp", cap.provider))
        if self.perm is not None:
            try:
                self.perm.authorize(f"mcp::{name}", arguments,
                                    force_approval=cap.needs_approval)
            except PermissionDenied as e:
                return {"error": str(e), "blocked": True,
                        "route": "mcp", "provider": cap.provider}
        return self.mcp.call(name, arguments,
                             provider=cap.provider or None)

    # ------------------------------------------------------------ #
    def capabilities_summary(self) -> list[str]:
        return self.caps.summary_lines()