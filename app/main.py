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

# Local-dev only: the Next.js review UI (localhost:3000) calls this API
# (localhost:8000) directly from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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
