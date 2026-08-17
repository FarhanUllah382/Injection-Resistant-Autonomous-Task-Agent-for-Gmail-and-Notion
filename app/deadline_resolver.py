"""
Resolve a Claude-extracted deadline phrase into a calendar date.

Deterministic and rule-based on purpose — not a general natural-language
date parser (see CLAUDE.md "Deadline is a phrase, not a resolved date").
Only handles common, unambiguous phrasing; anything else resolves to None
rather than guessing.
"""

import re
from datetime import date, datetime, timedelta
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

_WEEKDAY_RE = re.compile(
    r"^(?:(next|this)\s+)?(\w+?)(?:\s+(?:morning|afternoon|evening|eod))?$"
)
_RELATIVE_DAYS_RE = re.compile(r"^in\s+(\d+)\s+days?$")
_RELATIVE_WEEKS_RE = re.compile(r"^in\s+(\d+)\s+weeks?$")
_MONTH_DAY_RE = re.compile(r"^([a-zA-Z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?$")

# Fallback only — searches for a day reference anywhere in the phrase,
# rather than requiring the whole string to be just the day (see the
# fallback branch at the end of resolve_deadline_phrase for why).
_TODAY_TOMORROW_SEARCH_RE = re.compile(r"\b(today|tomorrow)\b", re.IGNORECASE)
_MONTH_DAY_SEARCH_RE = re.compile(
    r"\b([a-zA-Z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.IGNORECASE
)
_WEEKDAY_SEARCH_RE = re.compile(
    r"\b(?:(next|this)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def _next_weekday(today: date, qualifier: Optional[str], weekday: int) -> date:
    delta = (weekday - today.weekday()) % 7
    if qualifier == "next":
        delta = delta + 7 if delta != 0 else 7
    return today + timedelta(days=delta)


def _resolve_month_day(match: re.Match, today: date) -> Optional[date]:
    """Shared by the exact-match branch and the search-based fallback
    below. An explicit month+day is unambiguous, so this always takes
    priority over a bare weekday name when both are present in the same
    phrase (e.g. "Monday, August 24" must resolve to August 24, not to
    "the nearest Monday from today" — that silently ignores the stated
    date and can be wrong by up to a week, as it originally was for
    exactly this phrase)."""
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


def _end_of_month(today: date) -> date:
    if today.month == 12:
        return date(today.year, 12, 31)
    next_month_first = date(today.year, today.month + 1, 1)
    return next_month_first - timedelta(days=1)


def resolve_deadline_phrase(
    phrase: Optional[str], received_at: datetime, user_timezone: str
) -> Optional[date]:
    if not phrase:
        return None

    local_now = received_at.astimezone(ZoneInfo(user_timezone))
    today = local_now.date()
    text = phrase.strip().lower()

    if text in ("today", "eod", "end of day"):
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if "end of week" in text:
        return _next_weekday(today, None, _WEEKDAYS["friday"])
    if "end of month" in text:
        return _end_of_month(today)

    match = _RELATIVE_DAYS_RE.match(text)
    if match:
        return today + timedelta(days=int(match.group(1)))

    match = _RELATIVE_WEEKS_RE.match(text)
    if match:
        return today + timedelta(weeks=int(match.group(1)))

    match = _WEEKDAY_RE.match(text)
    if match and match.group(2) in _WEEKDAYS:
        return _next_weekday(today, match.group(1), _WEEKDAYS[match.group(2)])

    match = _MONTH_DAY_RE.match(text)
    if match:
        resolved = _resolve_month_day(match, today)
        if resolved is not None:
            return resolved

    # Fallback: phrases that pair a specific day with a time of day (e.g.
    # "5 PM this Friday", "3pm on Thursday", "Monday 9am"), or that pair
    # an explicit month+day with extra text (e.g. "Monday, August 24 at
    # 10:00 AM"), don't fullmatch any branch above, since none of them
    # expect a leading/trailing clock-time token or surrounding words —
    # they'd otherwise incorrectly resolve to None, or (worse) resolve to
    # the wrong date via the weekday-only check below, even though a
    # specific date is clearly stated. This searches for a date reference
    # alone and resolves just the date, ignoring any time-of-day text
    # elsewhere in the phrase — this function stays date-only by design
    # (V1 Decision 5: "deadline is a phrase, not a resolved date"). The
    # clock-time itself is resolved separately, only when treated as a
    # scheduling input — see app/meeting_time_resolver.py. Runs last,
    # after every exact-match branch above, so it only adds coverage for
    # phrases that would otherwise return None — it never changes an
    # already-resolved result. Month+day is checked before a bare weekday
    # name — see _resolve_month_day's docstring for why the order matters.
    match = _TODAY_TOMORROW_SEARCH_RE.search(text)
    if match:
        return today if match.group(1).lower() == "today" else today + timedelta(days=1)

    match = _MONTH_DAY_SEARCH_RE.search(text)
    if match:
        resolved = _resolve_month_day(match, today)
        if resolved is not None:
            return resolved

    match = _WEEKDAY_SEARCH_RE.search(text)
    if match:
        qualifier = match.group(1).lower() if match.group(1) else None
        weekday = match.group(2).lower()
        return _next_weekday(today, qualifier, _WEEKDAYS[weekday])

    return None
