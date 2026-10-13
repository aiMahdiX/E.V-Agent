"""Capability Manager — knows what E.V. can do.

Every native tool and every connected MCP server registers a Capability.
The Tool Orchestrator consults this layer before dispatching, so it can
decide "native (low latency)" vs "MCP (extensible)" and apply the right
security posture for each type.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Capability:
    name: str
    tool_type: str                     # "native" | "mcp"
    priority: int = 50
    provider: str = ""                 # "system", "game", "browser", ...
    tools: list[str] = field(default_factory=list)
    needs_approval: bool = False

    def summary(self) -> str:
        mark = "✓" if self.tools else "(empty)"
        return (f"{mark} {self.name:<18} [{self.tool_type:<6}] "
                f"priority={self.priority:<3} provider={self.provider or '-'} "
                f"tools={len(self.tools)}")


class CapabilityManager:
    def __init__(self, config: dict | None = None):
        self.capabilities: dict[str, Capability] = {}
        if config:
            self.load_native(config)
            self.load_mcp(config)

    # ------------------------------------------------------------ #
    def load_native(self, config: dict) -> None:
        native = config.get("tools", {}).get("native", {})
        for tool, opts in native.items():
            prio = opts if isinstance(opts, (int, float)) else \
                opts.get("priority", 50)
            tools = opts.get("tools", [tool]) if isinstance(opts, dict) \
                else [tool]
            cap = Capability(tool, "native", int(prio),
                             provider="system", tools=tools)
            self.register(cap)

    def load_mcp(self, config: dict) -> None:
        mcp_cfg = config.get("tools", {}).get("mcp", {})
        for name, opts in mcp_cfg.items():
            if not isinstance(opts, dict):
                continue
            cap = Capability(
                name, "mcp",
                priority=opts.get("priority", 50),
                provider=opts.get("server", ""),
                tools=opts.get("tools", [name]),
                needs_approval=opts.get("needs_approval", True),
            )
            self.register(cap)

    def register(self, cap: Capability) -> Capability:
        self.capabilities[cap.name] = cap
        return cap

    def register_mcp_server(self, name: str, tools: list[str],
                            default_priority: int = 60) -> None:
        """Bind a connected server's tools without discarding configured policy."""
        configured = [cap for cap in self.capabilities.values()
                      if cap.tool_type == "mcp" and cap.provider == name]
        if not configured:
            self.register(Capability(name, "mcp", default_priority,
                                     provider=name, tools=list(tools),
                                     needs_approval=True))
            return

        remaining = set(tools)
        for cap in configured:
            cap.tools = sorted(remaining.intersection(cap.tools))
            remaining.difference_update(cap.tools)
        if remaining:
            self.register(Capability(
                f"{name}:additional", "mcp", default_priority,
                provider=name, tools=sorted(remaining), needs_approval=True))

    # ------------------------------------------------------------ #
    def has(self, name: str) -> bool:
        return name in self.capabilities

    def get(self, name: str) -> Capability | None:
        return self.capabilities.get(name)

    def all(self) -> list[Capability]:
        return sorted(self.capabilities.values(),
                      key=lambda c: (-c.priority, c.name))

    def by_tool(self, tool_name: str,
                tool_type: str | None = None) -> Capability | None:
        """Return the highest-priority capability for a registered tool."""
        matches = [c for c in self.capabilities.values()
                   if tool_name in c.tools
                   and (tool_type is None or c.tool_type == tool_type)]
        if not matches:
            return None
        return max(matches, key=lambda c: (c.priority, c.name))

    def best_for(self, tool_name: str) -> Capability | None:
        return self.by_tool(tool_name)

    def native_tools(self) -> set[str]:
        return {tool for capability in self.capabilities.values()
            if capability.tool_type == "native"
            and capability.provider == "system"
            for tool in capability.tools}

    def summary_lines(self) -> list[str]:
        out = ["Capabilities:"]
        for cap in self.all():
            out.append("  " + cap.summary())
        return out