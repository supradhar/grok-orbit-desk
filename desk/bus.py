from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any


class EventBus:
    """In-memory pub/sub so layers can pass packets like an orbit."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[..., Awaitable[None] | None]]] = defaultdict(list)
        self.packets: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def subscribe(self, topic: str, fn: Callable[..., Awaitable[None] | None]) -> None:
        self._subs[topic].append(fn)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        packet = {"topic": topic, **payload}
        async with self._lock:
            self.packets.append(packet)
            if len(self.packets) > 120:
                self.packets = self.packets[-80:]
        for fn in list(self._subs.get(topic, [])) + list(self._subs.get("*", [])):
            result = fn(packet)
            if asyncio.iscoroutine(result):
                await result

    def recent(self, n: int = 40) -> list[dict[str, Any]]:
        return self.packets[-n:]
