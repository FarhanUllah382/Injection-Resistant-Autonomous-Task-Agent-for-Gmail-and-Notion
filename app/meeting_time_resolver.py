"""
Resolve a Claude-extracted meeting-time phrase into a real datetime.

Design Decisions V2.6, Decision 3: "resolved to a real datetime by the
existing deadline_resolver.py pattern." That module only ever resolves to
a `date` (no time-of-day) and Decision 9 doesn't list it as a file this
phase may touch — so this is a *new* module that follows the same
deterministic, conservative philosophy (see deadline_resolver.py's own
docstring: "not a general natural-language date parser... anything else
resolves to None rather than guessing") extended to also parse a
time-of-day, which a meeting slot genuinely needs and a deadline doesn't.

Both a day reference AND a specific clock time must be present for a
phrase to resolve at all. A vague daypart ("Thursday afternoon") is not
resolved — turning "afternoon" into a specific time would be inventing
precision the email never stated, the same principle CLAUDE.md applies to
deadlines ("never invent a deadline that isn't stated or clearly
implied").
"""

import re
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)
_NOON_RE = re.compile(r"\bnoon\b", re.IGNORECASE)
_MIDNIGHT_RE = re.compile(r"\bmidnight\b", re.IGNORECASE)

_DAY_RE = re.compile(
    r"\b(?:(next|this)\s+)?(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def _next_weekday(today: date, qualifier: Optional[str], weekday: int) -> date:
    delta = (weekday - today.weekday()) % 7
    if qualifier == "next":
        delta = delta + 7 if delta != 0 else 7
    return today + timedelta(days=delta)


def _extract_time(text: str) -> Optional[time]:
    if _NOON_RE.search(text):
        return time(12, 0)
    if _MIDNIGHT_RE.search(text):
        return time(0, 0)
    match = _TIME_RE.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiem = match.group(3).lower()
    if hour < 1 or hour > 12 or minute > 59:
        return None
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return time(hour, minute)


def _extract_day(text: str, today: date) -> Optional[date]:
    match = _DAY_RE.search(text)
    if not match:
        return None
    qualifier = match.group(1).lower() if match.group(1) else None
    token = match.group(2).lower()
    if token == "today":
        return today
    if token == "tomorrow":
        return today + timedelta(days=1)
    return _next_weekday(today, qualifier, _WEEKDAYS[token])


def resolve_meeting_time_phrase(
    phrase: Optional[str], received_at: datetime, user_timezone: str
) -> Optional[datetime]:
    """Returns a timezone-aware datetime in `user_timezone`, or None if the
    phrase doesn't clearly specify both a day and a clock time."""
    if not phrase:
        return None

    local_now = received_at.astimezone(ZoneInfo(user_timezone))
    today = local_now.date()
    text = phrase.strip().lower()

    day = _extract_day(text, today)
    clock_time = _extract_time(text)
    if day is None or clock_time is None:
        return None

    return datetime.combine(day, clock_time, tzinfo=ZoneInfo(user_timezone))
