"""
Calendar MCP server (Design Decisions V2.6, Decision 1).

Thin stdio wrapper around app/calendar_client.py — exact same shape as
mcp_servers/gmail_mcp/server.py. Exposes exactly two tools:
  list_events   — free/busy check for a window (read-only)
  create_event  — books a real event

create_event exists here as a capability, but nothing in this codebase
calls it except app/routes_scheduling.py's explicit, separate human-
approval endpoint (Decision 5) — there is no other call site anywhere,
by construction (verified via grep, see the final regression report).

Credentials arrive per-invocation via env vars set by the backend at
subprocess-spawn time (same pattern as Decision 4 of V2.1) — this process
stores nothing.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mcp.server.fastmcp import FastMCP

from app.calendar_client import (
    CalendarUnavailableError,
    build_calendar_service,
    build_credentials,
    create_event as _create_event,
    list_events as _list_events,
)

mcp = FastMCP("calendar")

_state = {"service": None, "creds": None, "starting_token": None}


def _get_service():
    if _state["service"] is None:
        account = SimpleNamespace(
            access_token=os.environ["CALENDAR_ACCESS_TOKEN"],
            refresh_token=os.environ["CALENDAR_REFRESH_TOKEN"],
        )
        _state["starting_token"] = account.access_token
        creds = build_credentials(account)
        _state["service"] = build_calendar_service(creds)
        _state["creds"] = creds
    return _state["service"]


def _token_update() -> dict | None:
    creds = _state["creds"]
    if creds is None or creds.token == _state["starting_token"]:
        return None
    return {
        "access_token": creds.token,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


@mcp.tool()
def list_events(start: str, end: str) -> dict:
    """List busy events on the primary calendar between ISO 8601 start and
    end datetimes. Returns {"unavailable": true} if the account hasn't
    granted Calendar scope, rather than an error (Decision 2)."""
    try:
        service = _get_service()
        events = _list_events(service, datetime.fromisoformat(start), datetime.fromisoformat(end))
    except CalendarUnavailableError:
        return {"unavailable": True, "events": [], "token_update": None}

    return {
        "unavailable": False,
        "events": [
            {"summary": e.summary, "start": e.start.isoformat(), "end": e.end.isoformat()}
            for e in events
        ],
        "token_update": _token_update(),
    }


@mcp.tool()
def create_event(summary: str, start: str, end: str, description: str = "") -> dict:
    """Books a real event on the primary calendar. Only ever invoked after
    explicit human approval — see app/routes_scheduling.py."""
    try:
        service = _get_service()
        event_id = _create_event(
            service, summary, datetime.fromisoformat(start), datetime.fromisoformat(end), description
        )
    except CalendarUnavailableError as e:
        return {"error": f"calendar_unavailable: {e}"}

    return {"event_id": event_id, "token_update": _token_update()}


if __name__ == "__main__":
    mcp.run(transport="stdio")
