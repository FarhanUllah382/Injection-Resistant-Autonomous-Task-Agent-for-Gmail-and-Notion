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
