from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    content: str
    status: str = "success"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool": self.tool_name,
            "status": self.status,
            "content": self.content,
            "metadata": self.metadata,
        }


class BaseTool:
    name: str
    description: str
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return False

    @property
    def concurrency_safe(self) -> bool:
        return self.read_only and not self.exclusive

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

