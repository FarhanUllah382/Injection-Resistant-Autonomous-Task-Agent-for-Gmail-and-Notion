"""
Stdio MCP client helpers (Design Decisions V2.1, Decisions 3 & 4).

The backend spawns each MCP server as a local subprocess over stdio — no
networked service, nothing added to docker-compose.yml. Credentials are
passed per-invocation via env vars at spawn time, sourced from the existing
token store (DB / app.config) — the MCP server process itself stores
nothing persistently.

This module only opens sessions and unwraps tool results; it has no
knowledge of Gmail/Notion business logic — that stays in
mcp_servers/*/server.py (which reuses app/gmail_client.py and
app/notion_client.py unchanged).
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GMAIL_SERVER = _REPO_ROOT / "mcp_servers" / "gmail_mcp" / "server.py"
_NOTION_SERVER = _REPO_ROOT / "mcp_servers" / "notion_mcp" / "server.py"
_CALENDAR_SERVER = _REPO_ROOT / "mcp_servers" / "calendar_mcp" / "server.py"


def _spawn_env(extra: dict) -> dict:
    env = dict(os.environ)
    env.update(extra)
    return env


def unwrap(result: CallToolResult) -> dict[str, Any]:
    if result.isError:
        text = result.content[0].text if result.content else "MCP tool call failed"
        raise RuntimeError(text)
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


@asynccontextmanager
async def gmail_session(access_token: str, refresh_token: str):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(_GMAIL_SERVER)],
        env=_spawn_env(
            {
                "GMAIL_ACCESS_TOKEN": access_token,
                "GMAIL_REFRESH_TOKEN": refresh_token or "",
            }
        ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def notion_session(api_key: str, database_id: str):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(_NOTION_SERVER)],
        env=_spawn_env(
            {
                "NOTION_API_KEY": api_key,
                "NOTION_DATABASE_ID": database_id,
            }
        ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def calendar_session(access_token: str, refresh_token: str):
    """Same account/token as gmail_session (V2.6 Decision 2 extends the
    existing OAuth grant rather than a second auth flow) — a separate MCP
    server process regardless, same isolation as every other server."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(_CALENDAR_SERVER)],
        env=_spawn_env(
            {
                "CALENDAR_ACCESS_TOKEN": access_token,
                "CALENDAR_REFRESH_TOKEN": refresh_token or "",
            }
        ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
