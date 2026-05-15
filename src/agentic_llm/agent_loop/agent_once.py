from __future__ import annotations

from dataclasses import dataclass, field
import json
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
    resumed_checkpoints: int = 0


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

    async def run(
        self,
        *,
        session_id: str,
        user_prompt: str,
        run_id: str | None = None,
    ) -> AgentRunResult:
        run_id = run_id or uuid.uuid4().hex
        messages: list[dict[str, Any]] = self._context_builder.build_messages(
            session_id=session_id,
            user_prompt=user_prompt,
        )
        answer_events: list[dict[str, Any]] = []
        all_tool_executions: list[ToolExecution] = []
        resumed_checkpoints = self._load_checkpoint_messages(
            session_id=session_id,
            run_id=run_id,
            messages=messages,
            answer_events=answer_events,
        )

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
                self._inject_runtime_arguments(
                    session_id=session_id,
                    tool_calls=response.tool_calls,
                )
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

                context.tool_calls = response.tool_calls
                await self._hook.before_execute_tools(context)
                executions = await self._tool_registry.execute_tool_calls(
                    response.tool_calls
                )
                all_tool_executions.extend(executions)
                context.tool_executions = executions
                await self._hook.after_execute_tools(context)

                for step_offset, execution in enumerate(executions, 1):
                    step = (
                        resumed_checkpoints
                        + len(all_tool_executions)
                        - len(executions)
                        + step_offset
                    )
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
                resumed_checkpoints=resumed_checkpoints,
            )

        raise MaxIterationsExceeded(
            f"Agent exceeded max_iterations={self._max_iterations}"
        )

    def _load_checkpoint_messages(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: list[dict[str, Any]],
        answer_events: list[dict[str, Any]],
    ) -> int:
        checkpoints = self._checkpoint_store.load(session_id=session_id, run_id=run_id)
        for checkpoint in checkpoints:
            tool_call = checkpoint.get("tool_call") or {}
            tool_result = checkpoint.get("tool_result") or {}
            call_id = str(tool_call.get("id") or f"checkpoint_{checkpoint.get('step')}")
            tool_name = str(tool_call.get("tool") or "")
            arguments = tool_call.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            raw_arguments = json.dumps(arguments, ensure_ascii=False)

            answer_events.append(
                {
                    "type": "tool_call",
                    "tool": tool_name,
                    "arguments": arguments,
                    "id": call_id,
                    "resumed": True,
                }
            )
            answer_events.append(
                {
                    "type": "tool_result",
                    "tool": tool_name,
                    "status": tool_result.get("status", "success"),
                    "content": str(tool_result.get("content", "")),
                    "metadata": {
                        **dict(tool_result.get("metadata") or {}),
                        "resumed": True,
                    },
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": raw_arguments,
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": str(tool_result.get("content", "")),
                }
            )
        return len(checkpoints)

    def _inject_runtime_arguments(
        self,
        *,
        session_id: str,
        tool_calls: list[Any],
    ) -> None:
        for tool_call in tool_calls:
            if tool_call.name == "spawn_subagent":
                tool_call.arguments.setdefault("parent_session_id", session_id)
            if tool_call.name == "cron_job" and tool_call.arguments.get("action") == "create":
                tool_call.arguments.setdefault("session_id", session_id)
            tool_call.raw_arguments = json.dumps(tool_call.arguments, ensure_ascii=False)
