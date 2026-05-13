from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
import uuid
from typing import Any

from agentic_llm.runtime.hooks import AgentHook, AgentHookContext


@dataclass(frozen=True, slots=True)
class TraceEvent:
    id: str
    type: str
    title: str
    detail: str
    session_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "detail": self.detail,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "metadata": self.metadata,
            "created_at_ms": self.created_at_ms,
        }


class TraceRecorder:
    def __init__(self, limit: int = 300) -> None:
        self._limit = limit
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()

    def record(
        self,
        *,
        event_type: str,
        title: str,
        detail: str,
        session_id: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            id=uuid.uuid4().hex,
            type=event_type,
            title=title,
            detail=detail,
            session_id=session_id,
            run_id=run_id,
            metadata=metadata or {},
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._limit:
                self._events = self._events[-self._limit :]
        return event

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            events = self._events[-limit:]
        return [event.to_dict() for event in events]


class TraceRecorderHook(AgentHook):
    def __init__(self, recorder: TraceRecorder) -> None:
        self._recorder = recorder

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._recorder.record(
            event_type="agent.iteration",
            title="LLM iteration started",
            detail=f"Iteration {context.iteration} started with {len(context.messages)} messages.",
            session_id=context.session_id,
            run_id=context.run_id,
            metadata={
                "iteration": context.iteration,
                "message_count": len(context.messages),
            },
        )

    async def on_stream_end(
        self,
        context: AgentHookContext,
        *,
        resuming: bool,
    ) -> None:
        self._recorder.record(
            event_type="llm.response",
            title="LLM response completed",
            detail=f"Provider response completed for iteration {context.iteration}.",
            session_id=context.session_id,
            run_id=context.run_id,
            metadata={
                "iteration": context.iteration,
                "resuming": resuming,
            },
        )

    async def after_execute_tools(self, context: AgentHookContext) -> None:
        tools = [
            {
                "name": execution.tool_call.name,
                "status": execution.result.status,
                "content_preview": execution.result.content[:240],
            }
            for execution in context.tool_executions
        ]
        self._recorder.record(
            event_type="tool.executed",
            title="Tools executed",
            detail=f"{len(tools)} tool call(s) completed.",
            session_id=context.session_id,
            run_id=context.run_id,
            metadata={
                "iteration": context.iteration,
                "tools": tools,
            },
        )

    def finalize_content(
        self,
        context: AgentHookContext,
        content: str | None,
    ) -> str | None:
        self._recorder.record(
            event_type="agent.finalize",
            title="Final answer ready",
            detail="Final content passed through finalize_content.",
            session_id=context.session_id,
            run_id=context.run_id,
            metadata={
                "iteration": context.iteration,
                "content_chars": len(content or ""),
            },
        )
        return content

