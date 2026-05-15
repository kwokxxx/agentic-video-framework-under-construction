from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any
from urllib.request import Request, urlopen
import uuid

from agentic_llm.mcp.config import MCPServerConfig


class MCPClientError(RuntimeError):
    pass


class MCPClient:
    """Minimal MCP client for streamable HTTP/SSE-style JSON-RPC endpoints."""

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config

    async def list_tools(self) -> list[dict[str, Any]]:
        payload = await self._json_rpc("tools/list", {})
        tools = payload.get("tools") or payload.get("result", {}).get("tools")
        if not isinstance(tools, list):
            return []
        return [tool for tool in tools if isinstance(tool, dict) and self._config.is_tool_enabled(str(tool.get("name") or ""))]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._json_rpc(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

    async def _json_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._config.type == "stdio":
            return await asyncio.to_thread(self._stdio_rpc, method, params)
        if self._config.type not in {"streamableHttp", "sse"}:
            raise MCPClientError(f"Unsupported MCP transport: {self._config.type}")
        if not self._config.url:
            raise MCPClientError("MCP HTTP config requires url")
        request_payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params,
        }
        return await asyncio.to_thread(self._post_json, request_payload)

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self._config.headers,
        }
        request = Request(self._config.url, data=data, headers=headers, method="POST")
        with urlopen(request, timeout=self._config.tool_timeout) as response:
            raw = response.read()
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise MCPClientError("MCP response must be a JSON object")
        if parsed.get("error"):
            raise MCPClientError(str(parsed["error"]))
        result = parsed.get("result", parsed)
        return result if isinstance(result, dict) else {"result": result}

    def _stdio_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._config.command:
            raise MCPClientError("MCP stdio config requires command")
        request_payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params,
        }
        body = json.dumps(request_payload).encode("utf-8")
        framed = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
        env = {**os.environ, **self._config.env}
        process = subprocess.Popen(
            [self._config.command, *self._config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            if process.stdin is None or process.stdout is None:
                raise MCPClientError("stdio process pipes were not created")
            process.stdin.write(framed)
            process.stdin.flush()
            response = _read_framed_json(process.stdout)
            if response.get("error"):
                raise MCPClientError(str(response["error"]))
            result = response.get("result", response)
            return result if isinstance(result, dict) else {"result": result}
        finally:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


def _read_framed_json(stream: Any) -> dict[str, Any]:
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = stream.read(1)
        if not chunk:
            raise MCPClientError("MCP stdio server closed before response headers")
        header += chunk
    header_text, remainder = header.split(b"\r\n\r\n", 1)
    content_length: int | None = None
    for line in header_text.decode("ascii", errors="replace").split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break
    if content_length is None:
        raise MCPClientError("MCP stdio response missing Content-Length")
    body = remainder
    while len(body) < content_length:
        chunk = stream.read(content_length - len(body))
        if not chunk:
            raise MCPClientError("MCP stdio server closed before response body")
        body += chunk
    parsed = json.loads(body[:content_length].decode("utf-8"))
    if not isinstance(parsed, dict):
        raise MCPClientError("MCP stdio response must be a JSON object")
    return parsed
