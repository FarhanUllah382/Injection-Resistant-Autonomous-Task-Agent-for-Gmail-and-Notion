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

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)
_NOON_RE = re.compile(r"\bnoon\b", re.IGNORECASE)
_MIDNIGHT_RE = re.compile(r"\bmidnight\b", re.IGNORECASE)

_DAY_RE = re.compile(
    r"\b(?:(next|this)\s+)?(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_MONTH_DAY_RE = re.compile(
    r"\b([a-zA-Z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.IGNORECASE
)


def _next_weekday(today: date, qualifier: Optional[str], weekday: int) -> date:
    delta = (weekday - today.weekday()) % 7
    if qualifier == "next":
        delta = delta + 7 if delta != 0 else 7
    return today + timedelta(days=delta)


def _extract_month_day(text: str, today: date) -> Optional[date]:
    """An explicit month+day (e.g. "August 24") is unambiguous and takes
    priority over a bare weekday name — see _extract_day below for why."""
    match = _MONTH_DAY_RE.search(text)
    if not match:
        return None
    month_name = match.group(1).lower()
    if month_name not in _MONTHS:
        return None
    month = _MONTHS[month_name]
    day = int(match.group(2))
    explicit_year = match.group(3)
    year = int(explicit_year) if explicit_year else today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if not explicit_year and candidate < today:
        candidate = date(today.year + 1, month, day)
    return candidate


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
    # Explicit month+day wins whenever present — a phrase like "Monday,
    # August 24" must resolve to August 24, not to "the nearest Monday
    # from today" (which silently ignores the stated date and can be
    # wrong by up to a week if today already happens to be a Monday).
    month_day = _extract_month_day(text, today)
    if month_day is not None:
        return month_day

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
