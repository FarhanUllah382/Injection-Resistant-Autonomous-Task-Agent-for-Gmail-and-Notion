"""
Shared pytest setup.

Every env var that app/config.py or app/db.py reads at import time must be
set *before* anything under app/ is imported for the first time — so this
file sets them as its very first action. A fresh sqlite file per test
session keeps this independent of a running Postgres/docker-compose
instance (CLAUDE.md Phase 1 principle: tests shouldn't need the full
stack), while still exercising the real SQLModel schema via init_db().
"""

import os
import tempfile
from pathlib import Path

_TEST_DB_PATH = Path(tempfile.gettempdir()) / "inbox_to_action_test.db"
_TEST_DB_PATH.unlink(missing_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ.setdefault("APP_ACCESS_TOKEN", "test-access-token-" + "x" * 20)
os.environ.setdefault("USER_TIMEZONE", "UTC")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DEMO_MODE", "false")

import pytest  # noqa: E402 — must follow the env setup above
from fastapi.testclient import TestClient  # noqa: E402

VALID_TOKEN = os.environ["APP_ACCESS_TOKEN"]


@pytest.fixture()
def client():
    from app.main import app  # imported here, after env vars are set

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers():
    return {"Authorization": f"Bearer {VALID_TOKEN}"}
