"""
FastAPI app entry point.

Single process, no background workers — see CLAUDE.md V1 architectural
constraints. Run with: uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routes_auth import router as auth_router
from app.routes_candidates import router as candidates_router
from app.routes_extract import router as extract_router
from app.routes_scan import router as scan_router

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


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
