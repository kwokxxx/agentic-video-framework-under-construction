from __future__ import annotations

from pathlib import Path
from typing import Callable

from agentic_llm.session.history import JsonlHistoryStore


class ContextBuilder:
    def __init__(
        self,
        *,
        workspace_root: Path | str,
        history_store: JsonlHistoryStore,
        runtime_context_provider: Callable[[], str] | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._history_store = history_store
        self._runtime_context_provider = runtime_context_provider

    def build_messages(self, *, session_id: str, user_prompt: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            }
        ]

        for record in self._history_store.load_qas(session_id):
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

