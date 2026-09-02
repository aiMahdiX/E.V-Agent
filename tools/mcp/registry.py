"""MCPRegistry — holds connected MCP clients and maps tool names to them."""
from __future__ import annotations

from tools.mcp.client import MCPClient, MCPError


class MCPRegistry:
    def __init__(self):
        self.clients: dict[str, MCPClient] = {}
        self._tool_map: dict[str, str] = {}   # tool name -> client name

    # ----------------------------------------------------------- #
    def attach(self, client: MCPClient) -> list[dict]:
        """Start a client and index its tools. Returns the tool list."""
        client.start()
        self.clients[client.name] = client
        tools = client.list_tools()
        for t in tools:
            self._tool_map.setdefault(t.get("name"), client.name)
        return tools

    def detach(self, name: str) -> None:
        client = self.clients.pop(name, None)
        if client:
            client.close()
        self._tool_map = {t: c for t, c in self._tool_map.items()
                          if c != name}

    # ----------------------------------------------------------- #
    def connected(self) -> list[str]:
        return sorted(self.clients)

    def tool_schemas(self) -> list[dict]:
        """MCP tools in the Ollama function-schema shape for the LLM."""
        out = []
        for client in self.clients.values():
            for t in client.tools_cache:
                out.append({
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object"}),
                    },
                })
        return out

    def call(self, tool_name: str, arguments: dict) -> dict:
        client_name = self._tool_map.get(tool_name)
        if not client_name:
            return {"error": f"no MCP server provides tool {tool_name!r}",
                    "blocked": True}
        client = self.clients.get(client_name)
        if not client or not client.connected:
            return {"error": f"MCP server {client_name!r} not connected"}
        try:
            return client.call(tool_name, arguments)
        except MCPError as e:
            return {"error": str(e)}

    def close_all(self) -> None:
        for client in self.clients.values():
            client.close()
        self.clients.clear()
        self._tool_map.clear()