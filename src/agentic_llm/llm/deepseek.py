from __future__ import annotations

import asyncio
import json
from typing import Any

from agentic_llm.config import DeepSeekSettings
from agentic_llm.llm.base import LLMResponse, ToolCall


class DeepSeekProvider:
    """DeepSeek OpenAI-compatible chat completions provider."""

    def __init__(self, settings: DeepSeekSettings | None = None) -> None:
        self._settings = settings or DeepSeekSettings.from_env()
        if not self._settings.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required")
        self._client: Any | None = None

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        response = await asyncio.to_thread(self._complete_sync, messages, tools)
        return self._parse_response(response)

    def _complete_sync(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "The openai package is required for DeepSeekProvider. "
                    "Install the project with `python3 -m pip install -e .`."
                ) from exc

            self._client = OpenAI(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
            )

        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if tools:
            kwargs["tools"] = tools
        return self._client.chat.completions.create(**kwargs)

    def _parse_response(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []

        for index, raw_call in enumerate(getattr(message, "tool_calls", None) or []):
            function = raw_call.function
            raw_arguments = function.arguments or "{}"
            arguments: dict[str, Any] = {}
            parse_error: str | None = None
            try:
                parsed = json.loads(raw_arguments)
                if isinstance(parsed, dict):
                    arguments = parsed
                else:
                    parse_error = "Tool arguments must be a JSON object"
            except json.JSONDecodeError as exc:
                parse_error = str(exc)

            tool_calls.append(
                ToolCall(
                    id=getattr(raw_call, "id", f"tool_call_{index}"),
                    name=function.name,
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                    parse_error=parse_error,
                )
            )

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            raw=response,
        )
