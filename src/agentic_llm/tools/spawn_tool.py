from __future__ import annotations

from typing import Any

from agentic_llm.subagents import SubAgentManager
from agentic_llm.tools.base import BaseTool, ToolResult


class SpawnTool(BaseTool):
    name = "spawn_subagent"
    description = (
        "Start an asynchronous SubAgent for a long-running or parallelizable task. "
        "The tool returns immediately; the SubAgent result comes back later as a system_subagent message."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Specific task prompt for the SubAgent.",
            },
            "parent_session_id": {
                "type": "string",
                "description": "Parent session that should receive the SubAgent result.",
            },
        },
        "required": ["prompt"],
    }

    def __init__(self, manager: SubAgentManager) -> None:
        self._manager = manager

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        parent_session_id = str(arguments.get("parent_session_id") or "default")
        task = self._manager.spawn(
            parent_session_id=parent_session_id,
            prompt=prompt,
        )
        return ToolResult(
            tool_name=self.name,
            content=(
                f"Started SubAgent {task.id}. "
                "It will return a system_subagent message when complete."
            ),
            metadata=task.to_dict(),
        )
