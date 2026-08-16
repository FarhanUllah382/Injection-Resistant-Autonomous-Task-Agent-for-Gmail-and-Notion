"""
V2.5 stress test: does Decision 7 check 5 actually catch a policy-relevant
shift when one is real, not just report "SAME" unconditionally?

Uses Decision 1's own second example note ("assume it's for the user"),
which the design review flagged as a plausible way a note could shift
actionable/confidence for ambiguous-addressee emails and, downstream,
compute_policy()'s output — without ever touching app/policy.py's code.
Deliberately adversarial; not proposed as a real note anywhere.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from phase1_extraction.run_v25_eval import compute_policy_for_extraction, RISKY_NOTE
from phase1_extraction.extractor import extract_email

STRESS_CASES = [
    {
        "id": "risky-1",
        "from": "colleague@example.com",
        "subject": "Deck review",
        "body": "Team, attaching the deck for review. Appreciate eyes on it by Friday before it goes out.",
    },
    {
        "id": "risky-2",
        "from": "colleague@example.com",
        "subject": "Draft ready",
        "body": "All, draft is attached. A review before end of week would be great before we circulate it further.",
    },
    {
        "id": "risky-3",
        "from": "colleague@example.com",
        "subject": "PR up for the release",
        "body": "Posting here in case anyone has bandwidth — PR is up for the release branch. Review before Friday would help us stay on schedule.",
    },
    {
        "id": "risky-4",
        "from": "colleague@example.com",
        "subject": "Proposal draft",
        "body": "Sharing the proposal draft with the group. Would be great to get a review in before Thursday's client call.",
    },
]


def main():
    diffs = []
    for case in STRESS_CASES:
        email_data = {"from": case["from"], "subject": case["subject"], "body": case["body"]}
        without = extract_email(email_data, correction_notes=None)
        with_note = extract_email(email_data, correction_notes=[RISKY_NOTE])

        reached_off, policy_off = compute_policy_for_extraction(without, case["from"])
        reached_on, policy_on = compute_policy_for_extraction(with_note, case["from"])

        same = (reached_off == reached_on) and (policy_off == policy_on)
        print(f"{case['id']}:")
        print(f"  without_note: actionable={without['actionable']} confidence={without['confidence']} "
              f"assignee={without['assignee']!r} -> reached_policy={reached_off} policy={policy_off}")
        print(f"  with_risky_note: actionable={with_note['actionable']} confidence={with_note['confidence']} "
              f"assignee={with_note['assignee']!r} -> reached_policy={reached_on} policy={policy_on}")
        print(f"  {'SAME' if same else '*** DIFFERENT ***'}\n")
        if not same:
            diffs.append(case["id"])

    print(f"RISKY_NOTE caused a policy-outcome change on {len(diffs)}/{len(STRESS_CASES)} cases: {diffs}")
    if diffs:
        print("This is the EXPECTED result — it proves the check 5 mechanism actually detects a real "
              "policy-relevant shift when one exists, rather than always reporting 'no difference.'")
    else:
        print("No shift detected on these particular cases — inconclusive for the stress test either way "
              "(doesn't prove the check is broken, just that these specific inputs didn't trigger a shift).")


if __name__ == "__main__":
    main()
