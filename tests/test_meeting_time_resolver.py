"""
Tests for app/meeting_time_resolver.py's resolve_meeting_time_phrase() —
only resolves when BOTH a day and a specific clock time are present
(Design Decisions V2.6, Decision 3); a vague daypart is deliberately left
unresolved rather than inventing a time (same principle as
deadline_resolver.py's "never invent a deadline").

Same fixed reference instant as test_deadline_resolver.py: 2026-11-06
12:00:00 UTC, a Friday.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.meeting_time_resolver import resolve_meeting_time_phrase

RECEIVED = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
TZ = "UTC"


def test_none_phrase_returns_none():
    assert resolve_meeting_time_phrase(None, RECEIVED, TZ) is None


def test_day_only_without_clock_time_does_not_resolve():
    # A bare day isn't a scheduling input on its own — that's a deadline,
    # handled by deadline_resolver.py instead.
    assert resolve_meeting_time_phrase("Friday", RECEIVED, TZ) is None


def test_vague_daypart_without_clock_time_does_not_resolve():
    assert resolve_meeting_time_phrase("Thursday afternoon", RECEIVED, TZ) is None


def test_clock_time_without_day_does_not_resolve():
    assert resolve_meeting_time_phrase("3pm", RECEIVED, TZ) is None


def test_explicit_day_and_time():
    result = resolve_meeting_time_phrase("5 PM this Friday", RECEIVED, TZ)
    assert result == datetime(2026, 11, 6, 17, 0, tzinfo=ZoneInfo(TZ))


def test_tomorrow_with_time():
    result = resolve_meeting_time_phrase("tomorrow at 9:30am", RECEIVED, TZ)
    assert result == datetime(2026, 11, 7, 9, 30, tzinfo=ZoneInfo(TZ))


def test_noon():
    result = resolve_meeting_time_phrase("Monday at noon", RECEIVED, TZ)
    assert result == datetime(2026, 11, 9, 12, 0, tzinfo=ZoneInfo(TZ))


def test_midnight():
    result = resolve_meeting_time_phrase("midnight on Monday", RECEIVED, TZ)
    assert result == datetime(2026, 11, 9, 0, 0, tzinfo=ZoneInfo(TZ))


def test_month_day_takes_priority_over_bare_weekday():
    result = resolve_meeting_time_phrase("Monday, August 24 at 10:00 AM", RECEIVED, TZ)
    assert result == datetime(2027, 8, 24, 10, 0, tzinfo=ZoneInfo(TZ))


def test_invalid_hour_does_not_resolve():
    assert resolve_meeting_time_phrase("13pm on Friday", RECEIVED, TZ) is None
