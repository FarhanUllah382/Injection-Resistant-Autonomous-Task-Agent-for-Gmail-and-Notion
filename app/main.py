"""
FastAPI app entry point.

Single process, no background workers — see CLAUDE.md V1 architectural
constraints. Run with: uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.db import init_db
from app.routes_auth import router as auth_router
from app.routes_candidates import router as candidates_router
from app.routes_extract import router as extract_router
from app.routes_scan import router as scan_router

app = FastAPI(title="Inbox-to-Action")
app.include_router(auth_router)
app.include_router(scan_router)
app.include_router(extract_router)
app.include_router(candidates_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
