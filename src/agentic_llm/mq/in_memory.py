from __future__ import annotations

import asyncio

from agentic_llm.mq.messages import InboundMessage, OutboundMessage


class InMemoryMessageQueue:
    """Local two-way queue used to model MQ InBound and OutBound."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, message: InboundMessage) -> None:
        await self._inbound.put(message)

    async def consume_inbound(self) -> InboundMessage:
        return await self._inbound.get()

    def acknowledge_inbound(self) -> None:
        self._inbound.task_done()

    async def publish_outbound(self, message: OutboundMessage) -> None:
        await self._outbound.put(message)

    async def consume_outbound(self) -> OutboundMessage:
        return await self._outbound.get()

    def acknowledge_outbound(self) -> None:
        self._outbound.task_done()

    def inbound_size(self) -> int:
        return self._inbound.qsize()

    def outbound_size(self) -> int:
        return self._outbound.qsize()

