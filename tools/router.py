"""Tool Router — central registry and dispatcher for all tools.

The LLM only ever talks to this router. Every call is permission-checked
and audited before reaching the OS. Shell commands are classified by their
*content* via ShellPermissionEngine; other tools by their action name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

from tools.base import Tool
from tools.shell import SHELL_TOOL, run_command
from tools.filesystem import FILE_TOOLS
from tools.process import PROCESS_TOOLS
from tools.services import SERVICE_TOOLS
from tools.gpu import GPU_TOOLS
from tools.network import NETWORK_TOOLS
from tools.audio import AUDIO_TOOLS
from tools.screen import SCREEN_TOOLS
from tools.gui import GUI_TOOLS
from tools.browser import BROWSER_TOOLS
from tools.camera import CAMERA_TOOLS
from tools.vision import VISION_TOOLS
from tools.integrations import INTEGRATION_TOOLS
from security.permissions import (PermissionEngine, PermissionDenied,
                                  ShellPermissionEngine)

_SHELL_TOOL_NAME = SHELL_TOOL.name


@dataclass
class ToolRouter:
    workspace: Path = field(default_factory=Path.cwd)
    perm: PermissionEngine | None = None
    shell_perm: ShellPermissionEngine | None = None
    _tools: dict[str, Tool] = field(default_factory=dict)

    def __post_init__(self):
        self.register(SHELL_TOOL)
        for t in (FILE_TOOLS + PROCESS_TOOLS + SERVICE_TOOLS + GPU_TOOLS
                  + NETWORK_TOOLS + AUDIO_TOOLS + SCREEN_TOOLS + GUI_TOOLS
                  + BROWSER_TOOLS + CAMERA_TOOLS + VISION_TOOLS
                  + INTEGRATION_TOOLS):
            self.register(t)
        # if no dedicated shell engine, derive one from the generic engine
        if self.shell_perm is None and self.perm is not None:
            self.shell_perm = ShellPermissionEngine(self.perm)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def _authorize(self, name: str, arguments: dict) -> None:
        if name == _SHELL_TOOL_NAME:
            if self.shell_perm is not None:
                self.shell_perm.authorize_command(
                    str(arguments.get("command", "")))
            return
        if self.perm is not None:
            self.perm.authorize(name, arguments)

    def dispatch(self, name: str, arguments: dict) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool: {name}"}
        try:
            self._authorize(name, arguments)
        except PermissionDenied as e:
            return {"error": str(e), "blocked": True}
        kw = {**arguments}
        kw.setdefault("workspace", self.workspace)
        try:
            return tool.fn(**kw)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{name} raised {type(e).__name__}: {e}"}
