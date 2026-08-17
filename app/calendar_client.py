"""
Google Calendar API fetch + create. Mirrors app/gmail_client.py's pattern
exactly (Design Decisions V2.6, Decision 1) — same OAuth credential
construction, same google-api-python-client usage, just a different API
surface (calendar v3 instead of gmail v1).

CalendarUnavailableError is raised specifically when the connected
account's token lacks Calendar scope (V2.6 Decision 2's graceful-
degradation requirement) — callers (app/scheduling.py) catch this
specifically and treat it as "skip scheduling, don't fail the request,"
never as a generic error.
"""

from dataclasses import dataclass
from datetime import datetime

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_SCOPES
from app.models import EmailAccount


class CalendarUnavailableError(Exception):
    """The connected account hasn't granted Calendar scope yet (or Calendar
    access otherwise failed with a permissions error). Never treated as a
    hard failure — see app/scheduling.py."""
    pass


@dataclass
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime


def build_credentials(account: EmailAccount) -> Credentials:
    """Same account, same token, same scopes list as app/gmail_client.py —
    Calendar and Gmail share one OAuth grant (V2.6 Decision 2 extends the
    existing consent request rather than starting a second auth flow)."""
    return Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=GOOGLE_SCOPES,
    )


def build_calendar_service(creds: Credentials):
    """A refresh_token granted only for Gmail's old scope list can't be
    refreshed against a Credentials object that now also requests Calendar
    scope — Google's token endpoint rejects the whole refresh with
    invalid_scope (a RefreshError, not an HttpError, and it happens before
    any Calendar API call is even made). That's exactly the "hasn't
    granted Calendar scope yet" case Decision 2 requires degrading
    gracefully from, so it's caught here too, not just HttpError below."""
    try:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
    except RefreshError as e:
        raise CalendarUnavailableError(str(e)) from e
    return build("calendar", "v3", credentials=creds)


def _is_insufficient_scope(error: HttpError) -> bool:
    if error.resp is not None and error.resp.status in (401, 403):
        reason = str(error).lower()
        return "insufficient" in reason or "scope" in reason or "forbidden" in reason
    return False


def list_events(service, time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
    """Busy events on the primary calendar in [time_min, time_max].

    A token that never had Calendar scope granted doesn't fail with an
    HttpError at all — googleapiclient lazily refreshes the access token
    inside .execute() itself, and that refresh is rejected by Google's
    token endpoint with a RefreshError (invalid_scope) before any HTTP
    request to the Calendar API is even made. Both exception types map to
    the same graceful-degradation outcome (Decision 2)."""
    try:
        response = service.events().list(
            calendarId="primary",
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except RefreshError as e:
        raise CalendarUnavailableError(str(e)) from e
    except HttpError as e:
        if _is_insufficient_scope(e):
            raise CalendarUnavailableError(str(e)) from e
        raise

    events = []
    for item in response.get("items", []):
        start_raw = item.get("start", {}).get("dateTime")
        end_raw = item.get("end", {}).get("dateTime")
        if not start_raw or not end_raw:
            continue  # all-day events have no dateTime; skip for free/busy purposes
        events.append(
            CalendarEvent(
                summary=item.get("summary", "(no title)"),
                start=datetime.fromisoformat(start_raw),
                end=datetime.fromisoformat(end_raw),
            )
        )
    return events


def create_event(
    service, summary: str, start: datetime, end: datetime, description: str = ""
) -> str:
    """Creates a real calendar event. Only ever called after the explicit,
    separate human approval step (Decision 5) — see app/routes_scheduling.py,
    the only caller anywhere in this codebase."""
    try:
        event = service.events().insert(
            calendarId="primary",
            body={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        ).execute()
    except RefreshError as e:
        raise CalendarUnavailableError(str(e)) from e
    except HttpError as e:
        if _is_insufficient_scope(e):
            raise CalendarUnavailableError(str(e)) from e
        raise
    return event["id"]
