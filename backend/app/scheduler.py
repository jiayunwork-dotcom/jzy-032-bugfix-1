"""Scheduler: drives runs through their topological order under a per-run
concurrency cap.

Structure:
  * :func:`tick_run` — one synchronous state-machine pass over a run (skip
    propagation, ready promotion, retry-due promotion, dispatch, run
    finalization). Pure DB logic, directly unit-testable.
  * :class:`Scheduler` — the async wrapper: a periodic loop, an asyncio task
    per executing node, and recovery of unfinished runs at startup.

Concurrency invariant: a node is dispatched only while the number of
RUNNING nodes of that run is below ``run.max_parallel``; since dispatch and
completion both funnel through the tick, the running count never exceeds the
cap. Retry-waiting nodes hold no slot, so retries never block other branches.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from . import executor, models
from .db import utcnow
from .models import (
    ACTIVE_RUN_STATUSES,
    NODE_PENDING,
    NODE_READY,
    NODE_RETRY_WAIT,
    NODE_RUNNING,
    RUN_FAILED,
    RUN_PENDING,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    TERMINAL_NODE_STATUSES,
    Run,
    RunNode,
)
from .recovery import recover_unfinished_runs

log = logging.getLogger("scheduler")

DispatchCallback = Callable[[int, str, int, float], None]
"""Called with (run_id, node_key, attempt_id, duration_seconds) when a node
is dispatched; the async layer turns this into an execution task."""


def tick_run(session: Session, run: Run, dispatch: DispatchCallback) -> None:
    """Advance one run by one state-machine pass."""
    nodes: dict[str, RunNode] = {n.node_key: n for n in run.nodes}
    preds: dict[str, list[str]] = {k: [] for k in nodes}
    for e in run.edges_snapshot:
        preds[e["to_key"]].append(e["from_key"])

    now = utcnow()
    if run.status == RUN_PENDING:
        run.status = RUN_RUNNING
        run.started_at = now

    # 1) Skip propagation (topological order): a pending node whose any
    #    predecessor failed or was skipped is itself marked skipped — it is
    #    "not satisfiable", never executed.
    for key in run.topo_order:
        node = nodes[key]
        if node.status != NODE_PENDING:
            continue
        upstream = preds[key]
        if upstream and any(nodes[p].status in (models.NODE_FAILED, models.NODE_SKIPPED) for p in upstream):
            node.status = models.NODE_SKIPPED
            node.finished_at = now
            node.last_error = "上游失败或被跳过，不满足触发条件"

    # 2) Ready promotion: all predecessors succeeded -> ready.
    for key in run.topo_order:
        node = nodes[key]
        if node.status != NODE_PENDING:
            continue
        if all(nodes[p].status == models.NODE_SUCCEEDED for p in preds[key]):
            node.status = NODE_READY

    # 3) Retry-due promotion: backoff elapsed -> ready again.
    for node in nodes.values():
        if (
            node.status == NODE_RETRY_WAIT
            and node.next_retry_at is not None
            and node.next_retry_at <= now
        ):
            node.status = NODE_READY
            node.next_retry_at = None

    # 4) Dispatch ready nodes in deterministic topological order while the
    #    run has free concurrency slots.
    running = sum(1 for n in nodes.values() if n.status == NODE_RUNNING)
    for key in run.topo_order:
        if running >= run.max_parallel:
            break
        node = nodes[key]
        if node.status != NODE_READY:
            continue
        attempt = executor.start_attempt(session, node)
        running += 1
        dispatch(run.id, node.node_key, attempt.id, node.duration_seconds)

    # 5) Run finalization: every node terminal -> run succeeded/failed.
    if nodes and all(n.status in TERMINAL_NODE_STATUSES for n in nodes.values()):
        run.status = (
            RUN_FAILED
            if any(n.status == models.NODE_FAILED for n in nodes.values())
            else RUN_SUCCEEDED
        )
        run.finished_at = utcnow()


class Scheduler:
    """Async scheduler loop. One instance per process; recovers unfinished
    runs from the database on startup so a restart never loses run state."""

    def __init__(self, session_factory: sessionmaker, tick_interval: float = 0.1):
        self._session_factory = session_factory
        self._tick_interval = tick_interval
        self._wakeup = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._node_tasks: dict[tuple[int, str], asyncio.Task] = {}
        self._stopped = asyncio.Event()

    # ------------------------------------------------------------------ API
    async def start(self) -> None:
        recovered = recover_unfinished_runs(self._session_factory)
        if recovered:
            log.info("recovered unfinished runs: %s", recovered)
        self._stopped.clear()
        self._loop_task = asyncio.create_task(self._loop(), name="scheduler-loop")

    async def stop(self) -> None:
        """Graceful shutdown: stop the loop and abandon in-flight node tasks.
        Abandoned attempts stay 'running' in the DB and are marked
        'interrupted' by recovery on the next startup."""
        await self._shutdown()

    async def crash(self) -> None:
        """Simulate an abrupt process kill (for recovery tests). Identical to
        stop(): no in-flight state is written back."""
        await self._shutdown()

    async def _shutdown(self) -> None:
        self._stopped.set()
        if self._loop_task:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        tasks = list(self._node_tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._node_tasks.clear()

    def wakeup(self) -> None:
        self._wakeup.set()

    # -------------------------------------------------------------- internals
    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.tick()
            except Exception:  # keep the loop alive; next tick retries
                log.exception("scheduler tick failed")
            self._wakeup.clear()
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=self._tick_interval)
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> None:
        """One pass over all active runs."""
        with self._session_factory() as session:
            runs = (
                session.query(Run)
                .filter(Run.status.in_(ACTIVE_RUN_STATUSES))
                .order_by(Run.id)
                .all()
            )
            for run in runs:
                tick_run(session, run, self._dispatch)
            session.commit()

    def _dispatch(self, run_id: int, node_key: str, attempt_id: int, duration: float) -> None:
        task = asyncio.create_task(
            self._execute(run_id, node_key, attempt_id, duration),
            name=f"node-{run_id}-{node_key}-a{attempt_id}",
        )
        self._node_tasks[(run_id, node_key)] = task

    async def _execute(self, run_id: int, node_key: str, attempt_id: int, duration: float) -> None:
        """Simulated node execution: sleep for the configured duration, then
        apply the outcome through the retry state machine."""
        try:
            await asyncio.sleep(duration)
            with self._session_factory() as session:
                node = (
                    session.query(RunNode)
                    .filter_by(run_id=run_id, node_key=node_key)
                    .one_or_none()
                )
                attempt = session.get(models.Attempt, attempt_id)
                if node is None or attempt is None or node.status != NODE_RUNNING:
                    return  # run/node no longer active (e.g. finalized elsewhere)
                executor.finish_attempt(session, node, attempt)
                session.commit()
        finally:
            self._node_tasks.pop((run_id, node_key), None)
            self._wakeup.set()
