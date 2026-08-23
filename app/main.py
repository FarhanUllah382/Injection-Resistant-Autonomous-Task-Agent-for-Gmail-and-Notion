"""
FastAPI app entry point.

Single process — see CLAUDE.md V1 architectural constraints. V2.7 (Design
Decisions V2.7, Decision 1) adds the one deliberate, user-confirmed
exception to that doc's "no background workers" default: an in-process
APScheduler job (app/scheduler.py) that calls the same run_scan()/
run_extract() functions POST /scan and POST /extract already call, just on
a ~2-minute timer instead of a click. Still one process, still no new
service/port/container — just a scheduled call inside the process that was
already running. Run with: uvicorn app.main:app --reload
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import scheduler as poll_scheduler
from app.db import init_db
from app.routes_auth import router as auth_router
from app.routes_candidates import router as candidates_router
from app.routes_events import router as events_router
from app.routes_extract import router as extract_router
from app.routes_scan import router as scan_router
from app.routes_scheduling import router as scheduling_router

app = FastAPI(title="Inbox-to-Action")

# The Next.js review UI calls this API directly from the browser. Defaults
# to local dev; in production set ALLOWED_ORIGINS to a comma-separated list
# of the deployed frontend origin(s), e.g. https://inbox-to-action-web.onrender.com
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _allowed_origins.split(",") if origin.strip()],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

app.include_router(auth_router)
app.include_router(scan_router)
app.include_router(extract_router)
app.include_router(candidates_router)
app.include_router(scheduling_router)
app.include_router(events_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    poll_scheduler.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    poll_scheduler.shutdown()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/debug/anthropic-check")
def debug_anthropic_check() -> dict:
    """Temporary diagnostic — isolates network reachability to
    api.anthropic.com from API-key correctness. No key sent; a 401 means
    the connection succeeded, only auth was (expectedly) rejected. Remove
    once the Render/Anthropic connectivity issue is resolved."""
    import time

    import httpx2

    def _try(label: str, fn):
        start = time.monotonic()
        try:
            resp = fn()
            return {
                "label": label,
                "reached_anthropic": True,
                "status_code": resp.status_code,
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }
        except Exception as e:  # noqa: BLE001 — diagnostic endpoint, report anything
            return {
                "label": label,
                "reached_anthropic": False,
                "error": repr(e),
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }

    raw = _try(
        "raw_httpx2_no_client",
        lambda: httpx2.post("https://api.anthropic.com/v1/messages", json={}, timeout=15.0),
    )

    # Same Anthropic() wrapper + same custom IPv4 transport the real
    # extractor uses, but with a throwaway fake key — isolates whether the
    # SDK wrapper/custom-transport combo itself is the problem, independent
    # of whatever the real ANTHROPIC_API_KEY env var actually contains.
    from anthropic import Anthropic

    ipv4_client = httpx2.Client(transport=httpx2.HTTPTransport(local_address="0.0.0.0"))

    def _via_sdk():
        client = Anthropic(api_key="sk-ant-fake-diagnostic-key", http_client=ipv4_client, max_retries=0)
        return client.messages.with_raw_response.create(
            model="claude-sonnet-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}]
        )

    via_sdk = _try("anthropic_sdk_with_ipv4_transport_fake_key", _via_sdk)

    return {"raw": raw, "via_sdk": via_sdk}
