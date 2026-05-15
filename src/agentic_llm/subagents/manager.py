from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
import time
from typing import Callable, TYPE_CHECKING
import uuid

from agentic_llm.mq.messages import InboundMessage

if TYPE_CHECKING:
    from agentic_llm.agent_loop import AgentOnceRun


AgentFactory = Callable[[], "AgentOnceRun"]
SubAgentResultHandler = Callable[[InboundMessage], None]


@dataclass(slots=True)
class SubAgentTask:
    id: str
    parent_session_id: str
    child_session_id: str
    prompt: str
    status: str = "queued"
    result: str | None = None
    error: str | None = None
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    completed_at_ms: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "parent_session_id": self.parent_session_id,
            "child_session_id": self.child_session_id,
            "prompt": self.prompt,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at_ms": self.created_at_ms,
            "completed_at_ms": self.completed_at_ms,
        }


class SubAgentManager:
    """Runs SubAgents in isolated sessions and returns results as system_subagent messages."""

    def __init__(
        self,
        *,
        agent_factory: AgentFactory,
        on_result: SubAgentResultHandler | None = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._on_result = on_result
        self._tasks: dict[str, SubAgentTask] = {}
        self._lock = threading.Lock()

    def spawn(self, *, parent_session_id: str, prompt: str) -> SubAgentTask:
        task_id = uuid.uuid4().hex
        child_session_id = f"{parent_session_id}:subagent:{task_id}"
        task = SubAgentTask(
            id=task_id,
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            prompt=prompt,
        )
        with self._lock:
            self._tasks[task_id] = task

        thread = threading.Thread(
            target=self._run_in_thread,
            args=(task_id,),
            name=f"subagent-{task_id[:8]}",
            daemon=True,
        )
        thread.start()
        return task

    def list_tasks(self) -> list[dict[str, object]]:
        with self._lock:
            return [task.to_dict() for task in self._tasks.values()]

    def _run_in_thread(self, task_id: str) -> None:
        asyncio.run(self._run(task_id))

    async def _run(self, task_id: str) -> None:
        task = self._get_task(task_id)
        if task is None:
            return
        self._update_task(task_id, status="running")
        try:
            agent = self._agent_factory()
            result = await agent.run(
                session_id=task.child_session_id,
                user_prompt=task.prompt,
            )
            content = result.content or ""
            self._update_task(
                task_id,
                status="completed",
                result=content,
                completed_at_ms=int(time.time() * 1000),
            )
            if self._on_result is not None:
                self._on_result(
                    InboundMessage(
                        session_id=task.parent_session_id,
                        source="system_subagent",
                        content=(
                            f"SubAgent {task.id} completed.\n"
                            f"Original task: {task.prompt}\n\n"
                            f"Result:\n{content}"
                        ),
                        metadata={
                            "subagent_id": task.id,
                            "child_session_id": task.child_session_id,
                        },
                    )
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._update_task(
                task_id,
                status="failed",
                error=error,
                completed_at_ms=int(time.time() * 1000),
            )
            if self._on_result is not None:
                task = self._get_task(task_id)
                if task is not None:
                    self._on_result(
                        InboundMessage(
                            session_id=task.parent_session_id,
                            source="system_subagent",
                            content=f"SubAgent {task.id} failed.\nOriginal task: {task.prompt}\n\nError:\n{error}",
                            metadata={
                                "subagent_id": task.id,
                                "child_session_id": task.child_session_id,
                                "error": error,
                            },
                        )
                    )

    def _get_task(self, task_id: str) -> SubAgentTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def _update_task(self, task_id: str, **changes: object) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            for key, value in changes.items():
                setattr(task, key, value)
