"""
Database engine and session management.
"""

from sqlmodel import SQLModel, Session, create_engine

from app.config import DATABASE_URL

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to .env, "
        "e.g. postgresql://user:password@localhost:5432/inbox_to_action"
    )

engine = create_engine(DATABASE_URL, echo=False)


def init_db() -> None:
    """Create tables that don't exist yet. No migration framework in v1."""
    import app.models  # noqa: F401 — ensure models are registered before create_all

    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
