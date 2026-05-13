from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.llm.base import LLMResponse
from agentic_llm.web.app import WebAppState


class FakeProvider:
    def __init__(self, settings) -> None:
        self.settings = settings

    async def complete(self, *, messages, tools):
        return LLMResponse(content="web ok", tool_calls=[])


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


if __name__ == "__main__":
    unittest.main()

