from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from agentic_llm.tools.base import BaseTool, ToolResult


class FetchUrlTool(BaseTool):
    name = "fetch_url"
    description = "Fetch text content from an HTTP or HTTPS URL."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP or HTTPS URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum number of characters to return.",
            },
        },
        "required": ["url"],
    }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = _validate_url(arguments.get("url"))
        max_chars = int(arguments.get("max_chars") or 12000)
        content, content_type = await asyncio.to_thread(_fetch_text, url, max_chars)
        return ToolResult(
            tool_name=self.name,
            content=content,
            metadata={
                "url": url,
                "content_type": content_type,
                "chars": len(content),
            },
        )


class SearchWebTool(BaseTool):
    name = "search_web"
    description = "Search the web for public pages related to a query."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return.",
            },
        },
        "required": ["query"],
    }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        max_results = int(arguments.get("max_results") or 5)
        url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
        html, _content_type = await asyncio.to_thread(_fetch_text, url, 60000)
        parser = _DuckDuckGoResultParser(max_results=max_results)
        parser.feed(html)
        if not parser.results:
            return ToolResult(
                tool_name=self.name,
                content="No search results parsed.",
                metadata={"query": query, "results": 0},
            )
        lines = [
            f"{index}. {item['title']}\n   {item['url']}"
            for index, item in enumerate(parser.results, 1)
        ]
        return ToolResult(
            tool_name=self.name,
            content="\n".join(lines),
            metadata={
                "query": query,
                "results": len(parser.results),
            },
        )


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self, *, max_results: int) -> None:
        super().__init__()
        self._max_results = max_results
        self._in_result_link = False
        self._current_url: str | None = None
        self._current_title_parts: list[str] = []
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or len(self.results) >= self._max_results:
            return
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class") or ""
        href = attrs_dict.get("href")
        if "result__a" in class_name and href:
            self._in_result_link = True
            self._current_url = href
            self._current_title_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            stripped = data.strip()
            if stripped:
                self._current_title_parts.append(stripped)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._in_result_link:
            return
        title = " ".join(self._current_title_parts).strip()
        if title and self._current_url:
            self.results.append({"title": title, "url": self._current_url})
        self._in_result_link = False
        self._current_url = None
        self._current_title_parts = []


def _validate_url(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("url must be a non-empty string")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an HTTP or HTTPS URL")
    return value


def _fetch_text(url: str, max_chars: int) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "agentic-video-framework/0.1",
            "Accept": "text/html,text/plain,application/json,*/*",
        },
    )
    with urlopen(request, timeout=20) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(max_chars + 1)
    text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... omitted ..."
    return text, content_type
