"""Application configuration, sourced from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # SQLAlchemy database URL. Docker Compose points this at PostgreSQL 16;
    # the test-suite overrides it with SQLite.
    database_url: str = "postgresql+psycopg://dag:dag@localhost:5432/dag"
    # Scheduler tick period in seconds (how often runs are re-evaluated).
    tick_interval: float = 0.1
    # Whether the background scheduler loop is started with the app.
    # Disabled in API tests that only exercise validation.
    scheduler_enabled: bool = True
    # Seconds to wait for the database to accept connections at startup.
    db_connect_timeout: float = 30.0


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", Settings.database_url),
        tick_interval=float(os.environ.get("TICK_INTERVAL", Settings.tick_interval)),
        scheduler_enabled=os.environ.get("SCHEDULER_ENABLED", "1") not in ("0", "false", "no"),
        db_connect_timeout=float(os.environ.get("DB_CONNECT_TIMEOUT", Settings.db_connect_timeout)),
    )


settings = load_settings()
