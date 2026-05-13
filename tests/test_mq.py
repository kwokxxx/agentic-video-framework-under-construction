from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.agent_loop import AgentOnceRun
from agentic_llm.context import ContextBuilder
from agentic_llm.llm.base import LLMResponse
from agentic_llm.mq import AgentMainLoop, InboundMessage, InMemoryMessageQueue, SessionRouter
from agentic_llm.runtime import CheckpointStore
from agentic_llm.session import JsonlHistoryStore
from agentic_llm.tools import ToolRegistry


class FinalAnswerProvider:
    async def complete(self, *, messages, tools):
        return LLMResponse(content="done", tool_calls=[])


class InMemoryMessageQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_inbound_and_outbound_queues(self) -> None:
        queue = InMemoryMessageQueue()
        inbound = InboundMessage(session_id="session-1", content="hello")

        await queue.publish_inbound(inbound)
        self.assertEqual(queue.inbound_size(), 1)

        consumed = await queue.consume_inbound()
        queue.acknowledge_inbound()
        self.assertEqual(consumed, inbound)


class SessionRouterTest(unittest.TestCase):
    def test_same_session_routes_to_same_partition(self) -> None:
        router = SessionRouter(partition_count=8)

        first = router.route("user-1:conversation-1")
        second = router.route("user-1:conversation-1")

        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 8)


class AgentMainLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_once_consumes_inbound_and_emits_outbound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_store = JsonlHistoryStore(root / "history")
            agent = AgentOnceRun(
                provider=FinalAnswerProvider(),
                context_builder=ContextBuilder(
                    workspace_root=root,
                    history_store=history_store,
                ),
                tool_registry=ToolRegistry([]),
                history_store=history_store,
                checkpoint_store=CheckpointStore(root / "checkpoints"),
            )
            queue = InMemoryMessageQueue()
            main_loop = AgentMainLoop(
                queue=queue,
                agent=agent,
                router=SessionRouter(partition_count=4),
            )
            inbound = InboundMessage(
                session_id="user-1:conversation-1",
                content="hello",
            )

            await queue.publish_inbound(inbound)
            processed = await main_loop.process_once()
            outbound = await queue.consume_outbound()
            queue.acknowledge_outbound()

            self.assertEqual(processed.session_id, inbound.session_id)
            self.assertEqual(processed.inbound_message_id, inbound.message_id)
            self.assertEqual(processed.outbound_message_id, outbound.message_id)
            self.assertEqual(outbound.correlation_id, inbound.message_id)
            self.assertEqual(outbound.content, "done")
            self.assertEqual(len(history_store.load_qas(inbound.session_id)), 1)


if __name__ == "__main__":
    unittest.main()

