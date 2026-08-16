"""
V2.5 Decision 6 & 7 evaluation.

Standalone script (needs DB access for the historical-candidate parts,
unlike extractor.py itself, which stays DB-independent — this script is
the caller, same role app/routes_extract.py plays in the live app).

Notes tested here are NOT written as active rows in correction_notes —
they're passed directly to extract_email() as literal strings, so nothing
here changes production behavior. See scripts/propose_correction_notes.py
for the real approval path.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.deadline_resolver import resolve_deadline_phrase
from app.policy import compute_policy
from app.sender_trust import sender_trust_signal
from phase1_extraction.extractor import extract_email

FIXTURE_PATH = Path(__file__).parent / "correction_fixture.jsonl"
TEST_EMAILS_PATH = Path(__file__).parent / "test_emails.jsonl"

SAFE_NOTE = (
    "Purely informational 'FYI' or 'heads up' emails that explicitly state no action is "
    "needed or are just status updates should not be extracted as actionable tasks, even "
    "if the system can infer a vague follow-up action."
)
RISKY_NOTE = "When an email says \"review\" without specifying who, assume it's for the user."

USER_TIMEZONE = "UTC"


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def compute_policy_for_extraction(extraction: dict, sender_email_addr: str) -> tuple:
    """Returns (reached_policy: bool, policy_decision or None). A candidate
    only reaches compute_policy() at all if actionable — mirrors
    app/routes_extract.py exactly."""
    if not extraction["actionable"]:
        return False, None
    fake_email = SimpleNamespace(from_address=sender_email_addr)
    trust = sender_trust_signal(fake_email)
    resolved = resolve_deadline_phrase(extraction.get("deadline"), datetime.now(timezone.utc), USER_TIMEZONE)
    deadline_resolved = resolved is not None
    injection_suspected = extraction.get("injection_suspected", True)
    decision = compute_policy(
        confidence=extraction.get("confidence", 0.0),
        deadline_resolved=deadline_resolved,
        assignee=extraction.get("assignee"),
        injection_suspected=injection_suspected,
        sender_trust_signal=trust,
    )
    return True, decision


# ---------------------------------------------------------------------------
# Decision 6 check 2: retroactive correction check (SAFE_NOTE)
# ---------------------------------------------------------------------------
def retroactive_check():
    print("=" * 70)
    print("DECISION 6 CHECK 2: Retroactive correction check (SAFE_NOTE, FYI fixture)")
    print("=" * 70)
    cases = load_jsonl(FIXTURE_PATH)
    all_pass = True
    for case in cases:
        email_data = {"from": case["from"], "subject": case["subject"], "body": case["body"]}
        without = extract_email(email_data, correction_notes=None)
        with_note = extract_email(email_data, correction_notes=[SAFE_NOTE])
        expected_actionable = case["human_action"] != "dismissed"  # False for all fixture cases
        ok = with_note["actionable"] == expected_actionable
        print(f"  {case['id']}: without_note.actionable={without['actionable']} "
              f"with_note.actionable={with_note['actionable']} expected={expected_actionable} "
              f"{'PASS' if ok else 'FAIL'}")
        all_pass = all_pass and ok
    print(f"\nRetroactive check: {'PASS' if all_pass else 'FAIL'} — "
          f"all fixture cases now match the human's correction with SAFE_NOTE active.\n")
    return all_pass


# ---------------------------------------------------------------------------
# Decision 6 check 2 (second half) + Decision 7 check 4:
# unrelated-candidates non-regression on the real Phase 1 15-email set
# ---------------------------------------------------------------------------
def unrelated_candidates_check(note: str, label: str):
    print("=" * 70)
    print(f"UNRELATED-CANDIDATES CHECK ({label}) — Phase 1 15-email set")
    print("=" * 70)
    cases = load_jsonl(TEST_EMAILS_PATH)
    mismatches = []
    actionable_correct = 0
    for case in cases:
        email_data = {"from": case["from"], "subject": case["subject"], "body": case["body"]}
        without = extract_email(email_data, correction_notes=None)
        with_note = extract_email(email_data, correction_notes=[note])
        true_actionable = case["label"]["actionable"]
        if with_note["actionable"] == true_actionable:
            actionable_correct += 1
        if without["actionable"] != with_note["actionable"]:
            mismatches.append((case["id"], without["actionable"], with_note["actionable"]))
            print(f"  #{case['id']}: MISMATCH without={without['actionable']} with_note={with_note['actionable']}")

    precision_recall_ok = actionable_correct == len(cases)
    print(f"\n  Unrelated-candidate actionable mismatches: {len(mismatches)} / {len(cases)}")
    print(f"  Accuracy with note active: {actionable_correct}/{len(cases)} "
          f"{'(matches 100% baseline)' if precision_recall_ok else '(REGRESSION)'}")
    return len(mismatches) == 0, precision_recall_ok


# ---------------------------------------------------------------------------
# Decision 7 check 5: behavioral policy-equivalence, notes ON vs OFF
# ---------------------------------------------------------------------------
def behavioral_policy_check(note: str, label: str, cases: list, source: str):
    """Decision 2 explicitly permits notes to change `actionable` — a note
    correctly stopping a false positive from ever reaching compute_policy()
    is the intended, allowed effect of a note, not a boundary violation.
    The actual thing Decision 2/7 check 5 must catch is a candidate that
    stays actionable under both conditions but gets a DIFFERENT
    policy_decision — that's the only category of diff that indicates
    notes are leaking into the policy layer. This function reports both
    categories separately so "notes changed actionable" (fine) is never
    conflated with "notes changed policy_decision for a still-actionable
    candidate" (the real violation)."""
    print("=" * 70)
    print(f"DECISION 7 CHECK 5: Behavioral policy-equivalence ({label}) — {source}")
    print("=" * 70)
    actionable_changed = []
    policy_flip_while_actionable = []
    for case in cases:
        email_data = {"from": case["from"], "subject": case["subject"], "body": case["body"]}
        without = extract_email(email_data, correction_notes=None)
        with_note = extract_email(email_data, correction_notes=[note])

        reached_off, policy_off = compute_policy_for_extraction(without, case["from"])
        reached_on, policy_on = compute_policy_for_extraction(with_note, case["from"])

        if reached_off != reached_on:
            category = "actionable changed (allowed per Decision 2)"
            actionable_changed.append(case["id"])
        elif reached_off and reached_on and policy_off != policy_on:
            category = "*** POLICY FLIP WHILE STILL ACTIONABLE (boundary violation) ***"
            policy_flip_while_actionable.append(case["id"])
        else:
            category = "same"
        print(f"  {case['id']}: off=[reached={reached_off}, policy={policy_off}] "
              f"on=[reached={reached_on}, policy={policy_on}]  -> {category}")

    print(f"\n  {label}: {len(actionable_changed)}/{len(cases)} cases had `actionable` change "
          f"(allowed) — {actionable_changed or 'none'}")
    print(f"  {label}: {len(policy_flip_while_actionable)}/{len(cases)} cases had a policy_decision "
          f"flip while remaining actionable (the real boundary check) — "
          f"{policy_flip_while_actionable or 'NONE — boundary holds'}")
    return actionable_changed, policy_flip_while_actionable


def main():
    results = {}

    results["retroactive"] = retroactive_check()

    unrelated_ok, precision_ok = unrelated_candidates_check(SAFE_NOTE, "SAFE_NOTE")
    results["unrelated_no_regression"] = unrelated_ok
    results["precision_recall_holds"] = precision_ok

    phase1_cases = load_jsonl(TEST_EMAILS_PATH)
    fyi_cases = load_jsonl(FIXTURE_PATH)
    combined_cases = phase1_cases + fyi_cases

    actionable_changed, policy_flips = behavioral_policy_check(
        SAFE_NOTE, "SAFE_NOTE", combined_cases, "Phase 1 set + FYI fixture"
    )
    results["safe_note_actionable_changed"] = actionable_changed
    results["safe_note_policy_boundary_violations"] = policy_flips

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
