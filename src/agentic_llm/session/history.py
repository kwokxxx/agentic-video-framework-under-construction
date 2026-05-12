from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)


@dataclass(slots=True)
class JsonlHistoryStore:
    root: Path

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append_qa(
        self,
        *,
        session_id: str,
        question: str,
        answer: list[dict[str, Any]],
        run_id: str,
    ) -> None:
        record = {
            "run_id": run_id,
            "question": question,
            "answer": answer,
        }
        with self._path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_qas(self, session_id: str) -> list[dict[str, Any]]:
        path = self._path(session_id)
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    def _path(self, session_id: str) -> Path:
        return self.root / f"{_safe_id(session_id)}.jsonl"

