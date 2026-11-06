"""
Tests for app/policy.py's compute_policy() — the shadow-mode trust/risk
rule (Design Decisions V2.3 Decisions 1-2, V2.4 Decision 4).
"""

from app.config import AUTO_CONFIDENCE_THRESHOLD
from app.policy import compute_policy

HIGH_CONFIDENCE = AUTO_CONFIDENCE_THRESHOLD + 0.01
LOW_CONFIDENCE = AUTO_CONFIDENCE_THRESHOLD - 0.1


def test_auto_eligible_in_the_lowest_stakes_case():
    decision = compute_policy(
        confidence=HIGH_CONFIDENCE,
        deadline_resolved=True,
        assignee=None,
        injection_suspected=False,
        sender_trust_signal="known",
    )
    assert decision == "auto_eligible"


def test_injection_suspected_overrides_everything_else():
    decision = compute_policy(
        confidence=1.0,
        deadline_resolved=True,
        assignee=None,
        injection_suspected=True,
        sender_trust_signal="known",
    )
    assert decision == "review_required"


def test_suspicious_sender_overrides_everything_else():
    decision = compute_policy(
        confidence=1.0,
        deadline_resolved=True,
        assignee=None,
        injection_suspected=False,
        sender_trust_signal="suspicious",
    )
    assert decision == "review_required"


def test_unresolved_deadline_forces_review():
    decision = compute_policy(
        confidence=HIGH_CONFIDENCE,
        deadline_resolved=False,
        assignee=None,
        injection_suspected=False,
        sender_trust_signal="known",
    )
    assert decision == "review_required"


def test_named_assignee_forces_review():
    decision = compute_policy(
        confidence=HIGH_CONFIDENCE,
        deadline_resolved=True,
        assignee="Sam",
        injection_suspected=False,
        sender_trust_signal="known",
    )
    assert decision == "review_required"


def test_confidence_below_auto_threshold_forces_review():
    decision = compute_policy(
        confidence=LOW_CONFIDENCE,
        deadline_resolved=True,
        assignee=None,
        injection_suspected=False,
        sender_trust_signal="known",
    )
    assert decision == "review_required"


def test_unknown_domain_sender_does_not_itself_block_auto_eligibility():
    # Only "suspicious" is a hard override — "unknown_domain" alone must
    # not prevent the lowest-stakes case from auto-qualifying.
    decision = compute_policy(
        confidence=HIGH_CONFIDENCE,
        deadline_resolved=True,
        assignee=None,
        injection_suspected=False,
        sender_trust_signal="unknown_domain",
    )
    assert decision == "auto_eligible"
