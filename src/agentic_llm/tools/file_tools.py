from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentic_llm.tools.base import BaseTool, ToolResult


class WorkspaceFileTool(BaseTool):
    def __init__(self, workspace_root: Path | str) -> None:
        self._workspace_root = Path(workspace_root).resolve()

    def _resolve_path(self, path_value: Any) -> Path:
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("path must be a non-empty string")

        path = Path(path_value)
        if not path.is_absolute():
            path = self._workspace_root / path
        resolved = path.resolve()
        if not resolved.is_relative_to(self._workspace_root):
            raise ValueError("path must stay inside the workspace root")
        return resolved


class ReadFileTool(WorkspaceFileTool):
    name = "read_file"
    description = "Read a text file from the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to read.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum number of characters to return.",
            },
        },
        "required": ["path"],
    }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(arguments.get("path"))
        max_chars = int(arguments.get("max_chars") or 12000)
        content = path.read_text(encoding="utf-8")
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars] + "\n... omitted ..."
        return ToolResult(
            tool_name=self.name,
            content=content,
            metadata={
                "path": str(path),
                "truncated": truncated,
            },
        )


class GrepFileTool(WorkspaceFileTool):
    name = "grep_file"
    description = "Search a text file for a regular expression pattern."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to search.",
            },
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern.",
            },
            "max_matches": {
                "type": "integer",
                "description": "Maximum number of matching lines to return.",
            },
        },
        "required": ["path", "pattern"],
    }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(arguments.get("path"))
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a non-empty string")

        max_matches = int(arguments.get("max_matches") or 50)
        regex = re.compile(pattern)
        matches: list[str] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if regex.search(line):
                matches.append(f"{line_number}: {line}")
                if len(matches) >= max_matches:
                    break

        return ToolResult(
            tool_name=self.name,
            content="\n".join(matches) if matches else "No matches.",
            metadata={
                "path": str(path),
                "pattern": pattern,
                "matches": len(matches),
            },
        )

