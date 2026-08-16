"""
POST /extract — stored emails -> task_candidates.

Reuses the Phase 1 extractor unchanged. Deliberately stops at candidate
creation: no approval/edit logic and no Notion sync here (see CLAUDE.md
build order — those are separate phases). Synchronous, single request,
one email at a time — no background worker.

Ahead of extraction, each email passes through Triage (app/triage.py) —
a deterministic pre-filter, no LLM call (Design Decisions V2.2). Only
obviously non-actionable emails are skipped; extraction_prompt.py and
extractor.py are otherwise reached exactly as in V2.1, unchanged.

Each actionable candidate also gets a shadow-mode policy_decision (Design
Decisions V2.3, Decisions 1-2 & 4) via app/policy.py — computed and
stored for later reporting, but never acted on: AUTO_ACT_ENABLED is False
(app/config.py), so `status` is always "pending" here, exactly as before
V2.3. See app/policy.py's docstring for why.
"""

from datetime import datetime, timezone as dt_timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.config import THREAD_CONTEXT_DEPTH
from app.db import get_session
from app.deadline_resolver import resolve_deadline_phrase
from app.models import Email, TaskCandidate, User
from app.policy import compute_policy
from app.triage import should_triage_out
from phase1_extraction.extractor import Extractor, ExtractionError

router = APIRouter(tags=["extract"])


def _build_thread_context(session: Session, email: Email) -> str:
    prior = session.exec(
        select(Email)
        .where(
            Email.thread_id == email.thread_id,
            Email.user_id == email.user_id,
            Email.id != email.id,
            Email.received_at < email.received_at,
        )
        .order_by(Email.received_at.desc())
        .limit(THREAD_CONTEXT_DEPTH)
    ).all()

    if not prior:
        return ""

    prior.reverse()  # chronological order
    blocks = [
        f"[{e.received_at.isoformat()}] From: {e.from_address}\nSubject: {e.subject}\n{e.cleaned_text}"
        for e in prior
    ]
    return "\n\n---\n\n".join(blocks)


@router.post("/extract")
def extract(max_emails: int = 20, session: Session = Depends(get_session)):
    user = session.exec(select(User)).first()
    if user is None:
        return {
            "processed": 0,
            "candidates_created": 0,
            "not_actionable": 0,
            "triaged_out": 0,
            "failed": 0,
        }

    pending = session.exec(
        select(Email)
        .where(Email.user_id == user.id, Email.extracted_at == None)  # noqa: E711
        .order_by(Email.received_at.asc())
        .limit(max_emails)
    ).all()

    extractor = Extractor()
    candidates_created = 0
    not_actionable = 0
    triaged_out = 0
    failed = 0

    for email in pending:
        if should_triage_out(email):
            print(f"[extract] email {email.id} ({email.subject!r}) triaged out — skipped extraction")
            triaged_out += 1
            email.extracted_at = datetime.now(dt_timezone.utc)
            session.add(email)
            session.commit()
            continue

        thread_context = _build_thread_context(session, email)
        email_data = {
            "from": email.from_address,
            "subject": email.subject,
            "body": email.cleaned_text,
        }

        try:
            result = extractor.extract(email_data, thread_context)
        except ExtractionError as e:
            print(f"[extract] email {email.id} ({email.subject!r}) failed: {e}")
            failed += 1
            continue  # leave extracted_at null so it's retried on the next /extract call

        email.extracted_at = datetime.now(dt_timezone.utc)
        session.add(email)

        if result["actionable"]:
            candidates_created += 1
            resolved_due_date = resolve_deadline_phrase(
                result["deadline"], email.received_at, user.timezone
            )
            deadline_resolved = resolved_due_date is not None
            candidate = TaskCandidate(
                email_id=email.id,
                claude_task=result["task"],
                claude_deadline_phrase=result["deadline"],
                claude_assignee=result["assignee"],
                claude_reason=result["reason"],
                claude_confidence=result["confidence"],
                resolved_due_date=resolved_due_date,
                policy_decision=compute_policy(
                    confidence=result["confidence"],
                    deadline_resolved=deadline_resolved,
                    assignee=result["assignee"],
                ),
                deadline_resolved=deadline_resolved,
                status="pending",  # shadow mode only — see module docstring
            )
            session.add(candidate)
        else:
            not_actionable += 1

        session.commit()

    return {
        "processed": len(pending) - failed,
        "candidates_created": candidates_created,
        "not_actionable": not_actionable,
        "triaged_out": triaged_out,
        "failed": failed,
    }
