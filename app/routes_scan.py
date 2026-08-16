"""
POST /scan — Gmail -> database only.

Fetches recent inbox messages, skips ones already stored, preprocesses the
body, and saves them as Email rows. Deliberately stops there: no extraction,
no task_candidates. Synchronous-per-request, single request — no background
worker (see CLAUDE.md V1 constraints); `async def` here is just how the
route awaits the Gmail MCP subprocess call (Design Decisions V2.1, Decision
5), not a background task.

Gmail fetch calls go through the Gmail MCP server (mcp_servers/gmail_mcp),
which wraps app/gmail_client.py unchanged — same OAuth/token/dedup logic as
V1, new transport (Decisions 1 & 3).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.mcp_clients import gmail_session, unwrap
from app.models import Email, EmailAccount, User
from app.preprocessing import clean_email_body

router = APIRouter(tags=["scan"])


def _persist_token_update(session: Session, account: EmailAccount, token_update: dict | None) -> None:
    """Persist a rotated Gmail access token reported by the MCP server —
    mirrors V1's `creds.token != account.access_token` check, just fed by
    the MCP tool response instead of a local Credentials object."""
    if not token_update or token_update["access_token"] == account.access_token:
        return
    account.access_token = token_update["access_token"]
    if token_update.get("expiry"):
        account.token_expiry = datetime.fromisoformat(token_update["expiry"])
    session.add(account)
    session.commit()


@router.post("/scan")
async def scan(max_results: int = 20, session: Session = Depends(get_session)):
    user = session.exec(select(User)).first()
    if user is None:
        raise HTTPException(400, "No user found — connect Gmail via /auth/google/login first")

    account = session.exec(
        select(EmailAccount).where(EmailAccount.user_id == user.id)
    ).first()
    if account is None:
        raise HTTPException(400, "No Gmail account connected — visit /auth/google/login first")

    async with gmail_session(account.access_token, account.refresh_token) as mcp:
        list_result = unwrap(await mcp.call_tool("list_recent_messages", {"max_results": max_results}))
        _persist_token_update(session, account, list_result.get("token_update"))

        candidate_ids = list_result["message_ids"]

        already_stored = set(
            session.exec(
                select(Email.message_id).where(
                    Email.user_id == user.id,
                    Email.message_id.in_(candidate_ids),
                )
            ).all()
        )

        new_count = 0
        for message_id in candidate_ids:
            if message_id in already_stored:
                continue

            fetched = unwrap(await mcp.call_tool("get_message", {"message_id": message_id}))
            _persist_token_update(session, account, fetched.get("token_update"))

            cleaned_text = clean_email_body(fetched["raw_text"], fetched["is_html"])

            email = Email(
                user_id=user.id,
                email_account_id=account.id,
                message_id=fetched["message_id"],
                thread_id=fetched["thread_id"],
                from_address=fetched["from_address"],
                subject=fetched["subject"],
                raw_text=fetched["raw_text"],
                cleaned_text=cleaned_text,
                received_at=datetime.fromisoformat(fetched["received_at"]),
            )
            session.add(email)
            new_count += 1

        session.commit()

    return {
        "fetched": len(candidate_ids),
        "new": new_count,
        "skipped": len(candidate_ids) - new_count,
    }
