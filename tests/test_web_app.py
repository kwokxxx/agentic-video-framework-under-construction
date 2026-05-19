from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.llm.base import LLMResponse, ToolCall
from agentic_llm.web.app import WebAppState


class FakeProvider:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.calls = []

    async def complete(self, *, messages, tools):
        self.calls.append(messages)
        return LLMResponse(content="web ok", tool_calls=[])


class ToolProvider:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.calls = 0

    async def complete(self, *, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "AGENT.md"},
                        raw_arguments='{"path":"AGENT.md"}',
                    )
                ],
            )
        return LLMResponse(content="read complete", tool_calls=[])


class WebAppStateTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_uses_mq_path_and_records_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("AGENT.md", "USER.md", "TOOLS.md"):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
                with patch("agentic_llm.web.app.DeepSeekProvider", FakeProvider):
                    app = WebAppState(root)
                    response = await app.handle_chat(
                        {
                            "session_id": "demo",
                            "message": "hello",
                        }
                    )

            self.assertEqual(response["message"]["content"], "web ok")
            event_types = [event["type"] for event in response["trace"]]
            self.assertIn("user.prompt", event_types)
            self.assertIn("mq.inbound", event_types)
            self.assertIn("agent.iteration", event_types)
            self.assertIn("llm.response", event_types)
            self.assertIn("agent.finalize", event_types)
            self.assertIn("mq.outbound", event_types)
            self.assertIn("session.history", event_types)

    async def test_status_does_not_expose_api_key_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-secret"}, clear=True):
                with patch("agentic_llm.web.app.DeepSeekProvider", FakeProvider):
                    app = WebAppState(root)

            status = app.status()

            self.assertTrue(status["api_key_configured"])
            self.assertNotIn("test-secret", str(status))

    async def test_automation_crud_uses_cron_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
                with patch("agentic_llm.web.app.DeepSeekProvider", FakeProvider):
                    app = WebAppState(root)
                    automation = app.create_automation(
                        {
                            "description": "Morning check",
                            "prompt": "Summarize overnight changes.",
                            "session_id": "demo",
                            "enabled": True,
                            "delete_after_run": False,
                            "schedule": {"kind": "cron", "expr": "*/30 * * * *"},
                        }
                    )

                    self.assertEqual(len(app.list_automations()), 1)
                    self.assertEqual(automation["description"], "Morning check")
                    self.assertEqual(automation["schedule"]["expr"], "*/30 * * * *")

                    run_at_ms = int(time.time() * 1000) + 3600000
                    updated = app.update_automation(
                        automation["id"],
                        {
                            "description": "One shot",
                            "prompt": "Run once.",
                            "enabled": False,
                            "schedule": {"kind": "once", "run_at_ms": run_at_ms},
                            "delete_after_run": True,
                        },
                    )

                    self.assertEqual(updated["description"], "One shot")
                    self.assertFalse(updated["enabled"])
                    self.assertEqual(updated["schedule"]["kind"], "once")
                    self.assertEqual(updated["state"]["next_run_at_ms"], run_at_ms)

                    delete_result = app.delete_automation(automation["id"])

            self.assertTrue(delete_result["deleted"])
            self.assertEqual(app.list_automations(), [])

    async def test_sessions_restore_history_and_preserve_agent_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
                with patch("agentic_llm.web.app.DeepSeekProvider", FakeProvider):
                    app = WebAppState(root)
                    await app.handle_chat(
                        {
                            "session_id": "demo",
                            "message": "remember demo detail",
                        }
                    )
                    await app.handle_chat(
                        {
                            "session_id": "other",
                            "message": "other detail",
                        }
                    )
                    await app.handle_chat(
                        {
                            "session_id": "demo",
                            "message": "recall this session",
                        }
                    )

            sessions = app.list_sessions()
            self.assertEqual({session["id"] for session in sessions}, {"demo", "other"})

            history = app.session_history("demo")
            self.assertEqual(
                [message["role"] for message in history["messages"]],
                ["user", "assistant", "user", "assistant"],
            )
            self.assertEqual(history["messages"][0]["content"], "remember demo detail")

            latest_context = app.provider.calls[-1]
            user_messages = [
                message["content"]
                for message in latest_context
                if message["role"] == "user"
            ]
            self.assertIn("remember demo detail", user_messages)
            self.assertIn("recall this session", user_messages)
            self.assertNotIn("other detail", user_messages)

            delete_result = app.delete_session("other")
            self.assertTrue(delete_result["deleted"])
            self.assertEqual(app.session_history("other")["messages"], [])
            self.assertEqual(
                {session["id"] for session in app.list_sessions()},
                {"demo"},
            )

    async def test_chat_passes_uploaded_attachments_to_agent_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
                with patch("agentic_llm.web.app.DeepSeekProvider", FakeProvider):
                    app = WebAppState(root)
                    attachments = app.save_uploads(
                        session_id="demo",
                        files=[
                            {
                                "filename": "note.txt",
                                "content": b"hello attachment",
                                "mime_type": "text/plain",
                            }
                        ],
                    )
                    await app.handle_chat(
                        {
                            "session_id": "demo",
                            "message": "inspect this",
                            "attachments": attachments,
                        }
                    )

            latest_context = app.provider.calls[-1]
            latest_user_message = latest_context[-1]["content"]
            self.assertIn("inspect this", latest_user_message)
            self.assertIn("Attached files are available", latest_user_message)
            self.assertIn("Use inspect_file", latest_user_message)
            self.assertIn("note.txt", latest_user_message)
            self.assertIn(attachments[0]["path"], latest_user_message)
            self.assertIn("inspect_file", {tool["name"] for tool in app.status()["tools"]})

            history = app.session_history("demo")
            self.assertEqual(history["messages"][0]["content"], "inspect this\n\nAttached: note.txt")
            delete_result = app.delete_session("demo")
            self.assertTrue(delete_result["deleted"])
            self.assertFalse((root / attachments[0]["path"]).exists())

    async def test_folder_upload_preserves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
                with patch("agentic_llm.web.app.DeepSeekProvider", FakeProvider):
                    app = WebAppState(root)
                    attachments = app.save_uploads(
                        session_id="demo",
                        files=[
                            {
                                "filename": "clip.txt",
                                "relative_path": "project/assets/clip.txt",
                                "content": b"clip",
                                "mime_type": "text/plain",
                            },
                            {
                                "filename": "shot.png",
                                "relative_path": "project/frames/shot.png",
                                "content": b"\x89PNG\r\n\x1a\n",
                                "mime_type": "image/png",
                            },
                        ],
                    )

            names = {attachment["name"] for attachment in attachments}
            self.assertEqual(
                names,
                {"project/assets/clip.txt", "project/frames/shot.png"},
            )
            for attachment in attachments:
                self.assertTrue((root / attachment["path"]).exists())
                self.assertIn("/project/", attachment["path"])

    async def test_session_history_renders_tool_hooks_as_system_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENT.md").write_text("# Agent\nhello", encoding="utf-8")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
                with patch("agentic_llm.web.app.DeepSeekProvider", ToolProvider):
                    app = WebAppState(root)
                    await app.handle_chat(
                        {
                            "session_id": "demo",
                            "message": "read AGENT.md",
                        }
                    )

            history = app.session_history("demo")
            event_types = [event["type"] for event in app.trace.list_events(limit=20)]

            self.assertEqual(
                [message["role"] for message in history["messages"]],
                ["user", "system", "system", "assistant"],
            )
            self.assertIn("tool.call", event_types)
            self.assertIn("tool.executed", event_types)
            self.assertIn("Tool call: read_file", history["messages"][1]["content"])
            self.assertNotIn("HOOK SYSTEM", history["messages"][1]["content"])
            self.assertIn("path: AGENT.md", history["messages"][1]["content"])
            self.assertIn("Tool result: read_file / success", history["messages"][2]["content"])
            self.assertIn("content_chars:", history["messages"][2]["content"])
            self.assertEqual(history["messages"][3]["content"], "read complete")


if __name__ == "__main__":
    unittest.main()
