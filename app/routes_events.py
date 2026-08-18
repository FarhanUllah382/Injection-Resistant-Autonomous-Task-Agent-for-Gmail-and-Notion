"""
Live updates for the review UI (Design Decisions V2.7, Decision 5).

GET /events streams Server-Sent Events from app/events.py's in-process bus
— chosen over WebSockets because every message flows server->client only
("a new candidate arrived," "Gmail needs reconnecting"), never the other
way (Decision 5's rationale). Non-interruptive by design: this endpoint
only ever pushes notifications, never state the client is required to act
on immediately.

GET /scheduler/status is a small addition beyond Decision 5's literal
scope: SSE has no replay, so a tab opened *after* an auth failure fired
(V2.7 Decision 2's "reconnect Gmail" prompt) would otherwise never learn
about it. This mirrors how GET /candidates already gives a freshly-opened
tab the current pending count — same "catch up on load" idea, applied to
the one other piece of state (poll health) that isn't naturally covered by
an existing endpoint.
"""

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import scheduler
from app.events import event_bus

router = APIRouter(tags=["events"])

_KEEPALIVE_SECONDS = 15


@router.get("/events")
async def stream_events():
    async def event_stream():
        queue = event_bus.subscribe_queue()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/scheduler/status")
def scheduler_status():
    return scheduler.get_status()
