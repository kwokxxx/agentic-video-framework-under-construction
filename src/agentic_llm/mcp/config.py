from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Literal


MCPTransport = Literal["stdio", "sse", "streamableHttp"]


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    name: str
    type: MCPTransport | None = None
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    tool_timeout: int = 30
    enabled_tools: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_dict(cls, name: str, payload: dict[str, Any]) -> "MCPServerConfig":
        enabled = payload.get("enabled_tools", payload.get("enabledTools", ["*"]))
        return cls(
            name=name,
            type=payload.get("type"),
            command=str(payload.get("command") or ""),
            args=[str(item) for item in payload.get("args", [])],
            env={str(key): _expand_env(str(value)) for key, value in dict(payload.get("env") or {}).items()},
            url=str(payload.get("url") or ""),
            headers={str(key): _expand_env(str(value)) for key, value in dict(payload.get("headers") or {}).items()},
            tool_timeout=int(payload.get("tool_timeout") or payload.get("toolTimeout") or 30),
            enabled_tools=[str(item) for item in enabled],
        )

    def is_tool_enabled(self, name: str) -> bool:
        return "*" in self.enabled_tools or name in self.enabled_tools


def load_mcp_configs(payload: dict[str, Any]) -> list[MCPServerConfig]:
    servers = payload.get("mcp_servers") or payload.get("mcpServers") or payload
    if not isinstance(servers, dict):
        raise ValueError("MCP config must be an object of server configs")
    configs: list[MCPServerConfig] = []
    for name, value in servers.items():
        if isinstance(value, dict):
            configs.append(MCPServerConfig.from_dict(str(name), value))
    return configs


def _expand_env(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value
