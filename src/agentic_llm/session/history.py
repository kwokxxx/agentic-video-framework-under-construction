from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
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
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "created_at_ms": int(time.time() * 1000),
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

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.jsonl")):
            records: list[dict[str, Any]] = []
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    records.append(json.loads(line))
            if not records:
                continue
            latest = records[-1]
            session_id = str(latest.get("session_id") or path.stem)
            sessions.append(
                {
                    "id": session_id,
                    "message_count": len(records) * 2,
                    "updated_at_ms": int(latest.get("created_at_ms") or 0),
                }
            )
        sessions.sort(key=lambda session: session["updated_at_ms"], reverse=True)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _path(self, session_id: str) -> Path:
        return self.root / f"{_safe_id(session_id)}.jsonl"
