"""Shared helpers for scheduler/recovery tests: in-memory SQLite session
factories, compact graph builders and async waiters."""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Attempt, Graph, GraphEdge, GraphNode, Run
from app.service import create_run

TERMINAL_RUN_STATUSES = ("succeeded", "failed")


def make_session_factory() -> sessionmaker:
    """A fresh in-memory SQLite database (single shared connection)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def build_graph(
    sf: sessionmaker,
    nodes: dict[str, dict],
    edges: list[tuple[str, str]],
    max_parallel: int = 4,
) -> int:
    """Create a graph from a compact spec: {key: {duration, fail_times,
    always_fail, max_retries, interval}} and [(from, to), ...]."""
    with sf() as s:
        g = Graph(name="test-graph", max_parallel=max_parallel)
        for key, cfg in nodes.items():
            g.nodes.append(
                GraphNode(
                    node_key=key,
                    name=key,
                    duration_seconds=cfg.get("duration", 0.02),
                    fail_times=cfg.get("fail_times", 0),
                    always_fail=cfg.get("always_fail", False),
                    max_retries=cfg.get("max_retries", 0),
                    retry_interval_seconds=cfg.get("interval", 0.05),
                )
            )
        for a, b in edges:
            g.edges.append(GraphEdge(from_key=a, to_key=b))
        s.add(g)
        s.commit()
        return g.id


def start_run(sf: sessionmaker, graph_id: int) -> int:
    with sf() as s:
        graph = s.get(Graph, graph_id)
        run = create_run(s, graph)
        s.commit()
        return run.id


async def wait_run(sf: sessionmaker, run_id: int, timeout: float = 15.0) -> str:
    """Poll until the run reaches a terminal status; returns that status."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        with sf() as s:
            status = s.get(Run, run_id).status
        if status in TERMINAL_RUN_STATUSES:
            return status
        assert asyncio.get_running_loop().time() < deadline, (
            f"run {run_id} did not finish within {timeout}s (status={status})"
        )
        await asyncio.sleep(0.01)


def run_snapshot(sf: sessionmaker, run_id: int) -> dict:
    with sf() as s:
        run = s.get(Run, run_id)
        return {
            "status": run.status,
            "topo_order": list(run.topo_order),
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "nodes": {
                n.node_key: {
                    "status": n.status,
                    "attempts": n.attempts,
                    "started_at": n.started_at,
                    "finished_at": n.finished_at,
                }
                for n in run.nodes
            },
        }


def attempts_of(sf: sessionmaker, run_id: int) -> list[dict]:
    with sf() as s:
        rows = (
            s.query(Attempt)
            .filter_by(run_id=run_id)
            .order_by(Attempt.id)
            .all()
        )
        return [
            {
                "node_key": a.node_key,
                "attempt_no": a.attempt_no,
                "result": a.result,
                "started_at": a.started_at,
                "finished_at": a.finished_at,
            }
            for a in rows
        ]


def max_concurrency(attempts: list[dict]) -> int:
    """Maximum number of attempts running simultaneously, computed with a
    sweep line over [started_at, finished_at] intervals."""
    events: list[tuple[datetime, int]] = []
    for a in attempts:
        if a["started_at"] and a["finished_at"]:
            events.append((a["started_at"], 1))
            events.append((a["finished_at"], -1))
    # Ends sort before starts at the same instant (delta -1 < 1).
    events.sort(key=lambda e: (e[0], e[1]))
    cur = best = 0
    for _, delta in events:
        cur += delta
        best = max(best, cur)
    return best


def overlap_seconds(a: dict, b: dict) -> float:
    """Overlap of two attempt intervals in seconds (0 if disjoint)."""
    start = max(a["started_at"], b["started_at"])
    end = min(a["finished_at"], b["finished_at"])
    return max(0.0, (end - start).total_seconds())
