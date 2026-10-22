"""Change notices for the live plant-data streams: ingest (a worker thread) wakes the organisation's streams (the
event loop). The API runs one worker, so an in-process notice reaches every stream."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Optional


class Bus:
    def __init__(self) -> None:
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.version: dict[int, int] = defaultdict(int)
        self._events: dict[int, asyncio.Event] = {}

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def notify(self, key: int) -> None:
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._bump, key)

    def _bump(self, key: int) -> None:
        self.version[key] += 1
        ev = self._events.pop(key, None)
        if ev:
            ev.set()

    async def wait(self, key: int, seen: int, timeout: float) -> int:
        """The version once it is past `seen` (at once if it already is), or after `timeout` seconds."""
        if self.version[key] == seen:
            ev = self._events.setdefault(key, asyncio.Event())
            try:
                await asyncio.wait_for(ev.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        return self.version[key]


BUS = Bus()  # keyed by organisation id
