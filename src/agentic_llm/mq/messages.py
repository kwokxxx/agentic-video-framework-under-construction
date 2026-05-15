from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
from typing import Any


@dataclass(frozen=True, slots=True)
class InboundMessage:
    session_id: str
    content: str
    source: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    session_id: str
    content: str
    source: str = "agent"
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
