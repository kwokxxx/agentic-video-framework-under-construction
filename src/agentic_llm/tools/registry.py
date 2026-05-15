from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any

from agentic_llm.llm.base import ToolCall
from agentic_llm.tools.base import BaseTool, ToolResult


@dataclass(slots=True)
class ToolExecution:
    tool_call: ToolCall
    result: ToolResult
    duration_ms: int = 0


class ToolRegistry:
    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    async def execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolExecution]:
        executions: list[ToolExecution] = []
        for batch in self._build_batches(tool_calls):
            batch_results = await asyncio.gather(
                *(self._execute_one(tool_call) for tool_call in batch)
            )
            executions.extend(batch_results)
        return executions

    def _build_batches(self, tool_calls: list[ToolCall]) -> list[list[ToolCall]]:
        batches: list[list[ToolCall]] = []
        current: list[ToolCall] = []

        for tool_call in tool_calls:
            tool = self._tools.get(tool_call.name)
            concurrency_safe = tool is not None and tool.concurrency_safe
            if concurrency_safe:
                current.append(tool_call)
                continue

            if current:
                batches.append(current)
                current = []
            batches.append([tool_call])

        if current:
            batches.append(current)

        return batches

    async def _execute_one(self, tool_call: ToolCall) -> ToolExecution:
        started = time.perf_counter()
        if tool_call.parse_error:
            return ToolExecution(
                tool_call=tool_call,
                result=ToolResult(
                    tool_name=tool_call.name,
                    status="error",
                    content=f"Invalid tool arguments JSON: {tool_call.parse_error}",
                ),
                duration_ms=_elapsed_ms(started),
            )

        tool = self._tools.get(tool_call.name)
        if tool is None:
            return ToolExecution(
                tool_call=tool_call,
                result=ToolResult(
                    tool_name=tool_call.name,
                    status="error",
                    content=f"Unknown tool: {tool_call.name}",
                ),
                duration_ms=_elapsed_ms(started),
            )

        try:
            result = await tool.execute(tool_call.arguments)
        except Exception as exc:
            result = ToolResult(
                tool_name=tool_call.name,
                status="error",
                content=f"{type(exc).__name__}: {exc}",
            )
        return ToolExecution(
            tool_call=tool_call,
            result=result,
            duration_ms=_elapsed_ms(started),
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
