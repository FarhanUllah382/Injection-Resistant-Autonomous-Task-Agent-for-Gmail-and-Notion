"""
Correction notes: storage access (Design Decisions V2.5, Decisions 4-5).

Pure DB access — no Claude calls live here (see app/correction_note_proposals.py
for that) and this module is never imported by phase1_extraction/extractor.py,
which stays DB-independent per Decision 4. The caller (app/routes_extract.py,
or an evaluation script) calls get_active_notes() and passes the result into
extractor.extract()/extract_email() as a plain list of strings.

The 5-note cap (Decision 5) lives entirely in get_active_notes()'s query —
it is read-time only and never writes to any row. The only functions that
ever change `active` are insert_active_note() (sets it True at creation)
and deactivate_note() (sets it False) — both require an explicit call,
never triggered by the cap or by anything automatic.
"""

from typing import Optional

from sqlmodel import Session, select

from app.models import CorrectionNote

ACTIVE_NOTE_LIMIT = 5


def get_active_notes(session: Session, limit: int = ACTIVE_NOTE_LIMIT) -> list[str]:
    """Read-time-only: the up-to-`limit` most-recently-approved active notes,
    as plain rule_text strings ready for extractor.py to inject. Never
    modifies any row — notes beyond the limit simply aren't selected."""
    rows = session.exec(
        select(CorrectionNote)
        .where(CorrectionNote.active == True)  # noqa: E712
        .order_by(CorrectionNote.approved_at.desc())
        .limit(limit)
    ).all()
    return [row.rule_text for row in rows]


def insert_active_note(
    session: Session, rule_text: str, source_decision_ids: list[int]
) -> CorrectionNote:
    """The only place a note becomes active — always an explicit, human-
    approved action (scripts/propose_correction_notes.py `approve`), never
    automatic."""
    note = CorrectionNote(
        rule_text=rule_text,
        source_decision_ids=source_decision_ids,
        active=True,
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def deactivate_note(session: Session, note_id: int) -> Optional[CorrectionNote]:
    """Explicit manual deactivation — never triggered by the 5-note cap."""
    note = session.get(CorrectionNote, note_id)
    if note is None:
        return None
    note.active = False
    session.add(note)
    session.commit()
    session.refresh(note)
    return note
