"""
Scheduling Agent (Design Decisions V2.6, Decision 4).

Self-contained: given a candidate with a resolved proposed meeting time,
checks the user's calendar and either confirms the slot is free or
suggests up to 3 alternative business-hour slots later the same week —
simple nearest-free-slot search, no optimization across constraints
(Decision 4's own explicit scope limit).

Never books anything. This module only ever calls the Calendar MCP's
list_events (read-only) tool. create_event is called from exactly one
place in this codebase: app/routes_scheduling.py's explicit, separate
human-approval endpoint (Decision 5) — never from here.

Runs on every actionable candidate with a resolved meeting time,
regardless of injection_suspected / sender_trust_signal / policy_decision
(Decision 6) — those signals don't currently gate candidate *creation* at
all in this codebase (they only affect compute_policy(), which never
auto-acts anyway), so there's nothing for the Scheduling Agent to
additionally filter on. A security-flagged candidate still goes through
normal human review; the suggestion is just extra context alongside it,
never a bypass.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, tzinfo as tzinfo_type
from typing import Literal

from app.config import BUSINESS_HOURS_END, BUSINESS_HOURS_START, MEETING_DURATION_MINUTES
from app.mcp_clients import calendar_session, unwrap

CalendarStatus = Literal["free", "conflict", "unavailable"]


@dataclass
class SchedulingResult:
    status: CalendarStatus
    suggested_slots: list[datetime] = field(default_factory=list)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _end_of_week(day):
    """Friday of the same week as `day` (Mon=0..Sun=6); if already past
    Friday, there's no more business-hour room left that week."""
    days_to_friday = 4 - day.weekday()
    return day + timedelta(days=max(days_to_friday, 0))


def _find_alternative_slots(
    proposed_start: datetime,
    duration_minutes: int,
    busy_events: list[tuple[datetime, datetime]],
    tz: tzinfo_type,
) -> list[datetime]:
    """Walks forward through business hours, same week, in
    duration_minutes increments, skipping weekends and anything before the
    originally proposed time or overlapping a busy event. Stops at 3."""
    slots: list[datetime] = []
    day = proposed_start.date()
    week_end = _end_of_week(day)

    candidate_day = day
    while candidate_day <= week_end and len(slots) < 3:
        if candidate_day.weekday() < 5:  # Monday-Friday only
            slot_start = datetime.combine(candidate_day, time(BUSINESS_HOURS_START, 0), tzinfo=tz)
            day_end = datetime.combine(candidate_day, time(BUSINESS_HOURS_END, 0), tzinfo=tz)
            while slot_start + timedelta(minutes=duration_minutes) <= day_end and len(slots) < 3:
                slot_end = slot_start + timedelta(minutes=duration_minutes)
                if slot_start >= proposed_start:
                    conflict = any(_overlaps(slot_start, slot_end, b_s, b_e) for b_s, b_e in busy_events)
                    if not conflict:
                        slots.append(slot_start)
                slot_start += timedelta(minutes=duration_minutes)
        candidate_day += timedelta(days=1)

    return slots


async def check_availability(
    access_token: str,
    refresh_token: str,
    proposed_start: datetime,
    duration_minutes: int = MEETING_DURATION_MINUTES,
) -> SchedulingResult:
    proposed_end = proposed_start + timedelta(minutes=duration_minutes)
    day = proposed_start.date()
    week_end = _end_of_week(day)
    window_start = datetime.combine(day, time(0, 0), tzinfo=proposed_start.tzinfo)
    window_end = datetime.combine(week_end, time(23, 59), tzinfo=proposed_start.tzinfo)

    async with calendar_session(access_token, refresh_token) as mcp:
        result = unwrap(
            await mcp.call_tool(
                "list_events",
                {"start": window_start.isoformat(), "end": window_end.isoformat()},
            )
        )

    if result.get("unavailable"):
        return SchedulingResult(status="unavailable")

    busy_events = [
        (datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"]))
        for e in result.get("events", [])
    ]

    if not any(_overlaps(proposed_start, proposed_end, b_s, b_e) for b_s, b_e in busy_events):
        return SchedulingResult(status="free")

    alternatives = _find_alternative_slots(proposed_start, duration_minutes, busy_events, proposed_start.tzinfo)
    return SchedulingResult(status="conflict", suggested_slots=alternatives)
