"""
Single-owner bearer-token auth (security hardening).

This app processes one person's inbox (see CLAUDE.md) — there is exactly
one operator who should ever be able to call these endpoints. A single
shared secret, `APP_ACCESS_TOKEN`, checked with a constant-time comparison
rather than `==` (which short-circuits on the first mismatched byte and can
leak timing information about the secret).

Fails closed: if `APP_ACCESS_TOKEN` is unset or shorter than
`_MIN_TOKEN_LENGTH` characters, every protected request is rejected — a
missing or weak token must never silently fall back to "no auth required."

The one deliberate exception is DEMO_MODE (app/config.py): that mode
exists specifically to be a public, no-login demo in front of synthetic
data and a fake in-memory Notion (app/demo_data.py, app/demo_notion.py) —
every write it can reach is harmless by construction, so both dependencies
below pass through unconditionally when it's on, same as the real
instance's token check is fail-closed when it's off.
"""

import hmac
import os

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import DEMO_MODE

_MIN_TOKEN_LENGTH = 32

_bearer_scheme = HTTPBearer(auto_error=False)


def _configured_token() -> str | None:
    token = os.getenv("APP_ACCESS_TOKEN")
    if not token or len(token) < _MIN_TOKEN_LENGTH:
        return None
    return token


def _matches(candidate: str | None) -> bool:
    expected = _configured_token()
    if expected is None or not candidate:
        return False
    return hmac.compare_digest(candidate, expected)


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Standard dependency for every protected route: `Authorization:
    Bearer <token>` header only."""
    if DEMO_MODE:
        return
    if not _matches(credentials.credentials if credentials else None):
        raise HTTPException(401, "Missing or invalid access token")


def require_token_header_or_query(request: Request) -> None:
    """Same check as require_token(), but also accepts a `?token=`
    query parameter. Needed only for GET /events: the browser's native
    EventSource API cannot send a custom Authorization header. A
    query-string token is more likely to end up in a proxy or access log
    than a header — an accepted tradeoff for this single SSE endpoint on a
    single-owner app, not used anywhere else."""
    if DEMO_MODE:
        return
    auth_header = request.headers.get("authorization", "")
    header_token = auth_header[7:] if auth_header.lower().startswith("bearer ") else None
    query_token = request.query_params.get("token")
    if _matches(header_token) or _matches(query_token):
        return
    raise HTTPException(401, "Missing or invalid access token")
