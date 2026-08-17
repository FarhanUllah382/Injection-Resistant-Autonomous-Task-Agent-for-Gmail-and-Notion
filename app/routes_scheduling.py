"""
Calendar-booking endpoint (Design Decisions V2.6, Decision 5).

This is the ONLY code path anywhere in this codebase that calls the
Calendar MCP's create_event tool. It is a separate, explicit human action
— never bundled into approve_candidate, never reachable through
app/policy.py, AUTO_ACT_ENABLED, or any confidence threshold. Approving a
task candidate only ever creates the Notion page, exactly as before V2.6;
booking a calendar event is always this distinct endpoint, always a
distinct button click in the review UI.
"""

from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import MEETING_DURATION_MINUTES
from app.db import get_session
from app.mcp_clients import calendar_session, unwrap
from app.models import CalendarBooking, Email, EmailAccount, TaskCandidate, User

router = APIRouter(prefix="/candidates", tags=["scheduling"])


class BookCalendarRequest(BaseModel):
    slot: Optional[str] = None  # ISO datetime; defaults to the resolved proposed time


@router.post("/{candidate_id}/book-calendar")
async def book_calendar(
    candidate_id: int, body: BookCalendarRequest, session: Session = Depends(get_session)
):
    user = session.exec(select(User)).first()
    if user is None:
        raise HTTPException(400, "No user found — connect Gmail via /auth/google/login first")

    candidate = session.get(TaskCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")

    if candidate.resolved_meeting_time is None:
        raise HTTPException(400, "This candidate has no resolved meeting time to book")
    if candidate.calendar_status == "unavailable":
        raise HTTPException(400, "Calendar access is unavailable for this account")

    existing = session.exec(
        select(CalendarBooking).where(CalendarBooking.candidate_id == candidate.id)
    ).first()
    if existing is not None:
        raise HTTPException(409, "This candidate's meeting is already booked")

    # Only the originally proposed time or one of the agent's own suggested
    # alternatives may be booked — this endpoint books a slot the
    # Scheduling Agent already surfaced, never an arbitrary caller-supplied
    # time.
    valid_slots = {candidate.resolved_meeting_time.isoformat()}
    valid_slots.update(candidate.suggested_meeting_slots or [])
    chosen_slot = body.slot or candidate.resolved_meeting_time.isoformat()
    if chosen_slot not in valid_slots:
        raise HTTPException(
            400, "slot must be the proposed time or one of the suggested alternative slots"
        )

    account = session.exec(select(EmailAccount).where(EmailAccount.user_id == user.id)).first()
    if account is None:
        raise HTTPException(400, "No Gmail/Calendar account connected")

    email = session.get(Email, candidate.email_id)
    task = candidate.final_task if candidate.final_task is not None else candidate.claude_task

    if chosen_slot == candidate.resolved_meeting_time.isoformat():
        start = candidate.resolved_meeting_time
    else:
        start = datetime.fromisoformat(chosen_slot)
    end = start + timedelta(minutes=MEETING_DURATION_MINUTES)

    # Google Calendar's API rejects event times with no timezone
    # indicator at all ("Missing time zone definition for start time").
    # resolved_meeting_time / suggested_meeting_slots are naive by the
    # time they get here, but the underlying instant they represent is
    # already UTC — Postgres TIMESTAMP WITHOUT TIME ZONE stores whatever
    # SQLAlchemy handed it, and every tz-aware datetime built upstream
    # (app/meeting_time_resolver.py's ZoneInfo(user_timezone) result) gets
    # converted to UTC before the tzinfo is stripped on write. Labeling
    # these naive values with the user's *local* timezone instead of UTC
    # would silently shift the instant by the UTC offset (verified live:
    # it booked an event 5 hours off for a UTC+5 user before this fix) —
    # so UTC is attached here, not user.timezone. The slot-matching
    # comparison above deliberately stays naive-vs-naive (matching what
    # the frontend received), so this only ever happens right before the
    # actual API call, never earlier.
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt_timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt_timezone.utc)

    async with calendar_session(account.access_token, account.refresh_token) as mcp:
        result = unwrap(
            await mcp.call_tool(
                "create_event",
                {
                    "summary": task or (email.subject if email else "Meeting"),
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "description": f"Created from Inbox-to-Action candidate #{candidate.id}",
                },
            )
        )
    if "error" in result:
        raise HTTPException(502, f"Failed to create calendar event: {result['error']}")

    booking = CalendarBooking(candidate_id=candidate.id, calendar_event_id=result["event_id"])
    session.add(booking)
    session.commit()

    return {"booked": True, "calendar_event_id": result["event_id"], "start": start.isoformat()}
