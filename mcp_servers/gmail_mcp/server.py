"""
Gmail MCP server (Design Decisions V2.1, Decision 1).

Thin stdio wrapper around the existing, already-tested app/gmail_client.py
— same OAuth build/refresh logic and Gmail API calls as V1, just reached
through an MCP tool call instead of a direct Python call. Exposes exactly
the two tools the scan/ingestion path needs: list and get.

Credentials arrive per-invocation via env vars set by the backend at
subprocess-spawn time (Decision 4) — this process stores nothing.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mcp.server.fastmcp import FastMCP

from app.gmail_client import (
    build_credentials,
    build_gmail_service,
    fetch_message,
    list_recent_message_ids,
)

mcp = FastMCP("gmail")

# Process-lifetime cache: one subprocess is spawned per /scan request, so the
# service is built once and reused across the list + get calls in that scan.
_state = {"service": None, "creds": None, "starting_token": None}


def _get_service():
    if _state["service"] is None:
        account = SimpleNamespace(
            access_token=os.environ["GMAIL_ACCESS_TOKEN"],
            refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        )
        _state["starting_token"] = account.access_token
        creds = build_credentials(account)
        _state["service"] = build_gmail_service(creds)
        _state["creds"] = creds
    return _state["service"]


def _token_update() -> dict | None:
    """Report a rotated access token so the backend can persist it, mirroring
    V1's routes_scan.py check (`creds.token != account.access_token`) — the
    MCP server itself keeps no persistent state (Decision 4)."""
    creds = _state["creds"]
    if creds is None or creds.token == _state["starting_token"]:
        return None
    return {
        "access_token": creds.token,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


@mcp.tool()
def list_recent_messages(max_results: int = 20) -> dict:
    """List recent inbox message ids for the connected Gmail account."""
    service = _get_service()
    ids = list_recent_message_ids(service, max_results=max_results)
    return {"message_ids": ids, "token_update": _token_update()}


@mcp.tool()
def get_message(message_id: str) -> dict:
    """Fetch and parse a single Gmail message by id."""
    service = _get_service()
    fetched = fetch_message(service, message_id)
    return {
        "message_id": fetched.message_id,
        "thread_id": fetched.thread_id,
        "from_address": fetched.from_address,
        "subject": fetched.subject,
        "raw_text": fetched.raw_text,
        "is_html": fetched.is_html,
        "received_at": fetched.received_at.isoformat(),
        "token_update": _token_update(),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
