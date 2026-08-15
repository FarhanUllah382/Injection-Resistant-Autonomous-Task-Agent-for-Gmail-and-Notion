"""
Gmail OAuth2 routes.

Single-process, single-user MVP: pending authorization state is kept in an
in-memory dict rather than a session store or Redis (see CLAUDE.md V1
constraints — no Redis, one process).
"""

from datetime import datetime, timezone as dt_timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlmodel import Session, select

from app.config import USER_TIMEZONE
from app.db import get_session
from app.gmail_oauth import build_flow
from app.models import EmailAccount, User

router = APIRouter(prefix="/auth/google", tags=["auth"])

# state -> Flow, cleared once the callback consumes it
_pending_flows: dict[str, Flow] = {}


@router.get("/login")
def login():
    flow = build_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",  # required to receive a refresh_token
        include_granted_scopes="true",
        prompt="consent",  # force consent so refresh_token is issued even on re-auth
    )
    _pending_flows[state] = flow
    return RedirectResponse(authorization_url)


@router.get("/callback")
def callback(code: str, state: str, session: Session = Depends(get_session)):
    flow = _pending_flows.pop(state, None)
    if flow is None:
        raise HTTPException(400, "Unknown or expired OAuth state")

    flow.fetch_token(code=code)
    creds = flow.credentials

    gmail = build("gmail", "v1", credentials=creds)
    profile = gmail.users().getProfile(userId="me").execute()
    gmail_address = profile["emailAddress"]

    if not USER_TIMEZONE:
        raise HTTPException(
            500,
            "USER_TIMEZONE is not set in .env — required before creating a user "
            "(no UTC fallback, see DESIGN_DECISIONS.md Decision 5)",
        )

    user = session.exec(select(User).where(User.email == gmail_address)).first()
    if user is None:
        user = User(email=gmail_address, timezone=USER_TIMEZONE)
        session.add(user)
        session.commit()
        session.refresh(user)

    token_expiry = creds.expiry
    if token_expiry and token_expiry.tzinfo is None:
        token_expiry = token_expiry.replace(tzinfo=dt_timezone.utc)

    account = session.exec(
        select(EmailAccount).where(
            EmailAccount.user_id == user.id,
            EmailAccount.gmail_address == gmail_address,
        )
    ).first()
    if account is None:
        account = EmailAccount(user_id=user.id, gmail_address=gmail_address)
        session.add(account)

    account.access_token = creds.token
    if creds.refresh_token:  # only present on first consent; don't overwrite with None
        account.refresh_token = creds.refresh_token
    account.token_expiry = token_expiry
    session.add(account)
    session.commit()

    return {"status": "connected", "gmail_address": gmail_address, "user_id": user.id}
