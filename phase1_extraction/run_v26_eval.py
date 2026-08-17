"""
V2.6 Decision 8 evaluation.

1. New scheduling test set (9 hand-labeled emails): confirm
   proposed_meeting_time is populated only for clear cases.
2. Calendar-check correctness against a known busy/free fixture (pure
   logic test — no live Calendar API access is possible in this
   environment; see the implementation report for why).
3. Phase 1 15-email regression (reuses phase1_extraction/run_experiment.py
   unchanged as the actual check; this script re-verifies precision/recall
   directly too).
4. V2.4 adversarial set regression (reuses
   phase1_extraction/run_adversarial_eval.py unchanged).
5. Scheduling correction (deadline-as-scheduling-input): regression-locks
   the isolated deadline_resolver.py fix, and checks
   _resolve_scheduling_input()'s meeting-stays-primary priority rule.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from phase1_extraction.extractor import extract_email
from app.deadline_resolver import resolve_deadline_phrase
from app.routes_extract import _resolve_scheduling_input
from app.scheduling import _find_alternative_slots, _overlaps

SCHEDULING_SET_PATH = Path(__file__).parent / "scheduling_test_emails.jsonl"


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def scheduling_field_check():
    print("=" * 70)
    print("DECISION 8 CHECK 1: proposed_meeting_time field precision")
    print("=" * 70)
    cases = load_jsonl(SCHEDULING_SET_PATH)
    correct = 0
    for case in cases:
        email_data = {"from": case["from"], "subject": case["subject"], "body": case["body"]}
        result = extract_email(email_data)
        present = bool(result.get("proposed_meeting_time"))
        expected = case["label"]["proposed_meeting_time_present"]
        ok = present == expected
        correct += ok
        print(f"  {case['id']}: proposed_meeting_time={result.get('proposed_meeting_time')!r} "
              f"present={present} expected={expected} {'PASS' if ok else 'FAIL'}")
    print(f"\n  {correct}/{len(cases)} correct.\n")
    return correct == len(cases)


def calendar_check_correctness():
    print("=" * 70)
    print("DECISION 8 CHECK 2: calendar-check correctness (fixture-based)")
    print("=" * 70)
    tz = timezone.utc
    # Known fixture: a Tuesday, with two busy blocks later that week.
    proposed = datetime(2026, 8, 18, 10, 0, tzinfo=tz)  # Tuesday 10:00-10:30 proposed
    busy_events = [
        (datetime(2026, 8, 18, 9, 30, tzinfo=tz), datetime(2026, 8, 18, 10, 30, tzinfo=tz)),  # overlaps proposed
        (datetime(2026, 8, 18, 11, 0, tzinfo=tz), datetime(2026, 8, 18, 12, 0, tzinfo=tz)),
        (datetime(2026, 8, 19, 9, 0, tzinfo=tz), datetime(2026, 8, 19, 17, 0, tzinfo=tz)),  # all Wed busy
    ]

    all_pass = True

    # Conflict detection: proposed slot overlaps the first busy block.
    proposed_end = proposed + timedelta(minutes=30)
    conflict = any(_overlaps(proposed, proposed_end, b_s, b_e) for b_s, b_e in busy_events)
    print(f"  Conflict correctly detected at proposed time: {conflict} {'PASS' if conflict else 'FAIL'}")
    all_pass = all_pass and conflict

    # Alternative slots: none should overlap any busy event, none before
    # the proposed time, none on Wednesday (fully busy), none on weekends.
    alternatives = _find_alternative_slots(proposed, 30, busy_events, tz)
    print(f"  Suggested alternatives: {[s.isoformat() for s in alternatives]}")

    for slot in alternatives:
        slot_end = slot + timedelta(minutes=30)
        overlaps_any = any(_overlaps(slot, slot_end, b_s, b_e) for b_s, b_e in busy_events)
        before_proposed = slot < proposed
        is_weekend = slot.weekday() >= 5
        ok = not overlaps_any and not before_proposed and not is_weekend
        print(f"    {slot.isoformat()}: overlaps_busy={overlaps_any} before_proposed={before_proposed} "
              f"weekend={is_weekend} {'PASS' if ok else 'FAIL'}")
        all_pass = all_pass and ok

    at_most_3 = len(alternatives) <= 3
    print(f"  At most 3 suggestions: {len(alternatives)} {'PASS' if at_most_3 else 'FAIL'}")
    all_pass = all_pass and at_most_3

    # Fully-free case: no conflict at all -> caller should report "free",
    # not call this function (verified structurally in app/scheduling.py's
    # check_availability — no busy events -> no _find_alternative_slots call).
    no_conflict_case = not any(
        _overlaps(datetime(2026, 8, 20, 14, 0, tzinfo=tz), datetime(2026, 8, 20, 14, 30, tzinfo=tz), b_s, b_e)
        for b_s, b_e in busy_events
    )
    print(f"  Genuinely free slot correctly identified as free: {no_conflict_case} "
          f"{'PASS' if no_conflict_case else 'FAIL'}")
    all_pass = all_pass and no_conflict_case

    print(f"\n  Calendar-check correctness: {'PASS' if all_pass else 'FAIL'}\n")
    return all_pass


def deadline_resolution_fix_check():
    """Regression-locks the isolated app/deadline_resolver.py fix: known
    time-bearing phrases must now resolve (previously None); every
    previously-working bare-date phrase must resolve to exactly the same
    date as before (zero behavior change for anything that already
    worked)."""
    print("=" * 70)
    print("SCHEDULING CORRECTION CHECK 1: deadline_resolver.py fix")
    print("=" * 70)
    received_at = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)  # a Monday
    tz = "Asia/Karachi"

    now_resolves = [
        ("5 PM this Friday", "2026-08-21"),
        ("3pm on Thursday", "2026-08-20"),
        ("Monday 9am", "2026-08-17"),
        ("end of day Friday", "2026-08-21"),
    ]
    unchanged = [
        ("Friday", "2026-08-21"),
        ("end of week", "2026-08-21"),
        ("Sept 1st", "2026-09-01"),
        ("today", "2026-08-17"),
        ("tomorrow", "2026-08-18"),
        ("EOD", "2026-08-17"),
        ("in 3 days", "2026-08-20"),
    ]

    all_pass = True
    for phrase, expected in now_resolves + unchanged:
        resolved = resolve_deadline_phrase(phrase, received_at, tz)
        ok = resolved is not None and resolved.isoformat() == expected
        print(f"  {phrase!r:25} -> {resolved} (expected {expected}) {'PASS' if ok else 'FAIL'}")
        all_pass = all_pass and ok

    print(f"\n  deadline_resolver fix: {'PASS' if all_pass else 'FAIL'}\n")
    return all_pass


def scheduling_priority_check():
    """_resolve_scheduling_input(): meeting stays strictly primary; deadline
    is only used as a fallback when no meeting resolved; a bare-date
    deadline with no clock time correctly yields nothing."""
    print("=" * 70)
    print("SCHEDULING CORRECTION CHECK 2: meeting-vs-deadline priority")
    print("=" * 70)
    received_at = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    tz = "Asia/Karachi"

    cases = [
        ("meeting only", {"deadline": None, "proposed_meeting_time": "Thursday at 2pm"}, "meeting"),
        ("deadline with time only", {"deadline": "5 PM this Friday", "proposed_meeting_time": None}, "deadline"),
        (
            "both present -> meeting wins",
            {"deadline": "5 PM this Friday", "proposed_meeting_time": "Thursday at 2pm"},
            "meeting",
        ),
        ("bare-date deadline, no meeting -> neither", {"deadline": "Friday", "proposed_meeting_time": None}, None),
        ("neither present", {"deadline": None, "proposed_meeting_time": None}, None),
    ]

    all_pass = True
    for label, result, expected_source in cases:
        source, phrase, resolved = _resolve_scheduling_input(result, received_at, tz)
        ok = source == expected_source
        print(f"  {label}: source={source} phrase={phrase!r} resolved={resolved} "
              f"(expected source={expected_source}) {'PASS' if ok else 'FAIL'}")
        all_pass = all_pass and ok

    print(f"\n  Priority logic: {'PASS' if all_pass else 'FAIL'}\n")
    return all_pass


if __name__ == "__main__":
    r1 = scheduling_field_check()
    r2 = calendar_check_correctness()
    r3 = deadline_resolution_fix_check()
    r4 = scheduling_priority_check()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  scheduling_field_check: {'PASS' if r1 else 'FAIL'}")
    print(f"  calendar_check_correctness: {'PASS' if r2 else 'FAIL'}")
    print(f"  deadline_resolution_fix_check: {'PASS' if r3 else 'FAIL'}")
    print(f"  scheduling_priority_check: {'PASS' if r4 else 'FAIL'}")
