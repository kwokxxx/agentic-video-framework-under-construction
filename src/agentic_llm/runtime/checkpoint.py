from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from agentic_llm.llm.base import ToolCall
from agentic_llm.tools.base import ToolResult


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)


@dataclass(slots=True)
class CheckpointStore:
    root: Path

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append_tool_result(
        self,
        *,
        session_id: str,
        run_id: str,
        step: int,
        tool_call: ToolCall,
        tool_result: ToolResult,
    ) -> None:
        path = self._path(session_id, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "step": step,
            "tool_call": {
                "id": tool_call.id,
                "tool": tool_call.name,
                "arguments": tool_call.arguments,
            },
            "tool_result": {
                "status": tool_result.status,
                "content": tool_result.content,
                "metadata": tool_result.metadata,
            },
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load(self, *, session_id: str, run_id: str) -> list[dict[str, Any]]:
        path = self._path(session_id, run_id)
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def _path(self, session_id: str, run_id: str) -> Path:
        return self.root / _safe_id(session_id) / f"{_safe_id(run_id)}.jsonl"

