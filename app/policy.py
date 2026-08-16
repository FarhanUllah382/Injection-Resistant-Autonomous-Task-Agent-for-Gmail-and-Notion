"""
Trust/risk policy engine (Design Decisions V2.3 Decisions 1-2, V2.4
Decision 4).

Answers exactly one question: should this candidate be eligible to skip
human review before its Notion page is created? Not a generic multi-action
risk engine — there is exactly one write action in this system (Notion
task creation via app/notion_client.py), so this is the only thing the
policy ever gates.

Still shadow mode only (V2.3 Decision 5). This function's result is
computed and stored on every candidate (see app/routes_extract.py), but
nothing in the approval flow branches on it yet, and no code path in this
codebase creates a Notion page without going through the existing human
`POST /candidates/{id}/approve` endpoint. AUTO_ACT_ENABLED (app/config.py)
stays False; the real auto-create/undo mechanism described in V2.3
Decision 3 is deliberately deferred until that flag's flip is separately
approved, and not before this phase's own evaluation (V2.4 Decision 6)
passes clean.

V2.4 adds two hard overrides (Decision 4), grounded in candidate id=9: a
well-formed, high-confidence, resolvable-deadline, no-assignee request
that would have been auto_eligible under V2.3 alone, but came from a
spoofed identity. `injection_suspected` (from extraction_prompt.py) and
sender_trust_signal == "suspicious" (app/sender_trust.py) each force
review_required regardless of every other signal — they are overrides,
not additional weights in a score.
"""

from typing import Literal, Optional

from app.config import AUTO_CONFIDENCE_THRESHOLD
from app.sender_trust import SenderTrust

PolicyDecision = Literal["auto_eligible", "review_required"]


def compute_policy(
    confidence: float,
    deadline_resolved: bool,
    assignee: Optional[str],
    injection_suspected: bool,
    sender_trust_signal: SenderTrust,
) -> PolicyDecision:
    """Narrow, auditable rule — not a scored/weighted model (V2.3 Decision
    2). A candidate is only ever auto-eligible in the lowest-stakes case:
    high confidence, a resolvable deadline, no named person to
    misattribute, no suspected injection, and no sender-identity red flag."""
    if injection_suspected or sender_trust_signal == "suspicious":
        return "review_required"  # hard override — nothing else matters
    if not deadline_resolved:
        return "review_required"  # incomplete data, never auto-act
    if confidence >= AUTO_CONFIDENCE_THRESHOLD and assignee is None:
        return "auto_eligible"
    return "review_required"  # default: ask a human
