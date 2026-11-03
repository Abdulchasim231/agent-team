"""Broadcast of team activity to every open dashboard (the office view)."""

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager


class EventHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self.latest: dict[str, dict] = {}  # last event per agent, for late joiners
        self.stats = {"requests": 0, "delegations": 0, "tool_calls": 0, "replies": 0}

    def publish(self, event: dict) -> None:
        event = {**event, "ts": time.time()}
        counter = {"start": "requests", "delegate": "delegations", "tool": "tool_calls",
                   "reply": "replies"}.get(event.get("type", ""))
        if counter:
            self.stats[counter] += 1
        if agent := event.get("agent"):
            self.latest[agent] = event
        for queue in list(self._subscribers):
            queue.put_nowait(event)

    def snapshot(self) -> dict:
        return {"type": "snapshot", "agents": self.latest, "stats": self.stats}

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[dict]]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
