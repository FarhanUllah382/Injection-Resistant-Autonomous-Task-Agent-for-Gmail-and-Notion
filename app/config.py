"""
App Configuration (Phase 2+)
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Anthropic API (reused from Phase 1)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-sonnet-5"

# Extraction parameters (reused from Phase 1)
THREAD_CONTEXT_DEPTH = 5
CONFIDENCE_THRESHOLD = 0.7

# Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Single MVP test user. V1 processes one person's inbox (see CLAUDE.md); the
# user's IANA timezone must be explicit, never defaulted to UTC (Decision 5).
USER_TIMEZONE = os.getenv("USER_TIMEZONE")

# Notion (Phase 4)
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Triage (V2.2) — deterministic pre-filter ahead of extraction (Design
# Decisions V2.2, Decision 2). Empty blocklist by default: matches Decision
# 3's fail-open policy — nothing is blocked by domain until the user
# explicitly configures one. User-editable, same convention as
# CONFIDENCE_THRESHOLD.
TRIAGE_BLOCKED_DOMAINS: list[str] = []
ACTION_KEYWORDS = ["please", "review", "due", "deadline", "assign"]
