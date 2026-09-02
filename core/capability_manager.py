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
            cap = Capability(tool, "native", int(prio),
                             provider="system", tools=[tool])
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

    # ------------------------------------------------------------ #
    def has(self, name: str) -> bool:
        return name in self.capabilities

    def get(self, name: str) -> Capability | None:
        return self.capabilities.get(name)

    def all(self) -> list[Capability]:
        return sorted(self.capabilities.values(),
                      key=lambda c: (-c.priority, c.name))

    def by_tool(self, tool_name: str) -> Capability | None:
        """The capability that owns a given tool (highest priority wins)."""
        matches = [c for c in self.capabilities.values()
                   if tool_name in c.tools]
        if not matches:
            return None
        return max(matches, key=lambda c: c.priority)

    def best_for(self, tool_name: str) -> Capability | None:
        return self.by_tool(tool_name)

    def native_tools(self) -> set[str]:
        return {c.name for c in self.capabilities.values()
                if c.tool_type == "native" and c.provider == "system"}

    def summary_lines(self) -> list[str]:
        out = ["Capabilities:"]
        for cap in self.all():
            out.append("  " + cap.summary())
        return out