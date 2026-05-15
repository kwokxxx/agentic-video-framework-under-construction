from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.context import ContextCompressor, ContextCompressorConfig
from agentic_llm.llm.base import LLMResponse
from agentic_llm.mcp import MCPServerConfig, build_mcp_tools
from agentic_llm.memory import MarkdownMemoryStore
from agentic_llm.runtime import CronJobStore, CronSchedule, CronScheduler, create_cron_job
from agentic_llm.skills import SkillLoader
from agentic_llm.subagents import SubAgentManager
from agentic_llm.tools import CronTool, EditFileTool, ReadSkillTool, RewriteMemoryTool, WriteFileTool


class RuntimeExtensionTest(unittest.IsolatedAsyncioTestCase):
    async def test_write_edit_and_memory_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write = WriteFileTool(root)
            edit = EditFileTool(root)
            memory = RewriteMemoryTool(MarkdownMemoryStore(root))

            await write.execute({"path": "note.txt", "content": "hello agent"})
            await edit.execute({"path": "note.txt", "old": "agent", "new": "runtime"})
            await memory.execute({"kind": "user", "content": "# User\nPrefers concise answers."})

            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "hello runtime")
            self.assertIn("Prefers concise", (root / "USER.md").read_text(encoding="utf-8"))

    async def test_skill_loader_and_read_skill_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "video"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: video\ndescription: \"Video SOP\"\nalways: false\n---\n# Body\n",
                encoding="utf-8",
            )
            loader = SkillLoader(workspace_root=root)
            tool = ReadSkillTool(loader)

            index = loader.build_index_xml()
            result = await tool.execute({"name": "video"})

            self.assertIn("<name>video</name>", index)
            self.assertIn("# Body", result.content)

    async def test_context_compressor_folds_prunes_and_summarizes(self) -> None:
        records = []
        for index in range(10):
            records.append(
                {
                    "question": f"question {index}",
                    "answer": [
                        {
                            "type": "tool_result",
                            "tool": "fetch",
                            "status": "success",
                            "content": "x" * 1000,
                        },
                        {"type": "text", "content": f"answer {index}"},
                    ],
                }
            )
        compressor = ContextCompressor(
            ContextCompressorConfig(
                max_context_chars=1400,
                tool_result_max_chars=200,
                tool_result_head_chars=60,
                tool_result_tail_chars=40,
                max_history_records=6,
                summary_recent_records=2,
            )
        )

        compressed = compressor.compress(records)

        self.assertTrue(compressed.report.folded_tool_results > 0)
        self.assertTrue(compressed.report.summary_created)
        self.assertLessEqual(len(compressed.records), 3)

    async def test_cron_tool_creates_and_deletes_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CronJobStore(Path(tmp) / "jobs.json")
            tool = CronTool(store)
            result = await tool.execute(
                {
                    "action": "create",
                    "description": "test job",
                    "prompt": "say hi",
                    "session_id": "demo",
                    "schedule": {
                        "kind": "once",
                        "run_at_ms": int(time.time() * 1000) + 60000,
                    },
                }
            )
            job_id = result.metadata["id"]

            self.assertEqual(len(store.list_jobs()), 1)
            await tool.execute({"action": "delete", "id": job_id})
            self.assertEqual(store.list_jobs(), [])

    async def test_cron_scheduler_executes_due_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CronJobStore(Path(tmp) / "jobs.json")
            executed: list[str] = []

            async def executor(job):
                executed.append(job.id)

            job = create_cron_job(
                description="due",
                prompt="run",
                session_id="demo",
                schedule=CronSchedule(kind="once", run_at_ms=int(time.time() * 1000) - 1),
            )
            store.upsert(job)
            scheduler = CronScheduler(store=store, executor=executor)

            await scheduler.on_timer()

            self.assertEqual(executed, [job.id])
            self.assertEqual(store.list_jobs(), [])

    async def test_subagent_manager_returns_system_message(self) -> None:
        class FinalProvider:
            async def complete(self, *, messages, tools):
                return LLMResponse(content="subagent done", tool_calls=[])

        from agentic_llm.agent_loop import AgentOnceRun
        from agentic_llm.context import ContextBuilder
        from agentic_llm.runtime import CheckpointStore
        from agentic_llm.session import JsonlHistoryStore
        from agentic_llm.tools import ToolRegistry

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            messages = []

            def build_agent():
                history = JsonlHistoryStore(root / "history")
                return AgentOnceRun(
                    provider=FinalProvider(),
                    context_builder=ContextBuilder(workspace_root=root, history_store=history),
                    tool_registry=ToolRegistry([]),
                    history_store=history,
                    checkpoint_store=CheckpointStore(root / "checkpoints"),
                )

            manager = SubAgentManager(agent_factory=build_agent, on_result=messages.append)
            task = manager.spawn(parent_session_id="demo", prompt="work")

            deadline = time.time() + 5
            while time.time() < deadline and not messages:
                await asyncio.sleep(0.05)

            self.assertEqual(task.parent_session_id, "demo")
            self.assertEqual(messages[0].source, "system_subagent")
            self.assertIn("subagent done", messages[0].content)


class MCPHTTPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if payload["method"] == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo input",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                },
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"content": [{"type": "text", "text": payload["params"]["arguments"]["text"]}]},
            }
        data = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


class MCPToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_mcp_tools_from_http_server(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = MCPServerConfig(
                name="local",
                type="streamableHttp",
                url=f"http://127.0.0.1:{server.server_address[1]}",
                enabled_tools=["echo"],
            )
            tools = await build_mcp_tools([config])
            result = await tools[0].execute({"text": "hello"})

            self.assertEqual(tools[0].name, "mcp_local_echo")
            self.assertEqual(result.content, "hello")
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
