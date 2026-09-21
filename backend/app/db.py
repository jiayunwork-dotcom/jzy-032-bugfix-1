"""Database engine, session factory and the declarative base.

All timestamps are stored as naive UTC (``DateTime(timezone=False)``) so the
same models work identically on PostgreSQL and SQLite; :func:`utcnow` is the
single source of "now" for the whole codebase.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (canonical clock for the app)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {}
    if database_url.startswith("sqlite"):
        # Allow cross-thread use (scheduler loop + API handlers) and give
        # SQLite a generous busy timeout for concurrent short writes.
        connect_args = {"check_same_thread": False, "timeout": 30}
    return create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency yielding a short-lived session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
