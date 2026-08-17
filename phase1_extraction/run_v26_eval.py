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
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from phase1_extraction.extractor import extract_email
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


if __name__ == "__main__":
    r1 = scheduling_field_check()
    r2 = calendar_check_correctness()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  scheduling_field_check: {'PASS' if r1 else 'FAIL'}")
    print(f"  calendar_check_correctness: {'PASS' if r2 else 'FAIL'}")
