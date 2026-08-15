"""
Gmail API fetch + parse. Manual-trigger only — no polling, no push, no
history-sync state (see CLAUDE.md V1 constraints).
"""

import base64
import codecs
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_SCOPES
from app.models import EmailAccount


@dataclass
class FetchedMessage:
    message_id: str
    thread_id: str
    from_address: str
    subject: str
    raw_text: str
    is_html: bool
    received_at: datetime


def build_credentials(account: EmailAccount) -> Credentials:
    return Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=GOOGLE_SCOPES,
    )


def build_gmail_service(creds: Credentials):
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def list_recent_message_ids(service, max_results: int = 20) -> list[str]:
    response = service.users().messages().list(
        userId="me", labelIds=["INBOX"], maxResults=max_results
    ).execute()
    return [m["id"] for m in response.get("messages", [])]


def _charset_from_headers(headers: list) -> str:
    """Read the charset declared in a part's Content-Type header. Gmail API
    bodies aren't always UTF-8 (e.g. Windows-1252 is common), so decoding
    with a hardcoded utf-8 silently corrupts characters like smart quotes."""
    for h in headers or []:
        if h.get("name", "").lower() == "content-type":
            match = re.search(r'charset="?([\w-]+)"?', h.get("value", ""), re.IGNORECASE)
            if match:
                charset = match.group(1)
                try:
                    codecs.lookup(charset)
                    return charset
                except LookupError:
                    break
    return "utf-8"


def _decode_part(data: str, charset: str = "utf-8") -> str:
    padded = data + "=" * (-len(data) % 4)
    raw_bytes = base64.urlsafe_b64decode(padded)
    return raw_bytes.decode(charset, errors="replace")


def _extract_body(payload: dict) -> tuple[str, bool]:
    """Returns (raw_text, is_html). Prefers text/plain over text/html."""
    parts = payload.get("parts")
    if not parts:
        data = payload.get("body", {}).get("data")
        if not data:
            return "", False
        is_html = payload.get("mimeType") == "text/html"
        charset = _charset_from_headers(payload.get("headers"))
        return _decode_part(data, charset), is_html

    plain, html = None, None
    for part in parts:
        mime = part.get("mimeType")
        data = part.get("body", {}).get("data")
        charset = _charset_from_headers(part.get("headers"))
        if mime == "text/plain" and data and plain is None:
            plain = _decode_part(data, charset)
        elif mime == "text/html" and data and html is None:
            html = _decode_part(data, charset)
        elif part.get("parts"):  # nested multipart (e.g. multipart/alternative)
            nested_text, nested_is_html = _extract_body(part)
            if nested_text and not nested_is_html and plain is None:
                plain = nested_text
            elif nested_text and nested_is_html and html is None:
                html = nested_text

    if plain is not None:
        return plain, False
    if html is not None:
        return html, True
    return "", False


def fetch_message(service, message_id: str) -> FetchedMessage:
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    raw_text, is_html = _extract_body(msg["payload"])
    received_at = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc)

    return FetchedMessage(
        message_id=msg["id"],
        thread_id=msg["threadId"],
        from_address=headers.get("From", "unknown"),
        subject=headers.get("Subject", "(no subject)"),
        raw_text=raw_text,
        is_html=is_html,
        received_at=received_at,
    )
