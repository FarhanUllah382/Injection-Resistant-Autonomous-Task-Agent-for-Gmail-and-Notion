"""
Triage pre-filter (Design Decisions V2.2, Decisions 1-3).

Deterministic, cheap heuristic filter that runs ahead of the existing
Extraction Agent (see app/routes_extract.py) — no LLM call, no MCP call.
Only obviously non-actionable emails are skipped; anything uncertain
proceeds to extraction unchanged (extraction_prompt.py / extractor.py are
untouched — Triage only decides which emails reach them, per Decision 4).

False negatives here (a real task silently skipped before extraction or
the user ever sees it) are the primary risk this module exists to guard
against — worse than false positives, which only cost one avoidable
Claude call (Decision 3). Every code path below either returns True on a
clear, deterministic match or returns False — nothing is skipped on
uncertainty or error.

Note: Decision 2's original heuristic list also included a
`List-Unsubscribe` header check. That header isn't captured anywhere in
the pipeline — app/gmail_client.py's FetchedMessage and the `emails`
table only carry From/Subject — and adding it would mean extending the
Gmail fetch path and/or schema, both out of bounds for V2.2. Dropped for
now per explicit sign-off; revisit if the fetch path is ever deliberately
extended.
"""

import re
from email.utils import parseaddr

from app.config import ACTION_KEYWORDS, TRIAGE_BLOCKED_DOMAINS

_NOREPLY_RE = re.compile(r"^(no-?reply|notifications)@", re.IGNORECASE)


def should_triage_out(email) -> bool:
    """Returns True only if `email` should be SKIPPED (not sent to
    extraction). Returns False for anything uncertain — Triage never
    substitutes its own judgment for extraction's `actionable` field, it
    only avoids calling that logic on obvious non-actionable mail."""
    try:
        _, address = parseaddr(email.from_address or "")
        address = address.lower()
        _, _, domain = address.partition("@")

        if domain and domain in TRIAGE_BLOCKED_DOMAINS:
            return True

        if _NOREPLY_RE.match(address):
            subject = (email.subject or "").lower()
            if not any(keyword in subject for keyword in ACTION_KEYWORDS):
                return True

        return False
    except Exception:
        # Fail open (Decision 3): any triage error must never suppress a
        # real task — let it through to extraction instead.
        return False
