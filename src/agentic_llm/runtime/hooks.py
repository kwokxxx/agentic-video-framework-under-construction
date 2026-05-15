from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentHookContext:
    session_id: str
    run_id: str
    iteration: int
    messages: list[dict[str, Any]]
    tool_calls: list[Any] = field(default_factory=list)
    tool_executions: list[Any] = field(default_factory=list)


class AgentHook:
    async def before_iteration(self, context: AgentHookContext) -> None:
        pass

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        pass

    async def on_stream_end(
        self,
        context: AgentHookContext,
        *,
        resuming: bool,
    ) -> None:
        pass

    async def after_execute_tools(self, context: AgentHookContext) -> None:
        pass

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        pass

    def finalize_content(
        self,
        context: AgentHookContext,
        content: str | None,
    ) -> str | None:
        return content


class CompositeHook(AgentHook):
    def __init__(self, hooks: list[AgentHook] | None = None) -> None:
        self._hooks = list(hooks or [])

    async def before_iteration(self, context: AgentHookContext) -> None:
        for hook in self._hooks:
            try:
                await hook.before_iteration(context)
            except Exception:
                logger.exception("AgentHook.before_iteration error in %s", type(hook).__name__)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        for hook in self._hooks:
            try:
                await hook.on_stream(context, delta)
            except Exception:
                logger.exception("AgentHook.on_stream error in %s", type(hook).__name__)

    async def on_stream_end(
        self,
        context: AgentHookContext,
        *,
        resuming: bool,
    ) -> None:
        for hook in self._hooks:
            try:
                await hook.on_stream_end(context, resuming=resuming)
            except Exception:
                logger.exception("AgentHook.on_stream_end error in %s", type(hook).__name__)

    async def after_execute_tools(self, context: AgentHookContext) -> None:
        for hook in self._hooks:
            try:
                await hook.after_execute_tools(context)
            except Exception:
                logger.exception("AgentHook.after_execute_tools error in %s", type(hook).__name__)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for hook in self._hooks:
            try:
                await hook.before_execute_tools(context)
            except Exception:
                logger.exception("AgentHook.before_execute_tools error in %s", type(hook).__name__)

    def finalize_content(
        self,
        context: AgentHookContext,
        content: str | None,
    ) -> str | None:
        for hook in self._hooks:
            content = hook.finalize_content(context, content)
        return content
