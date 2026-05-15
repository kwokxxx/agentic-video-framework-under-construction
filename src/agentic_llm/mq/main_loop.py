from __future__ import annotations

from dataclasses import dataclass

from agentic_llm.agent_loop import AgentOnceRun
from agentic_llm.mq.in_memory import InMemoryMessageQueue
from agentic_llm.mq.messages import OutboundMessage
from agentic_llm.mq.session_router import SessionRouter


@dataclass(slots=True)
class ProcessedMessage:
    session_id: str
    inbound_message_id: str
    outbound_message_id: str
    partition: int


class AgentMainLoop:
    """Service-level loop that consumes inbound messages and emits outbound replies."""

    def __init__(
        self,
        *,
        queue: InMemoryMessageQueue,
        agent: AgentOnceRun,
        router: SessionRouter | None = None,
    ) -> None:
        self._queue = queue
        self._agent = agent
        self._router = router or SessionRouter()

    async def process_once(self) -> ProcessedMessage:
        inbound = await self._queue.consume_inbound()
        partition = self._router.route(inbound.session_id)
        try:
            user_prompt = inbound.content
            if inbound.source != "user":
                user_prompt = f"[{inbound.source}]\n{inbound.content}"
            result = await self._agent.run(
                session_id=inbound.session_id,
                user_prompt=user_prompt,
            )
            outbound = OutboundMessage(
                session_id=inbound.session_id,
                content=result.content or "",
                correlation_id=inbound.message_id,
                metadata={
                    "inbound_source": inbound.source,
                    "inbound_metadata": inbound.metadata,
                    "run_id": result.run_id,
                },
            )
            await self._queue.publish_outbound(outbound)
            return ProcessedMessage(
                session_id=inbound.session_id,
                inbound_message_id=inbound.message_id,
                outbound_message_id=outbound.message_id,
                partition=partition,
            )
        finally:
            self._queue.acknowledge_inbound()
