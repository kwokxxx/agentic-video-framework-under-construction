from agentic_llm.mq.in_memory import InMemoryMessageQueue
from agentic_llm.mq.messages import InboundMessage, OutboundMessage
from agentic_llm.mq.session_router import SessionRouter

__all__ = [
    "AgentMainLoop",
    "InboundMessage",
    "InMemoryMessageQueue",
    "OutboundMessage",
    "SessionRouter",
]


def __getattr__(name: str):
    if name == "AgentMainLoop":
        from agentic_llm.mq.main_loop import AgentMainLoop

        return AgentMainLoop
    raise AttributeError(name)
