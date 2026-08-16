"""
Trust/risk policy engine (Design Decisions V2.3, Decisions 1-2).

Answers exactly one question: should this candidate be eligible to skip
human review before its Notion page is created? Not a generic multi-action
risk engine — there is exactly one write action in this system (Notion
task creation via app/notion_client.py), so this is the only thing the
policy ever gates.

V2.3 ships in shadow mode only (Decision 5). This function's result is
computed and stored on every candidate (see app/routes_extract.py), but
nothing in the approval flow branches on it yet, and no code path in this
codebase creates a Notion page without going through the existing human
`POST /candidates/{id}/approve` endpoint. AUTO_ACT_ENABLED (app/config.py)
stays False; the real auto-create/undo mechanism described in Decision 3
is deliberately deferred until that flag's flip is separately approved.
"""

from typing import Literal, Optional

from app.config import AUTO_CONFIDENCE_THRESHOLD

PolicyDecision = Literal["auto_eligible", "review_required"]


def compute_policy(
    confidence: float,
    deadline_resolved: bool,
    assignee: Optional[str],
) -> PolicyDecision:
    """Narrow, auditable rule — not a scored/weighted model (Decision 2).
    A candidate is only ever auto-eligible in the lowest-stakes case: high
    confidence, a resolvable deadline, and no named person to misattribute."""
    if not deadline_resolved:
        return "review_required"  # incomplete data, never auto-act
    if confidence >= AUTO_CONFIDENCE_THRESHOLD and assignee is None:
        return "auto_eligible"
    return "review_required"  # default: ask a human
