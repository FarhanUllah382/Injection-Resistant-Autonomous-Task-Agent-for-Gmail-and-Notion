"""
Notion API client — creates a task page on approve (Phase 4).

Field mapping is fixed against the actual "Inbox Tasks" database schema:
Name (title), Due Date (date), Assignee (rich_text), Source Email (url),
Reason (rich_text). See CLAUDE.md "Notion integration" — this is the only
Notion write path; nothing else in the app calls the Notion API.
"""

from datetime import date as date_type
from typing import Optional

from notion_client import Client
from notion_client.errors import APIResponseError

from app.config import NOTION_API_KEY, NOTION_DATABASE_ID

_client = Client(auth=NOTION_API_KEY)


class NotionSyncError(Exception):
    pass


def create_task_page(
    task: str,
    resolved_due_date: Optional[date_type],
    assignee: Optional[str],
    reason: str,
    gmail_link: str,
) -> str:
    """Create the task page in Notion and return its page id."""
    properties = {
        "Name": {"title": [{"text": {"content": task}}]},
        "Source Email": {"url": gmail_link},
        "Reason": {"rich_text": [{"text": {"content": reason}}]},
    }
    if resolved_due_date is not None:
        properties["Due Date"] = {"date": {"start": resolved_due_date.isoformat()}}
    if assignee:
        properties["Assignee"] = {"rich_text": [{"text": {"content": assignee}}]}

    try:
        page = _client.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=properties,
        )
    except APIResponseError as e:
        raise NotionSyncError(str(e)) from e

    return page["id"]
