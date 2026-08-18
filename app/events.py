"""
In-process pub-sub for the review UI's live updates (Design Decisions V2.7,
Decision 5). One process, one broadcaster, no new dependency — Server-Sent
Events out over app/routes_events.py's /events endpoint.

Deliberately dumb: no persistence, no delivery guarantee, no replay for a
client that wasn't connected when an event fired. That's fine here —
app/routes_candidates.py's GET /candidates already gives a freshly-opened
tab the current state (pending count, etc.), so this bus only needs to
carry live, in-the-moment notifications (V2.7 Decision 5's "since you were
away" case is covered by that existing endpoint, not by this module).

Pure and DB-free by design so it's testable without a request or a
database — see phase1-style standalone scripts for the pattern this
mirrors (no FastAPI/DB dependency for its own logic).
"""

import asyncio
from typing import AsyncIterator


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe_queue(self) -> asyncio.Queue:
        """Lower-level than subscribe() — returns the raw queue so a caller
        (e.g. routes_events.py) can apply its own timeout/keepalive logic
        around queue.get() without this module knowing about transports."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def publish(self, event: dict) -> None:
        """Fan out to every currently-subscribed queue. Never blocks, never
        raises on the caller's behalf — a full queue (a stuck/dead
        subscriber) drops that one event for that one subscriber rather
        than backing up event creation elsewhere in the app."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow/stuck subscriber — drop for them, not for anyone else

    async def subscribe(self) -> AsyncIterator[dict]:
        """Convenience async-iterator form for a caller that doesn't need
        custom timeout handling. Cleans up its queue on exit (including
        cancellation, e.g. a client disconnecting)."""
        queue = self.subscribe_queue()
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(queue)


event_bus = EventBus()
