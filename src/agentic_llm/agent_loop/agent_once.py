from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Any

from agentic_llm.context.builder import ContextBuilder
from agentic_llm.llm.base import LLMProvider
from agentic_llm.runtime.checkpoint import CheckpointStore
from agentic_llm.runtime.hooks import AgentHookContext, CompositeHook
from agentic_llm.session.history import JsonlHistoryStore
from agentic_llm.tools.registry import ToolExecution, ToolRegistry


class MaxIterationsExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class AgentRunResult:
    content: str | None
    run_id: str
    iterations: int
    tool_executions: list[ToolExecution] = field(default_factory=list)


class AgentOnceRun:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        context_builder: ContextBuilder,
        tool_registry: ToolRegistry,
        history_store: JsonlHistoryStore,
        checkpoint_store: CheckpointStore,
        hook: CompositeHook | None = None,
        max_iterations: int = 6,
    ) -> None:
        self._provider = provider
        self._context_builder = context_builder
        self._tool_registry = tool_registry
        self._history_store = history_store
        self._checkpoint_store = checkpoint_store
        self._hook = hook or CompositeHook()
        self._max_iterations = max_iterations

    async def run(self, *, session_id: str, user_prompt: str) -> AgentRunResult:
        run_id = uuid.uuid4().hex
        messages: list[dict[str, Any]] = self._context_builder.build_messages(
            session_id=session_id,
            user_prompt=user_prompt,
        )
        answer_events: list[dict[str, Any]] = []
        all_tool_executions: list[ToolExecution] = []

        for iteration in range(1, self._max_iterations + 1):
            context = AgentHookContext(
                session_id=session_id,
                run_id=run_id,
                iteration=iteration,
                messages=messages,
            )
            await self._hook.before_iteration(context)

            response = await self._provider.complete(
                messages=messages,
                tools=self._tool_registry.schemas(),
            )
            await self._hook.on_stream_end(context, resuming=False)

            if response.tool_calls:
                if response.content:
                    answer_events.append(
                        {
                            "type": "text",
                            "content": response.content,
                            "phase": "intermediate",
                        }
                    )

                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            tool_call.to_chat_tool_call()
                            for tool_call in response.tool_calls
                        ],
                    }
                )
                for tool_call in response.tool_calls:
                    answer_events.append(
                        {
                            "type": "tool_call",
                            "tool": tool_call.name,
                            "arguments": tool_call.arguments,
                            "id": tool_call.id,
                        }
                    )

                executions = await self._tool_registry.execute_tool_calls(
                    response.tool_calls
                )
                all_tool_executions.extend(executions)
                context.tool_executions = executions
                await self._hook.after_execute_tools(context)

                for step_offset, execution in enumerate(executions, 1):
                    step = len(all_tool_executions) - len(executions) + step_offset
                    self._checkpoint_store.append_tool_result(
                        session_id=session_id,
                        run_id=run_id,
                        step=step,
                        tool_call=execution.tool_call,
                        tool_result=execution.result,
                    )
                    answer_events.append(execution.result.to_event())
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": execution.tool_call.id,
                            "content": execution.result.content,
                        }
                    )
                continue

            final_content = self._hook.finalize_content(context, response.content)
            answer_events.append(
                {
                    "type": "text",
                    "content": final_content,
                    "phase": "final",
                }
            )
            self._history_store.append_qa(
                session_id=session_id,
                question=user_prompt,
                answer=answer_events,
                run_id=run_id,
            )
            return AgentRunResult(
                content=final_content,
                run_id=run_id,
                iterations=iteration,
                tool_executions=all_tool_executions,
            )

        raise MaxIterationsExceeded(
            f"Agent exceeded max_iterations={self._max_iterations}"
        )

