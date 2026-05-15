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
from agentic_llm.memory import MarkdownMemoryStore
from agentic_llm.mq import AgentMainLoop, InboundMessage, InMemoryMessageQueue, SessionRouter
from agentic_llm.runtime import CheckpointStore, CompositeHook, CronJob, CronJobStore, ThreadedCronService
from agentic_llm.session import JsonlHistoryStore
from agentic_llm.skills import SkillLoader
from agentic_llm.subagents import SubAgentManager
from agentic_llm.tools import (
    CronTool,
    EditFileTool,
    FetchUrlTool,
    GrepFileTool,
    ReadFileTool,
    ReadSkillTool,
    RewriteMemoryTool,
    SearchWebTool,
    SpawnTool,
    ToolRegistry,
    WriteFileTool,
)
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
        self.skill_loader = SkillLoader(workspace_root=self.workspace_root)
        self.memory_store = MarkdownMemoryStore(self.workspace_root)
        self.cron_store = CronJobStore(self.state_root / "cron" / "jobs.json")
        self.trace = TraceRecorder()
        self.router = SessionRouter(partition_count=8)
        self.locks = SessionLockManager()
        self.settings = DeepSeekSettings.from_env()
        self.provider = DeepSeekProvider(self.settings)
        self.background_messages: list[dict[str, Any]] = []
        self.background_messages_lock = threading.Lock()
        self.cron_service = ThreadedCronService(
            store=self.cron_store,
            executor=self._execute_cron_job,
        )
        self.subagent_manager = SubAgentManager(
            agent_factory=lambda: self._build_agent(include_spawn=False),
            on_result=self._process_background_inbound,
        )
        self.context_builder: ContextBuilder
        self.tool_registry: ToolRegistry
        self.agent = self._build_agent(include_spawn=True)
        self.cron_service.start()

    def _build_agent(self, *, include_spawn: bool) -> AgentOnceRun:
        context_builder = ContextBuilder(
            workspace_root=self.workspace_root,
            history_store=self.history_store,
            skill_loader=self.skill_loader,
        )
        tools = [
            ReadFileTool(self.workspace_root),
            GrepFileTool(self.workspace_root),
            WriteFileTool(self.workspace_root),
            EditFileTool(self.workspace_root),
            SearchWebTool(),
            FetchUrlTool(),
            ReadSkillTool(self.skill_loader),
            RewriteMemoryTool(self.memory_store),
            CronTool(self.cron_store, on_change=self.cron_service.arm_timer),
        ]
        if include_spawn:
            tools.append(SpawnTool(self.subagent_manager))
        registry = ToolRegistry(tools)
        agent = AgentOnceRun(
            provider=self.provider,
            context_builder=context_builder,
            tool_registry=registry,
            history_store=self.history_store,
            checkpoint_store=self.checkpoint_store,
            hook=CompositeHook([TraceRecorderHook(self.trace)]),
        )
        if include_spawn:
            self.context_builder = context_builder
            self.tool_registry = registry
        return agent

    async def handle_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or "default").strip() or "default"
        content = str(payload.get("message") or "").strip()
        if not content:
            raise ValueError("message is required")

        lock = self.locks.get(session_id)
        with lock:
            return await self._handle_chat_locked(
                session_id,
                content,
                source="user",
                metadata={},
            )

    async def _handle_chat_locked(
        self,
        session_id: str,
        content: str,
        *,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        queue = InMemoryMessageQueue()
        main_loop = AgentMainLoop(
            queue=queue,
            agent=self.agent,
            router=self.router,
        )
        inbound = InboundMessage(
            session_id=session_id,
            content=content,
            source=source,
            metadata=metadata,
        )
        if source == "user":
            self.trace.record(
                event_type="user.prompt",
                title="User prompt submitted",
                detail="User message received from the web console.",
                session_id=session_id,
                metadata={
                    "message_id": inbound.message_id,
                    "content_chars": len(content),
                },
            )
        partition = self.router.route(session_id)
        self.trace.record(
            event_type="mq.inbound",
            title="Inbound message enqueued",
            detail=f"{source} message routed to partition {partition}.",
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
                "session_id": session_id,
                "role": "assistant",
                "content": outbound.content,
                "correlation_id": outbound.correlation_id,
                "source": outbound.source,
                "metadata": outbound.metadata,
            },
            "partition": processed.partition,
            "trace": self.trace.list_events(limit=80),
        }

    async def _execute_cron_job(self, job: CronJob) -> None:
        await asyncio.to_thread(
            self._process_background_inbound,
            InboundMessage(
                session_id=job.session_id,
                source="system_cron",
                content=(
                    f"Cron job {job.id} is due.\n"
                    f"Description: {job.description}\n\n"
                    f"Task:\n{job.prompt}"
                ),
                metadata={
                    "cron_job_id": job.id,
                    "description": job.description,
                },
            ),
        )

    def _process_background_inbound(self, message: InboundMessage) -> None:
        self.trace.record(
            event_type=message.source,
            title="Background message received",
            detail="Background runtime message is being routed through the main Agent.",
            session_id=message.session_id,
            metadata=message.metadata,
        )
        lock = self.locks.get(message.session_id)
        with lock:
            response = asyncio.run(
                self._handle_chat_locked(
                    message.session_id,
                    message.content,
                    source=message.source,
                    metadata=message.metadata,
                )
            )
        with self.background_messages_lock:
            self.background_messages.append(response["message"])
            self.background_messages = self.background_messages[-100:]

    def pop_background_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.background_messages_lock:
            selected = [
                message
                for message in self.background_messages
                if message.get("session_id") == session_id
            ]
            self.background_messages = [
                message for message in self.background_messages if message not in selected
            ]
        return selected

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.history_store.list_sessions()

    def delete_session(self, session_id: str) -> dict[str, Any]:
        deleted_history = self.history_store.delete_session(session_id)
        deleted_checkpoints = self.checkpoint_store.delete_session(session_id)
        with self.background_messages_lock:
            self.background_messages = [
                message
                for message in self.background_messages
                if message.get("session_id") != session_id
            ]
        return {
            "session_id": session_id,
            "deleted": deleted_history or deleted_checkpoints,
        }

    def session_history(self, session_id: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for index, record in enumerate(self.history_store.load_qas(session_id)):
            run_id = str(record.get("run_id") or index)
            created_at_ms = int(record.get("created_at_ms") or 0)
            question = str(record.get("question") or "")
            if question:
                messages.append(
                    {
                        "id": f"{run_id}:user",
                        "session_id": session_id,
                        "role": "user",
                        "content": question,
                        "created_at_ms": created_at_ms,
                    }
                )

            answer_events = record.get("answer", [])
            if isinstance(answer_events, list):
                for event_index, event in enumerate(answer_events):
                    hook_message = self._render_hook_history_message(event)
                    if not hook_message:
                        continue
                    messages.append(
                        {
                            "id": f"{run_id}:hook:{event_index}",
                            "session_id": session_id,
                            "role": "system",
                            "content": hook_message,
                            "created_at_ms": created_at_ms,
                        }
                    )

            answer = self._render_user_history_answer(answer_events)
            if answer:
                messages.append(
                    {
                        "id": f"{run_id}:assistant",
                        "session_id": session_id,
                        "role": "assistant",
                        "content": answer,
                        "created_at_ms": created_at_ms,
                    }
                )
        return {"session_id": session_id, "messages": messages}

    def _render_hook_history_message(self, event: object) -> str:
        if not isinstance(event, dict):
            return ""

        event_type = event.get("type")
        if event_type == "tool_call":
            tool = str(event.get("tool") or "unknown")
            arguments = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
            details = self._format_safe_mapping(arguments)
            lines = [f"Tool call: {tool}"]
            if details:
                lines.append(details)
            return "\n".join(lines)

        if event_type == "tool_result":
            tool = str(event.get("tool") or "unknown")
            status = str(event.get("status") or "success")
            metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
            details = self._format_safe_mapping(
                {
                    **metadata,
                    "content_chars": len(str(event.get("content") or "")),
                }
            )
            lines = [f"Tool result: {tool} / {status}"]
            if details:
                lines.append(details)
            return "\n".join(lines)

        return ""

    def _format_safe_mapping(self, values: dict[str, Any]) -> str:
        safe_keys = {
            "action",
            "chars",
            "content_chars",
            "kind",
            "matches",
            "max_chars",
            "max_matches",
            "name",
            "path",
            "pattern",
            "replacements",
            "status",
            "truncated",
            "url",
        }
        parts: list[str] = []
        for key, value in values.items():
            key_text = str(key)
            if key_text not in safe_keys:
                continue
            parts.append(f"{key_text}: {self._format_safe_value(key_text, value)}")
        return "\n".join(parts)

    def _format_safe_value(self, key: str, value: Any) -> str:
        if key == "path" and isinstance(value, str):
            try:
                path = Path(value).resolve()
                return str(path.relative_to(self.workspace_root))
            except ValueError:
                return value
        return str(value)

    def _render_user_history_answer(self, answer: object) -> str:
        if not isinstance(answer, list):
            return ""

        final_parts: list[str] = []
        fallback_parts: list[str] = []
        for event in answer:
            if not isinstance(event, dict) or event.get("type") != "text":
                continue
            content = str(event.get("content") or "")
            if not content:
                continue
            fallback_parts.append(content)
            if event.get("phase") == "final":
                final_parts.append(content)
        return "\n\n".join(final_parts or fallback_parts)

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
            "skills": [skill.to_dict() for skill in self.skill_loader.list_skills()],
            "memory": self.memory_store.index(),
            "cron_jobs": [job.to_dict() for job in self.cron_store.list_jobs()],
            "subagents": self.subagent_manager.list_tasks(),
            "context_compression": self.context_builder.last_compression_report.to_dict(),
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
        if parsed.path == "/api/sessions":
            self._send_json({"sessions": self.server.app_state.list_sessions()})
            return
        if parsed.path == "/api/history":
            query = parse_qs(parsed.query)
            session_id = (query.get("session_id", ["default"])[0] or "default").strip()
            self._send_json(self.server.app_state.session_history(session_id))
            return
        if parsed.path == "/api/trace":
            query = parse_qs(parsed.query)
            limit = int(query.get("limit", ["100"])[0])
            self._send_json({"trace": self.server.app_state.trace.list_events(limit=limit)})
            return
        if parsed.path == "/api/messages":
            query = parse_qs(parsed.query)
            session_id = (query.get("session_id", ["default"])[0] or "default").strip()
            self._send_json(
                {
                    "messages": self.server.app_state.pop_background_messages(
                        session_id
                    )
                }
            )
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

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/session":
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        query = parse_qs(parsed.query)
        session_id = (query.get("session_id", [""])[0] or "").strip()
        if not session_id:
            self._send_error(HTTPStatus.BAD_REQUEST, "session_id is required")
            return
        self._send_json(self.server.app_state.delete_session(session_id))

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
