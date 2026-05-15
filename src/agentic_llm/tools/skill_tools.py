from __future__ import annotations

from typing import Any

from agentic_llm.skills import SkillLoader
from agentic_llm.tools.base import BaseTool, ToolResult


class ReadSkillTool(BaseTool):
    name = "read_skill"
    description = "Read a full SKILL.md body after the skill index indicates it is relevant."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name from the Skill Index.",
            },
        },
        "required": ["name"],
    }

    def __init__(self, skill_loader: SkillLoader) -> None:
        self._skill_loader = skill_loader

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = arguments.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        content = self._skill_loader.read_skill(name)
        metadata = self._skill_loader.get_skill(name)
        return ToolResult(
            tool_name=self.name,
            content=content,
            metadata={
                "skill": name,
                "location": str(metadata.location) if metadata else "",
            },
        )
