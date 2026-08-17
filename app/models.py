"""
Database models.

Schema matches the data model in CLAUDE.md: users, email_accounts, emails,
task_candidates, user_decisions, notion_tasks. Do not add tables or fields
speculatively — see CLAUDE.md "Data model" before expanding this.

Note: this follows CLAUDE.md's notion_tasks-as-a-separate-table design
(candidate -> notion page id + sync status), not DESIGN_DECISIONS.md's
draft of putting notion_page_id directly on task_candidates. CLAUDE.md
overrides where the two disagree; flagged here since the draft doc still
shows the old version.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    timezone: str  # IANA timezone, e.g. "America/New_York" — required, no UTC fallback
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EmailAccount(SQLModel, table=True):
    __tablename__ = "email_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    gmail_address: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expiry: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Email(SQLModel, table=True):
    __tablename__ = "emails"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="unique_user_message"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    email_account_id: int = Field(foreign_key="email_accounts.id")
    message_id: str = Field(index=True)  # Gmail API message id
    thread_id: str = Field(index=True)  # Gmail API thread id
    from_address: str
    subject: str
    raw_text: str  # original from Gmail (HTML + signatures)
    cleaned_text: str  # after preprocessing
    received_at: datetime
    extracted_at: Optional[datetime] = None  # set once extraction succeeds; null means "not yet processed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaskCandidate(SQLModel, table=True):
    __tablename__ = "task_candidates"

    id: Optional[int] = Field(default=None, primary_key=True)
    email_id: int = Field(foreign_key="emails.id")

    # Claude's original extraction (immutable once written)
    claude_task: Optional[str] = None
    claude_deadline_phrase: Optional[str] = None
    claude_assignee: Optional[str] = None
    claude_reason: str
    claude_confidence: float

    # User's final version — null until edited; approval falls back to claude_* fields
    final_task: Optional[str] = None
    final_deadline_phrase: Optional[str] = None
    final_assignee: Optional[str] = None

    # Deterministic, app-computed from deadline_phrase + email.received_at + user timezone.
    # Never set by Claude. Null if it can't be safely resolved.
    resolved_due_date: Optional[date] = None

    # Trust/risk policy output (V2.3, Decisions 2 & 4) — computed once at
    # candidate creation (app/routes_extract.py) via app/policy.py, stored
    # here so shadow-mode reporting is a simple query. Shadow mode only:
    # nothing currently branches on this value, and `status` never becomes
    # anything other than what V1 already produces (see AUTO_ACT_ENABLED
    # in app/config.py).
    policy_decision: Optional[str] = None  # "auto_eligible" | "review_required"
    deadline_resolved: Optional[bool] = None

    # Scheduling Agent output (V2.6, Decisions 3-4). claude_* immutable once
    # written, same convention as the task/deadline/assignee fields above.
    # resolved_meeting_time is app-computed by app/meeting_time_resolver.py
    # (never by Claude), null if the phrase couldn't be safely resolved.
    # calendar_status / suggested_meeting_slots are computed once at
    # candidate creation by app/scheduling.py — "unavailable" means the
    # connected account hasn't granted Calendar scope yet (Decision 2),
    # not an error. None of this ever books anything — see
    # app/routes_scheduling.py for the only code path that can.
    proposed_meeting_phrase: Optional[str] = None
    resolved_meeting_time: Optional[datetime] = None
    calendar_status: Optional[str] = None  # "free" | "conflict" | "unavailable" | None
    suggested_meeting_slots: Optional[list] = Field(default=None, sa_column=Column(JSON))
    # V2.6 scheduling correction: proposed_meeting_phrase/resolved_meeting_time
    # above are now populated from EITHER an explicit meeting proposal OR a
    # time-bearing deadline (e.g. "5 PM this Friday") when no meeting was
    # proposed — meeting stays strictly primary when both are present. This
    # field records which one actually produced the value, purely for
    # accurate UI labeling — it changes no resolution or policy behavior.
    scheduling_source: Optional[str] = None  # "meeting" | "deadline" | None

    status: str = Field(default="pending")  # pending | edited | approved | dismissed
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserDecision(SQLModel, table=True):
    __tablename__ = "user_decisions"

    id: Optional[int] = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="task_candidates.id")
    user_id: int = Field(foreign_key="users.id")
    action: str  # approved | edited | dismissed
    changed_fields: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    decided_at: datetime = Field(default_factory=datetime.utcnow)


class NotionTask(SQLModel, table=True):
    __tablename__ = "notion_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="task_candidates.id", unique=True)
    notion_page_id: str
    sync_status: str  # e.g. "synced" | "failed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CorrectionNote(SQLModel, table=True):
    """
    Approved correction notes (V2.5, Decision 4). Only ever contains notes
    that a human has already explicitly approved — see app/correction_notes.py
    and scripts/propose_correction_notes.py. There is no "proposed but
    undecided" state stored here; proposals live only transiently (printed
    output) until a human approves one, at which point a row is inserted
    directly with active=True.

    `active` is only ever changed by an explicit user action (approve or
    deactivate) — never automatically, including by the 5-note read-time
    cap (Design Decisions V2.5, Decision 5) applied in
    app/correction_notes.py.get_active_notes().
    """

    __tablename__ = "correction_notes"

    id: Optional[int] = Field(default=None, primary_key=True)
    rule_text: str
    # Which user_decisions rows this was derived from — JSON, consistent
    # with UserDecision.changed_fields (Decision 4).
    source_decision_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = Field(default=True)


class CalendarBooking(SQLModel, table=True):
    """
    Records a real calendar event created via the explicit, separate
    approval action (V2.6, Decision 5) — same role NotionTask plays for
    Notion pages. A row here only ever exists because a human clicked
    "Also add to calendar"; nothing else in this codebase writes one.
    """

    __tablename__ = "calendar_bookings"

    id: Optional[int] = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="task_candidates.id", unique=True)
    calendar_event_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
