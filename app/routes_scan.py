"""
POST /scan — Gmail -> database only.

Fetches recent inbox messages, skips ones already stored, preprocesses the
body, and saves them as Email rows. Deliberately stops there: no extraction,
no task_candidates. Synchronous, single request — no background worker
(see CLAUDE.md V1 constraints).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.gmail_client import build_credentials, build_gmail_service, fetch_message, list_recent_message_ids
from app.models import Email, EmailAccount, User
from app.preprocessing import clean_email_body

router = APIRouter(tags=["scan"])


@router.post("/scan")
def scan(max_results: int = 20, session: Session = Depends(get_session)):
    user = session.exec(select(User)).first()
    if user is None:
        raise HTTPException(400, "No user found — connect Gmail via /auth/google/login first")

    account = session.exec(
        select(EmailAccount).where(EmailAccount.user_id == user.id)
    ).first()
    if account is None:
        raise HTTPException(400, "No Gmail account connected — visit /auth/google/login first")

    creds = build_credentials(account)
    service = build_gmail_service(creds)

    # Persist a refreshed access token if the client library rotated it.
    if creds.token != account.access_token:
        account.access_token = creds.token
        if creds.expiry:
            account.token_expiry = creds.expiry
        session.add(account)
        session.commit()

    candidate_ids = list_recent_message_ids(service, max_results=max_results)

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

        fetched = fetch_message(service, message_id)
        cleaned_text = clean_email_body(fetched.raw_text, fetched.is_html)

        email = Email(
            user_id=user.id,
            email_account_id=account.id,
            message_id=fetched.message_id,
            thread_id=fetched.thread_id,
            from_address=fetched.from_address,
            subject=fetched.subject,
            raw_text=fetched.raw_text,
            cleaned_text=cleaned_text,
            received_at=fetched.received_at,
        )
        session.add(email)
        new_count += 1

    session.commit()

    return {
        "fetched": len(candidate_ids),
        "new": new_count,
        "skipped": len(candidate_ids) - new_count,
    }
