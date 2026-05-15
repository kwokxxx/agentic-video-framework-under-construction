from __future__ import annotations

from pathlib import Path
from typing import Callable

from agentic_llm.context.compressor import ContextCompressionReport, ContextCompressor
from agentic_llm.session.history import JsonlHistoryStore
from agentic_llm.skills import SkillLoader


class ContextBuilder:
    def __init__(
        self,
        *,
        workspace_root: Path | str,
        history_store: JsonlHistoryStore,
        runtime_context_provider: Callable[[], str] | None = None,
        skill_loader: SkillLoader | None = None,
        compressor: ContextCompressor | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._history_store = history_store
        self._runtime_context_provider = runtime_context_provider
        self._skill_loader = skill_loader
        self._compressor = compressor or ContextCompressor()
        self.last_compression_report = ContextCompressionReport()

    def build_messages(self, *, session_id: str, user_prompt: str) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            }
        ]

        compressed = self._compressor.compress(self._history_store.load_qas(session_id))
        self.last_compression_report = compressed.report

        for record in compressed.records:
            messages.append({"role": "user", "content": str(record.get("question", ""))})
            rendered_answer = self._render_answer(record.get("answer", []))
            if rendered_answer:
                messages.append({"role": "assistant", "content": rendered_answer})

        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _build_system_prompt(self) -> str:
        sections: list[str] = [
            "You are an Agentic LLM creative assistant. Use tools when they are needed, treat tool results as observations, and produce a final answer when the task is complete."
        ]

        for name in ("AGENT.md", "USER.md", "TOOLS.md"):
            path = self._workspace_root / name
            if path.exists():
                sections.append(f"## {name}\n{path.read_text(encoding='utf-8')}")

        if self._runtime_context_provider is not None:
            runtime_context = self._runtime_context_provider()
            if runtime_context:
                sections.append(f"## Runtime Context\n{runtime_context}")

        if self._skill_loader is not None:
            skill_index = self._skill_loader.build_index_xml()
            if skill_index:
                sections.append(
                    "## Skill Index\n"
                    "The following skills are available. Load a full SKILL.md only when the task needs that SOP.\n"
                    f"{skill_index}"
                )

        return "\n\n".join(sections)

    def _render_answer(self, answer: object) -> str:
        if not isinstance(answer, list):
            return ""

        rendered: list[str] = []
        for event in answer:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "text":
                rendered.append(str(event.get("content", "")))
            elif event_type == "tool_call":
                rendered.append(
                    f"[tool_call:{event.get('tool')}] {event.get('arguments', {})}"
                )
            elif event_type == "tool_result":
                rendered.append(
                    f"[tool_result:{event.get('tool')} status={event.get('status')}] "
                    f"{event.get('content', '')}"
                )
        return "\n".join(part for part in rendered if part)
