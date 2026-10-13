from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager


class InMemoryBroker:
    def __init__(self):
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @staticmethod
    def _safe_put(queue: asyncio.Queue, payload: dict):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def publish(self, payload: dict):
        for loop, queue in tuple(self._subscribers):
            if loop.is_closed():
                continue
            loop.call_soon_threadsafe(self._safe_put, queue, payload)

    @asynccontextmanager
    async def subscribe(self):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        entry = (loop, queue)
        self._subscribers.add(entry)
        try:
            yield queue
        finally:
            self._subscribers.discard(entry)
