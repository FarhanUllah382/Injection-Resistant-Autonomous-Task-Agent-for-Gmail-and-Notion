"""
Notion MCP server (Design Decisions V2.1, Decision 2).

Decision 2 says to adopt Notion's official MCP server if it fits our
schema, else fall back to a thin custom wrapper (same pattern as Decision
1). The official `@notionhq/notion-mcp-server` package fits the schema
(verified: our database's single data source has exactly the Name/Due
Date/Assignee/Source Email/Reason properties app/notion_client.py already
builds) but is an npm/Node.js package, and this environment has no
Node.js runtime. Per that fallback clause, this is a thin custom Python
MCP wrapper around the existing, already-tested app/notion_client.py —
same Notion SDK call as V1, just reached through an MCP tool call instead
of a direct Python call.

Credentials arrive per-invocation via env vars set by the backend at
subprocess-spawn time (Decision 4) — this process stores nothing.
"""

import sys
from datetime import date as date_type
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mcp.server.fastmcp import FastMCP

from app.notion_client import NotionSyncError, create_task_page

mcp = FastMCP("notion")


@mcp.tool()
def create_notion_task(
    task: str,
    reason: str,
    gmail_link: str,
    resolved_due_date: Optional[str] = None,
    assignee: Optional[str] = None,
) -> dict:
    """Create a task page in the Notion database. resolved_due_date, if
    given, is an ISO calendar date string (e.g. "2026-08-20")."""
    due = date_type.fromisoformat(resolved_due_date) if resolved_due_date else None
    try:
        page_id = create_task_page(
            task=task,
            resolved_due_date=due,
            assignee=assignee,
            reason=reason,
            gmail_link=gmail_link,
        )
    except NotionSyncError as e:
        return {"error": str(e)}
    return {"page_id": page_id}


if __name__ == "__main__":
    mcp.run(transport="stdio")
