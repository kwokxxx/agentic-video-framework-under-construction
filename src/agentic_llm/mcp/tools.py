from __future__ import annotations

import json
from typing import Any

from agentic_llm.mcp.client import MCPClient
from agentic_llm.mcp.config import MCPServerConfig
from agentic_llm.tools.base import BaseTool, ToolResult


class MCPTool(BaseTool):
    def __init__(
        self,
        *,
        server_name: str,
        client: MCPClient,
        tool_definition: dict[str, Any],
    ) -> None:
        self._server_name = server_name
        self._client = client
        self._tool_definition = tool_definition
        name = str(tool_definition.get("name") or "")
        if not name:
            raise ValueError("MCP tool definition requires name")
        self.name = f"mcp_{server_name}_{name}"
        self._mcp_tool_name = name
        self.description = str(tool_definition.get("description") or f"MCP tool {name}")
        self.parameters = dict(tool_definition.get("inputSchema") or {"type": "object", "properties": {}, "required": []})

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        payload = await self._client.call_tool(self._mcp_tool_name, arguments)
        content = _extract_mcp_content(payload)
        return ToolResult(
            tool_name=self.name,
            content=content,
            metadata={
                "server": self._server_name,
                "mcp_tool": self._mcp_tool_name,
            },
        )


async def build_mcp_tools(configs: list[MCPServerConfig]) -> list[MCPTool]:
    tools: list[MCPTool] = []
    for config in configs:
        client = MCPClient(config)
        for definition in await client.list_tools():
            tools.append(
                MCPTool(
                    server_name=config.name,
                    client=client,
                    tool_definition=definition,
                )
            )
    return tools


def _extract_mcp_content(payload: dict[str, Any]) -> str:
    content = payload.get("content") or payload.get("result", {}).get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(content, str):
        return content
    return json.dumps(payload, ensure_ascii=False)
