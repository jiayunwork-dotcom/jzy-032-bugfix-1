"""FastAPI application entrypoint.

Lifespan: wait for the database, create tables, then start the scheduler —
whose first action is recovering unfinished runs from the database so a
restart resumes work instead of losing it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import SessionLocal, engine, init_db
from .routes import graphs, runs
from .scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")


async def wait_for_db(timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # DB not up yet (compose startup race)
            if time.monotonic() > deadline:
                raise
            log.info("waiting for database: %s", exc)
            await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await wait_for_db(settings.db_connect_timeout)
    init_db()
    scheduler: Scheduler | None = None
    if settings.scheduler_enabled:
        scheduler = Scheduler(SessionLocal, tick_interval=settings.tick_interval)
        await scheduler.start()
        app.state.scheduler = scheduler
        log.info("scheduler started (tick=%.2fs)", settings.tick_interval)
    yield
    if scheduler is not None:
        await scheduler.stop()


app = FastAPI(title="DAG 任务编排调度平台", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graphs.router)
app.include_router(runs.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
