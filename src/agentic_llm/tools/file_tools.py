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


class WriteFileTool(WorkspaceFileTool):
    name = "write_file"
    description = "Write a complete text file inside the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to write.",
            },
            "content": {
                "type": "string",
                "description": "Full file content to write.",
            },
        },
        "required": ["path", "content"],
    }

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(
            tool_name=self.name,
            content=f"Wrote {len(content)} characters to {path}.",
            metadata={
                "path": str(path),
                "chars": len(content),
            },
        )


class EditFileTool(WorkspaceFileTool):
    name = "edit_file"
    description = "Edit a workspace text file by replacing an exact old string with a new string."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to edit.",
            },
            "old": {
                "type": "string",
                "description": "Exact text to replace.",
            },
            "new": {
                "type": "string",
                "description": "Replacement text.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of only the first occurrence.",
            },
        },
        "required": ["path", "old", "new"],
    }

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(arguments.get("path"))
        old = arguments.get("old")
        new = arguments.get("new")
        if not isinstance(old, str) or not old:
            raise ValueError("old must be a non-empty string")
        if not isinstance(new, str):
            raise ValueError("new must be a string")

        content = path.read_text(encoding="utf-8")
        count = content.count(old)
        if count == 0:
            raise ValueError("old text was not found")

        replace_all = bool(arguments.get("replace_all"))
        updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        replacements = count if replace_all else 1
        return ToolResult(
            tool_name=self.name,
            content=f"Edited {path}; replacements={replacements}.",
            metadata={
                "path": str(path),
                "replacements": replacements,
            },
        )
