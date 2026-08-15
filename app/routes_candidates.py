"""
Candidate review endpoints: list / edit / approve / dismiss.

This is the API surface for Phase 3's review UI — list candidates,
approve/edit/dismiss — but no UI here and no Notion writes on approve
(see CLAUDE.md build order; Notion sync is Phase 4). Confidence
thresholding happens here, at query time, not at candidate-creation time
(see app/routes_extract.py) — CONFIDENCE_THRESHOLD only ever filters what
gets surfaced for review.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, and_, or_, select

from app.config import CONFIDENCE_THRESHOLD
from app.db import get_session
from app.deadline_resolver import resolve_deadline_phrase
from app.models import Email, TaskCandidate, User, UserDecision

router = APIRouter(prefix="/candidates", tags=["candidates"])


def _gmail_link(message_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{message_id}"


def _get_single_user(session: Session) -> User:
    user = session.exec(select(User)).first()
    if user is None:
        raise HTTPException(400, "No user found — connect Gmail via /auth/google/login first")
    return user


def _get_candidate(session: Session, candidate_id: int) -> TaskCandidate:
    candidate = session.get(TaskCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    return candidate


def _serialize(candidate: TaskCandidate, email: Email) -> dict:
    return {
        "id": candidate.id,
        "status": candidate.status,
        "task": candidate.final_task if candidate.final_task is not None else candidate.claude_task,
        "deadline_phrase": (
            candidate.final_deadline_phrase
            if candidate.final_deadline_phrase is not None
            else candidate.claude_deadline_phrase
        ),
        "resolved_due_date": candidate.resolved_due_date,
        "assignee": (
            candidate.final_assignee if candidate.final_assignee is not None else candidate.claude_assignee
        ),
        "confidence": candidate.claude_confidence,
        "reason": candidate.claude_reason,
        "created_at": candidate.created_at,
        "email": {
            "subject": email.subject,
            "from_address": email.from_address,
            "received_at": email.received_at,
            "gmail_link": _gmail_link(email.message_id),
        },
    }


@router.get("")
def list_candidates(status: Optional[str] = None, session: Session = Depends(get_session)):
    query = select(TaskCandidate, Email).join(Email, TaskCandidate.email_id == Email.id)

    if status is not None:
        # Explicit status requested (e.g. "approved", "dismissed") — exact match,
        # no threshold. Once a status is decided, confidence no longer matters.
        query = query.where(TaskCandidate.status == status)
    else:
        # Default "review queue": freshly-extracted candidates above the confidence
        # threshold, plus anything already edited. An edited candidate has already
        # been looked at by a human, so it stays in the queue regardless of its
        # original confidence — otherwise editing one would silently vanish it
        # from view with no way to ever approve or dismiss it.
        query = query.where(
            or_(
                and_(
                    TaskCandidate.status == "pending",
                    TaskCandidate.claude_confidence >= CONFIDENCE_THRESHOLD,
                ),
                TaskCandidate.status == "edited",
            )
        )

    query = query.order_by(TaskCandidate.claude_confidence.desc())

    rows = session.exec(query).all()
    return [_serialize(candidate, email) for candidate, email in rows]


class CandidateEdit(BaseModel):
    task: Optional[str] = None
    deadline_phrase: Optional[str] = None
    assignee: Optional[str] = None


@router.patch("/{candidate_id}")
def edit_candidate(candidate_id: int, edit: CandidateEdit, session: Session = Depends(get_session)):
    user = _get_single_user(session)
    candidate = _get_candidate(session, candidate_id)

    changed_fields = {}
    provided = edit.model_dump(exclude_unset=True)

    if "task" in provided:
        old = candidate.final_task if candidate.final_task is not None else candidate.claude_task
        if edit.task != old:
            changed_fields["task"] = {"old": old, "new": edit.task}
        candidate.final_task = edit.task

    if "deadline_phrase" in provided:
        old = (
            candidate.final_deadline_phrase
            if candidate.final_deadline_phrase is not None
            else candidate.claude_deadline_phrase
        )
        if edit.deadline_phrase != old:
            changed_fields["deadline_phrase"] = {"old": old, "new": edit.deadline_phrase}
        candidate.final_deadline_phrase = edit.deadline_phrase

    if "assignee" in provided:
        old = candidate.final_assignee if candidate.final_assignee is not None else candidate.claude_assignee
        if edit.assignee != old:
            changed_fields["assignee"] = {"old": old, "new": edit.assignee}
        candidate.final_assignee = edit.assignee

    if not changed_fields:
        return _serialize(candidate, session.get(Email, candidate.email_id))

    candidate.status = "edited"
    session.add(candidate)
    session.add(
        UserDecision(
            candidate_id=candidate.id,
            user_id=user.id,
            action="edited",
            changed_fields=changed_fields,
        )
    )
    session.commit()
    session.refresh(candidate)

    return _serialize(candidate, session.get(Email, candidate.email_id))


@router.post("/{candidate_id}/approve")
def approve_candidate(candidate_id: int, session: Session = Depends(get_session)):
    user = _get_single_user(session)
    candidate = _get_candidate(session, candidate_id)
    email = session.get(Email, candidate.email_id)

    if candidate.status == "approved":
        raise HTTPException(409, "Candidate is already approved")
    if candidate.status == "dismissed":
        raise HTTPException(409, "Candidate was dismissed — cannot approve")

    deadline_phrase = (
        candidate.final_deadline_phrase
        if candidate.final_deadline_phrase is not None
        else candidate.claude_deadline_phrase
    )
    candidate.resolved_due_date = resolve_deadline_phrase(deadline_phrase, email.received_at, user.timezone)
    candidate.status = "approved"
    session.add(candidate)
    session.add(
        UserDecision(candidate_id=candidate.id, user_id=user.id, action="approved", changed_fields=None)
    )
    session.commit()
    session.refresh(candidate)

    return _serialize(candidate, email)


@router.post("/{candidate_id}/dismiss")
def dismiss_candidate(candidate_id: int, session: Session = Depends(get_session)):
    user = _get_single_user(session)
    candidate = _get_candidate(session, candidate_id)

    if candidate.status == "approved":
        raise HTTPException(409, "Candidate is already approved — cannot dismiss")

    candidate.status = "dismissed"
    session.add(candidate)
    session.add(
        UserDecision(candidate_id=candidate.id, user_id=user.id, action="dismissed", changed_fields=None)
    )
    session.commit()
    session.refresh(candidate)

    return _serialize(candidate, session.get(Email, candidate.email_id))
