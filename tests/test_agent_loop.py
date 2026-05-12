from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.agent_loop import AgentOnceRun
from agentic_llm.context import ContextBuilder
from agentic_llm.llm.base import LLMResponse, ToolCall
from agentic_llm.runtime import CheckpointStore
from agentic_llm.session import JsonlHistoryStore
from agentic_llm.tools import GrepFileTool, ReadFileTool, ToolRegistry


class FakeProvider:
    def __init__(self) -> None:
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
                        arguments={"path": "note.txt"},
                        raw_arguments='{"path":"note.txt"}',
                    )
                ],
            )
        return LLMResponse(content="The file says: hello agent.", tool_calls=[])


class AgentLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_tool_loop_writes_history_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello agent", encoding="utf-8")
            history_store = JsonlHistoryStore(root / "history")
            checkpoint_store = CheckpointStore(root / "checkpoints")
            agent = AgentOnceRun(
                provider=FakeProvider(),
                context_builder=ContextBuilder(
                    workspace_root=root,
                    history_store=history_store,
                ),
                tool_registry=ToolRegistry([ReadFileTool(root)]),
                history_store=history_store,
                checkpoint_store=checkpoint_store,
            )

            result = await agent.run(
                session_id="user-1:conversation-1",
                user_prompt="Read note.txt",
            )

            self.assertEqual(result.content, "The file says: hello agent.")
            self.assertEqual(result.iterations, 2)
            self.assertEqual(len(result.tool_executions), 1)

            qas = history_store.load_qas("user-1:conversation-1")
            self.assertEqual(len(qas), 1)
            event_types = [event["type"] for event in qas[0]["answer"]]
            self.assertEqual(event_types, ["tool_call", "tool_result", "text"])

            checkpoints = checkpoint_store.load(
                session_id="user-1:conversation-1",
                run_id=result.run_id,
            )
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(checkpoints[0]["tool_call"]["tool"], "read_file")


class ToolRegistryTest(unittest.IsolatedAsyncioTestCase):
    async def test_grep_tool_returns_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("alpha\nbeta\nalphabet\n", encoding="utf-8")
            registry = ToolRegistry([GrepFileTool(root)])

            executions = await registry.execute_tool_calls(
                [
                    ToolCall(
                        id="call_1",
                        name="grep_file",
                        arguments={"path": "note.txt", "pattern": "alpha"},
                    )
                ]
            )

            self.assertEqual(executions[0].result.status, "success")
            self.assertIn("1: alpha", executions[0].result.content)
            self.assertIn("3: alphabet", executions[0].result.content)


if __name__ == "__main__":
    unittest.main()

