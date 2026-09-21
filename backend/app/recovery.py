"""Recovery of unfinished runs after a scheduler restart.

Policy:
  * runs still in pending/running state are picked up again — never lost,
    never restarted from scratch;
  * nodes that were RUNNING when the process died have their open attempt
    marked 'interrupted' (it does not consume the retry budget) and are
    re-queued as ready, so only the interrupted node re-executes;
  * retry-waiting nodes keep their persisted backoff deadline;
  * succeeded/failed/skipped nodes are untouched — no re-run of finished work.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from .db import utcnow
from .models import (
    ACTIVE_RUN_STATUSES,
    ATTEMPT_INTERRUPTED,
    ATTEMPT_RUNNING,
    NODE_READY,
    NODE_RUNNING,
    Attempt,
    Run,
)

log = logging.getLogger("recovery")


def recover_unfinished_runs(session_factory: sessionmaker) -> list[int]:
    """Reset in-flight state left behind by a previous process. Returns the
    ids of runs that were recovered."""
    with session_factory() as session:
        runs = (
            session.query(Run)
            .filter(Run.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(Run.id)
            .all()
        )
        recovered: list[int] = []
        now = utcnow()
        for run in runs:
            for node in run.nodes:
                if node.status != NODE_RUNNING:
                    continue
                open_attempt = (
                    session.query(Attempt)
                    .filter_by(run_id=run.id, node_key=node.node_key, result=ATTEMPT_RUNNING)
                    .order_by(Attempt.id.desc())
                    .first()
                )
                if open_attempt is not None:
                    open_attempt.result = ATTEMPT_INTERRUPTED
                    open_attempt.error = "调度器重启，本次尝试被中断"
                    open_attempt.finished_at = now
                node.status = NODE_READY  # re-judged: will be re-dispatched
                node.next_retry_at = None
            recovered.append(run.id)
        session.commit()
        if recovered:
            log.info("recovery: re-queued interrupted nodes of runs %s", recovered)
        return recovered
