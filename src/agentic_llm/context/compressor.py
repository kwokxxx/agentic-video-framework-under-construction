from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import time
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextCompressorConfig:
    max_context_chars: int = 48000
    tool_result_max_chars: int = 2400
    tool_result_head_chars: int = 1200
    tool_result_tail_chars: int = 800
    recent_full_history_records: int = 3
    max_history_records: int = 24
    summary_recent_records: int = 8


@dataclass(slots=True)
class ContextCompressionReport:
    original_records: int = 0
    final_records: int = 0
    original_chars: int = 0
    final_chars: int = 0
    folded_tool_results: int = 0
    pruned_records: int = 0
    summary_created: bool = False
    stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_records": self.original_records,
            "final_records": self.final_records,
            "original_chars": self.original_chars,
            "final_chars": self.final_chars,
            "folded_tool_results": self.folded_tool_results,
            "pruned_records": self.pruned_records,
            "summary_created": self.summary_created,
            "stages": self.stages,
        }


@dataclass(slots=True)
class CompressedHistory:
    records: list[dict[str, Any]]
    report: ContextCompressionReport


class ContextCompressor:
    """Three-stage compression: fold tool results, prune old QA, summarize old QA."""

    def __init__(self, config: ContextCompressorConfig | None = None) -> None:
        self._config = config or ContextCompressorConfig()

    def compress(self, records: list[dict[str, Any]]) -> CompressedHistory:
        report = ContextCompressionReport(
            original_records=len(records),
            original_chars=_estimate_chars(records),
        )
        working = deepcopy(records)

        if _estimate_chars(working) > self._config.max_context_chars:
            folded = self._fold_old_tool_results(working)
            if folded:
                report.folded_tool_results = folded
                report.stages.append("fold_tool_results")

        if (
            _estimate_chars(working) > self._config.max_context_chars
            and len(working) > self._config.max_history_records
        ):
            remove_count = len(working) - self._config.max_history_records
            working = working[remove_count:]
            report.pruned_records += remove_count
            report.stages.append("prune_old_history")

        if _estimate_chars(working) > self._config.max_context_chars:
            working = self._summarize_old_history(working, report)

        report.final_records = len(working)
        report.final_chars = _estimate_chars(working)
        return CompressedHistory(records=working, report=report)

    def _fold_old_tool_results(self, records: list[dict[str, Any]]) -> int:
        folded = 0
        cutoff = max(0, len(records) - self._config.recent_full_history_records)
        for record in records[:cutoff]:
            answer = record.get("answer")
            if not isinstance(answer, list):
                continue
            for event in answer:
                if not isinstance(event, dict) or event.get("type") != "tool_result":
                    continue
                content = event.get("content")
                if not isinstance(content, str):
                    continue
                if len(content) <= self._config.tool_result_max_chars:
                    continue
                event["content"] = _fold_text(
                    content,
                    head_chars=self._config.tool_result_head_chars,
                    tail_chars=self._config.tool_result_tail_chars,
                )
                event.setdefault("metadata", {})
                if isinstance(event["metadata"], dict):
                    event["metadata"]["folded"] = True
                    event["metadata"]["original_chars"] = len(content)
                folded += 1
        return folded

    def _summarize_old_history(
        self,
        records: list[dict[str, Any]],
        report: ContextCompressionReport,
    ) -> list[dict[str, Any]]:
        keep = max(1, self._config.summary_recent_records)
        if len(records) <= keep:
            return records
        old_records = records[:-keep]
        recent = records[-keep:]
        report.summary_created = True
        report.pruned_records += len(old_records)
        report.stages.append("summary_old_history")
        summary = _build_deterministic_summary(old_records)
        summary_record = {
            "run_id": f"context_summary_{int(time.time() * 1000)}",
            "question": "Earlier conversation summary",
            "answer": [
                {
                    "type": "text",
                    "phase": "summary",
                    "content": summary,
                }
            ],
            "summary": True,
        }
        return [summary_record, *recent]


def _fold_text(content: str, *, head_chars: int, tail_chars: int) -> str:
    head = content[:head_chars].rstrip()
    tail = content[-tail_chars:].lstrip()
    return f"{head}\n... omitted ...\n{tail}"


def _build_deterministic_summary(records: list[dict[str, Any]]) -> str:
    lines = [
        "Older context was compressed to keep the current LLM call within budget.",
        "Compressed QA highlights:",
    ]
    for index, record in enumerate(records, 1):
        question = str(record.get("question", "")).strip().replace("\n", " ")
        answer = record.get("answer", [])
        text_parts: list[str] = []
        if isinstance(answer, list):
            for event in answer:
                if isinstance(event, dict) and event.get("type") == "text":
                    text = str(event.get("content", "")).strip().replace("\n", " ")
                    if text:
                        text_parts.append(text)
        answer_preview = " ".join(text_parts)[:240]
        lines.append(f"{index}. User: {question[:240]}")
        if answer_preview:
            lines.append(f"   Assistant: {answer_preview}")
    return "\n".join(lines)


def _estimate_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))
