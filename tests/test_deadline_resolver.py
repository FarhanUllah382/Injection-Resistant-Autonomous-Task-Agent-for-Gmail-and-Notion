"""
Tests for app/deadline_resolver.py's resolve_deadline_phrase() — a
deterministic, date-only resolver (never a general NL date parser; see
that module's docstring and CLAUDE.md's "Deadline is a phrase, not a
resolved date").

Fixed reference instant: 2026-11-06 12:00:00 UTC, a Friday, in UTC (no
offset to account for) so expected dates are easy to reason about.
"""

from datetime import date, datetime, timezone

from app.deadline_resolver import resolve_deadline_phrase

RECEIVED = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)  # Friday
TZ = "UTC"


def test_none_phrase_returns_none():
    assert resolve_deadline_phrase(None, RECEIVED, TZ) is None


def test_empty_phrase_returns_none():
    assert resolve_deadline_phrase("", RECEIVED, TZ) is None


def test_today():
    assert resolve_deadline_phrase("today", RECEIVED, TZ) == date(2026, 11, 6)


def test_tomorrow():
    assert resolve_deadline_phrase("tomorrow", RECEIVED, TZ) == date(2026, 11, 7)


def test_eod_means_today():
    assert resolve_deadline_phrase("EOD", RECEIVED, TZ) == date(2026, 11, 6)


def test_bare_weekday_name_this_week():
    # Received on a Friday; "Monday" means the next one, not today.
    assert resolve_deadline_phrase("Monday", RECEIVED, TZ) == date(2026, 11, 9)


def test_next_weekday_skips_an_extra_week():
    assert resolve_deadline_phrase("next Monday", RECEIVED, TZ) == date(2026, 11, 16)


def test_end_of_week_resolves_to_friday():
    assert resolve_deadline_phrase("end of week", RECEIVED, TZ) == date(2026, 11, 6)


def test_end_of_month():
    assert resolve_deadline_phrase("end of month", RECEIVED, TZ) == date(2026, 11, 30)


def test_in_n_days():
    assert resolve_deadline_phrase("in 3 days", RECEIVED, TZ) == date(2026, 11, 9)


def test_in_n_weeks():
    assert resolve_deadline_phrase("in 2 weeks", RECEIVED, TZ) == date(2026, 11, 20)


def test_explicit_month_day_future_this_year():
    assert resolve_deadline_phrase("December 1st", RECEIVED, TZ) == date(2026, 12, 1)


def test_explicit_month_day_already_passed_rolls_to_next_year():
    assert resolve_deadline_phrase("January 1st", RECEIVED, TZ) == date(2027, 1, 1)


def test_month_day_with_explicit_year():
    assert resolve_deadline_phrase("March 5, 2029", RECEIVED, TZ) == date(2029, 3, 5)


def test_month_day_wins_over_bare_weekday_in_same_phrase():
    # "Monday, August 24" must resolve to the stated date, not to "the
    # nearest Monday" — see _resolve_month_day's docstring.
    assert resolve_deadline_phrase("Monday, August 24", RECEIVED, TZ) == date(2027, 8, 24)


def test_time_bearing_phrase_still_resolves_the_date_only():
    # Deadlines stay date-only by design — clock time is a separate
    # resolver's job (app/meeting_time_resolver.py).
    assert resolve_deadline_phrase("5 PM this Friday", RECEIVED, TZ) == date(2026, 11, 6)


def test_unrecognized_phrase_returns_none_rather_than_guessing():
    assert resolve_deadline_phrase("sometime soonish", RECEIVED, TZ) is None
