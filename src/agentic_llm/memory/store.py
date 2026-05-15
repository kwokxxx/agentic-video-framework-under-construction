from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


MemoryKind = Literal["user", "tools"]


@dataclass(frozen=True, slots=True)
class MemoryFile:
    kind: MemoryKind
    filename: str
    description: str


class MarkdownMemoryStore:
    """Markdown-backed memory store for USER.md and TOOLS.md."""

    _FILES: dict[MemoryKind, MemoryFile] = {
        "user": MemoryFile(
            kind="user",
            filename="USER.md",
            description="User preferences, identity, creative positioning, and style memory.",
        ),
        "tools": MemoryFile(
            kind="tools",
            filename="TOOLS.md",
            description="Tool usage feedback, constraints, caveats, and operating notes.",
        ),
    }

    def __init__(self, workspace_root: Path | str) -> None:
        self._workspace_root = Path(workspace_root).resolve()

    def path_for(self, kind: MemoryKind) -> Path:
        return self._workspace_root / self._FILES[kind].filename

    def read(self, kind: MemoryKind) -> str:
        path = self.path_for(kind)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def rewrite(self, kind: MemoryKind, content: str) -> Path:
        path = self.path_for(kind)
        path.write_text(_normalize_markdown(content), encoding="utf-8")
        return path

    def index(self) -> list[dict[str, str | bool]]:
        rows: list[dict[str, str | bool]] = []
        for memory in self._FILES.values():
            path = self._workspace_root / memory.filename
            rows.append(
                {
                    "kind": memory.kind,
                    "filename": memory.filename,
                    "description": memory.description,
                    "exists": path.exists(),
                }
            )
        return rows


def _normalize_markdown(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return ""
    return stripped + "\n"
