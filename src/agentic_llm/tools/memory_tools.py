from __future__ import annotations

from typing import Any

from agentic_llm.memory import MarkdownMemoryStore
from agentic_llm.tools.base import BaseTool, ToolResult


class RewriteMemoryTool(BaseTool):
    name = "rewrite_memory"
    description = (
        "Rewrite USER.md or TOOLS.md after considering the full old memory, new memory, "
        "and conflict rules. Use this for durable cross-session memory updates."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "Memory file to rewrite: user or tools.",
                "enum": ["user", "tools"],
            },
            "content": {
                "type": "string",
                "description": "Full replacement Markdown content.",
            },
        },
        "required": ["kind", "content"],
    }

    def __init__(self, memory_store: MarkdownMemoryStore) -> None:
        self._memory_store = memory_store

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        kind = arguments.get("kind")
        if kind not in {"user", "tools"}:
            raise ValueError("kind must be 'user' or 'tools'")
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        path = self._memory_store.rewrite(kind, content)
        return ToolResult(
            tool_name=self.name,
            content=f"Rewrote {path.name} with {len(content)} characters.",
            metadata={
                "kind": kind,
                "path": str(path),
                "chars": len(content),
            },
        )
