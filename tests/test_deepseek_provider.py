from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.config import DeepSeekSettings
from agentic_llm.llm.deepseek import DeepSeekProvider


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return "response"


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self) -> None:
        self.chat = FakeChat()


class DeepSeekProviderTest(unittest.TestCase):
    def test_disables_thinking_mode_for_tool_loop_compatibility(self) -> None:
        provider = DeepSeekProvider(
            DeepSeekSettings(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="deepseek-v4-flash",
            )
        )
        fake_client = FakeClient()
        provider._client = fake_client

        response = provider._complete_sync(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )

        self.assertEqual(response, "response")
        self.assertEqual(
            fake_client.chat.completions.kwargs["extra_body"],
            {"thinking": {"type": "disabled"}},
        )


if __name__ == "__main__":
    unittest.main()

