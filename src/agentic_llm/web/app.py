from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

from agentic_llm.agent_loop import AgentOnceRun
from agentic_llm.config import DeepSeekSettings
from agentic_llm.context import ContextBuilder
from agentic_llm.llm import DeepSeekProvider
from agentic_llm.mq import AgentMainLoop, InboundMessage, InMemoryMessageQueue, SessionRouter
from agentic_llm.runtime import CheckpointStore, CompositeHook
from agentic_llm.session import JsonlHistoryStore
from agentic_llm.tools import GrepFileTool, ReadFileTool, ToolRegistry
from agentic_llm.web.tracing import TraceRecorder, TraceRecorderHook


class SessionLockManager:
    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, session_id: str) -> threading.Lock:
        with self._guard:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]


class WebAppState:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.state_root = self.workspace_root / ".agentic_llm"
        self.history_store = JsonlHistoryStore(self.state_root / "history")
        self.checkpoint_store = CheckpointStore(self.state_root / "checkpoints")
        self.trace = TraceRecorder()
        self.router = SessionRouter(partition_count=8)
        self.locks = SessionLockManager()
        self.settings = DeepSeekSettings.from_env()
        self.tool_registry = ToolRegistry(
            [
                ReadFileTool(self.workspace_root),
                GrepFileTool(self.workspace_root),
            ]
        )
        self.context_builder = ContextBuilder(
            workspace_root=self.workspace_root,
            history_store=self.history_store,
        )
        self.agent = AgentOnceRun(
            provider=DeepSeekProvider(self.settings),
            context_builder=self.context_builder,
            tool_registry=self.tool_registry,
            history_store=self.history_store,
            checkpoint_store=self.checkpoint_store,
            hook=CompositeHook([TraceRecorderHook(self.trace)]),
        )

    async def handle_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or "default").strip() or "default"
        content = str(payload.get("message") or "").strip()
        if not content:
            raise ValueError("message is required")

        lock = self.locks.get(session_id)
        with lock:
            return await self._handle_chat_locked(session_id, content)

    async def _handle_chat_locked(self, session_id: str, content: str) -> dict[str, Any]:
        queue = InMemoryMessageQueue()
        main_loop = AgentMainLoop(
            queue=queue,
            agent=self.agent,
            router=self.router,
        )
        inbound = InboundMessage(session_id=session_id, content=content)
        partition = self.router.route(session_id)
        self.trace.record(
            event_type="mq.inbound",
            title="Inbound message enqueued",
            detail=f"User message routed to partition {partition}.",
            session_id=session_id,
            metadata={
                "message_id": inbound.message_id,
                "partition": partition,
                "source": inbound.source,
            },
        )

        await queue.publish_inbound(inbound)
        processed = await main_loop.process_once()
        outbound = await queue.consume_outbound()
        queue.acknowledge_outbound()
        self.trace.record(
            event_type="mq.outbound",
            title="Outbound message emitted",
            detail="Agent reply published to MQ OutBound.",
            session_id=session_id,
            metadata={
                "message_id": outbound.message_id,
                "correlation_id": outbound.correlation_id,
                "partition": processed.partition,
            },
        )
        self.trace.record(
            event_type="session.history",
            title="History persisted",
            detail="Completed QA written to JSONL history store.",
            session_id=session_id,
            metadata={
                "history_records": len(self.history_store.load_qas(session_id)),
                "state_root": str(self.state_root),
            },
        )

        return {
            "session_id": session_id,
            "message": {
                "id": outbound.message_id,
                "role": "assistant",
                "content": outbound.content,
                "correlation_id": outbound.correlation_id,
            },
            "partition": processed.partition,
            "trace": self.trace.list_events(limit=80),
        }

    def status(self) -> dict[str, Any]:
        bootstrap = {
            name: (self.workspace_root / name).exists()
            for name in ("AGENT.md", "USER.md", "TOOLS.md")
        }
        tools = [
            {
                "name": schema["function"]["name"],
                "description": schema["function"]["description"],
            }
            for schema in self.tool_registry.schemas()
        ]
        return {
            "model": self.settings.model,
            "base_url": self.settings.base_url,
            "api_key_configured": bool(self.settings.api_key),
            "workspace_root": str(self.workspace_root),
            "state_root": str(self.state_root),
            "partition_count": self.router.partition_count,
            "bootstrap": bootstrap,
            "tools": tools,
            "trace": self.trace.list_events(limit=80),
        }


class AgentHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], app_state: WebAppState) -> None:
        super().__init__(server_address, AgentRequestHandler)
        self.app_state = app_state


class AgentRequestHandler(BaseHTTPRequestHandler):
    server: AgentHTTPServer

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/api/status"):
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static("index.html")
            return
        if parsed.path == "/api/status":
            self._send_json(self.server.app_state.status())
            return
        if parsed.path == "/api/trace":
            query = parse_qs(parsed.query)
            limit = int(query.get("limit", ["100"])[0])
            self._send_json({"trace": self.server.app_state.trace.list_events(limit=limit)})
            return
        if parsed.path.startswith("/static/"):
            self._serve_static(parsed.path.removeprefix("/static/"))
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/chat":
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            payload = self._read_json()
            response = asyncio.run(self.server.app_state.handle_chat(payload))
        except ValueError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self.server.app_state.trace.record(
                event_type="server.error",
                title="Request failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Agent request failed")
            return

        self._send_json(response)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _serve_static(self, relative_path: str) -> None:
        static_root = Path(__file__).parent / "static"
        target = (static_root / relative_path).resolve()
        if not target.is_relative_to(static_root.resolve()) or not target.exists():
            self._send_error(HTTPStatus.NOT_FOUND, "Static file not found")
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)


def run_server(host: str = "0.0.0.0", port: int = 8000, workspace_root: Path | None = None) -> None:
    root = workspace_root or Path.cwd()
    app_state = WebAppState(root)
    server = AgentHTTPServer((host, port), app_state)
    print(f"Agentic Video Framework console running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, workspace_root=Path.cwd())


if __name__ == "__main__":
    main()
