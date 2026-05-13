from __future__ import annotations

import hashlib


class SessionRouter:
    def __init__(self, partition_count: int = 1) -> None:
        if partition_count < 1:
            raise ValueError("partition_count must be >= 1")
        self._partition_count = partition_count

    @property
    def partition_count(self) -> int:
        return self._partition_count

    def route(self, session_id: str) -> int:
        digest = hashlib.sha256(session_id.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big")
        return value % self._partition_count

