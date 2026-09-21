"""Node execution & retry state machine.

Owns the per-node lifecycle transitions (ready -> running -> succeeded /
retry_wait -> ... -> failed) and the simulated outcome policy. The scheduler
drives these transitions; this module decides *what* the transitions are.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from .db import utcnow
from .models import (
    ATTEMPT_FAILURE,
    ATTEMPT_SUCCESS,
    NODE_FAILED,
    NODE_READY,
    NODE_RETRY_WAIT,
    NODE_RUNNING,
    NODE_SUCCEEDED,
    Attempt,
    RunNode,
)


def attempt_will_fail(node: RunNode, attempt_no: int) -> bool:
    """Simulated outcome policy for one attempt: `always_fail` fails every
    attempt, otherwise the first `fail_times` attempts fail and later ones
    succeed (models a flaky task that recovers after retries)."""
    if node.always_fail:
        return True
    return attempt_no <= node.fail_times


def start_attempt(session: Session, node: RunNode) -> Attempt:
    """Transition a ready node to running and open an attempt record."""
    assert node.status == NODE_READY, f"node {node.node_key} not ready (is {node.status})"
    now = utcnow()
    attempt = Attempt(
        run_id=node.run_id,
        node_key=node.node_key,
        attempt_no=node.attempts + 1,
        started_at=now,
    )
    node.status = NODE_RUNNING
    node.next_retry_at = None
    if node.started_at is None:
        node.started_at = now
    session.add(attempt)
    session.flush()
    return attempt


def finish_attempt(session: Session, node: RunNode, attempt: Attempt) -> None:
    """Close the current attempt of a running node and apply the retry state
    machine:

    * success                -> node succeeded
    * failure, retries left  -> node retry_wait with a backoff deadline
    * failure, retries spent -> node failed (propagates downstream)
    """
    assert node.status == NODE_RUNNING, f"node {node.node_key} not running (is {node.status})"
    now = utcnow()
    failed = attempt_will_fail(node, attempt.attempt_no)

    node.attempts = attempt.attempt_no
    attempt.finished_at = now

    if not failed:
        attempt.result = ATTEMPT_SUCCESS
        node.status = NODE_SUCCEEDED
        node.finished_at = now
        node.last_error = None
        return

    attempt.result = ATTEMPT_FAILURE
    attempt.error = f"模拟任务失败（第 {attempt.attempt_no} 次尝试）"
    node.last_error = attempt.error
    if attempt.attempt_no <= node.max_retries:
        # Backoff, then the node becomes ready again. Retry waiting does not
        # hold a concurrency slot, so unrelated branches keep progressing.
        node.status = NODE_RETRY_WAIT
        node.next_retry_at = now + timedelta(seconds=node.retry_interval_seconds)
    else:
        node.status = NODE_FAILED
        node.finished_at = now
