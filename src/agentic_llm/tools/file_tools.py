from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
import struct
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


class InspectFileTool(WorkspaceFileTool):
    name = "inspect_file"
    description = "Inspect any workspace file, including binary files and images."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to inspect.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum text preview characters for text-like files.",
            },
        },
        "required": ["path"],
    }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(arguments.get("path"))
        max_chars = int(arguments.get("max_chars") or 4000)
        data = path.read_bytes()
        mime_type = _guess_mime_type(path.name)
        digest = hashlib.sha256(data).hexdigest()
        dimensions = _image_dimensions(data, mime_type)
        preview = _text_preview(path, data, mime_type, max_chars=max_chars)

        metadata: dict[str, Any] = {
            "path": str(path),
            "mime_type": mime_type,
            "size_bytes": len(data),
            "sha256": digest,
        }
        lines = [
            f"Path: {path}",
            f"MIME: {mime_type}",
            f"Size: {len(data)} bytes",
            f"SHA256: {digest}",
        ]
        if dimensions is not None:
            width, height = dimensions
            metadata["width"] = width
            metadata["height"] = height
            lines.append(f"Image dimensions: {width}x{height}")
        if preview is not None:
            text, truncated = preview
            metadata["truncated"] = truncated
            lines.append("")
            lines.append("Text preview:")
            lines.append(text)
            if truncated:
                lines.append("... omitted ...")
        else:
            metadata["text_preview"] = False
            lines.append("Text preview: unavailable for this file type.")

        return ToolResult(
            tool_name=self.name,
            content="\n".join(lines),
            metadata=metadata,
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


def _text_preview(
    path: Path,
    data: bytes,
    mime_type: str,
    *,
    max_chars: int,
) -> tuple[str, bool] | None:
    text_suffixes = {
        ".csv",
        ".json",
        ".log",
        ".md",
        ".py",
        ".toml",
        ".tsv",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
    if not mime_type.startswith("text/") and path.suffix.lower() not in text_suffixes:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    truncated = len(text) > max_chars
    return (text[:max_chars], truncated)


def _guess_mime_type(filename: str) -> str:
    suffix_types = {
        ".csv": "text/csv",
        ".json": "application/json",
        ".log": "text/plain",
        ".md": "text/markdown",
        ".py": "text/x-python",
        ".toml": "application/toml",
        ".tsv": "text/tab-separated-values",
        ".txt": "text/plain",
        ".xml": "application/xml",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
    }
    return (
        mimetypes.guess_type(filename)[0]
        or suffix_types.get(Path(filename).suffix.lower())
        or "application/octet-stream"
    )


def _image_dimensions(data: bytes, mime_type: str) -> tuple[int, int] | None:
    if mime_type == "image/png" and len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", data[16:24])
    if mime_type == "image/gif" and len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if mime_type == "image/jpeg" and len(data) >= 4 and data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    index = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        while marker == 0xFF and index < len(data):
            marker = data[index]
            index += 1
        if marker in (0xD8, 0xD9):
            continue
        if index + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            return None
        if marker in sof_markers and segment_length >= 7:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += segment_length
    return None
