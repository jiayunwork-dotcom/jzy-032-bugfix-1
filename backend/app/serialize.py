"""ORM -> API schema converters."""
from __future__ import annotations

from . import models
from .schemas import (
    AttemptOut,
    EdgeIn,
    GraphOut,
    GraphSummary,
    NodeOut,
    RunNodeOut,
    RunOut,
    RunSummary,
)


def graph_to_out(graph: models.Graph) -> GraphOut:
    return GraphOut(
        id=graph.id,
        name=graph.name,
        max_parallel=graph.max_parallel,
        created_at=graph.created_at,
        updated_at=graph.updated_at,
        nodes=[
            NodeOut(
                key=n.node_key,
                name=n.name,
                duration_seconds=n.duration_seconds,
                fail_times=n.fail_times,
                always_fail=n.always_fail,
                max_retries=n.max_retries,
                retry_interval_seconds=n.retry_interval_seconds,
                x=n.pos_x,
                y=n.pos_y,
            )
            for n in graph.nodes
        ],
        edges=[EdgeIn(from_key=e.from_key, to_key=e.to_key) for e in graph.edges],
    )


def graph_to_summary(graph: models.Graph) -> GraphSummary:
    return GraphSummary(
        id=graph.id,
        name=graph.name,
        max_parallel=graph.max_parallel,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        updated_at=graph.updated_at,
    )


def run_to_out(run: models.Run) -> RunOut:
    return RunOut(
        id=run.id,
        graph_id=run.graph_id,
        graph_name=run.graph.name if run.graph else "",
        status=run.status,
        max_parallel=run.max_parallel,
        topo_order=list(run.topo_order),
        edges=[EdgeIn(**e) for e in run.edges_snapshot],
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        nodes=[
            RunNodeOut(
                node_key=n.node_key,
                name=n.name,
                status=n.status,
                attempts=n.attempts,
                next_retry_at=n.next_retry_at,
                last_error=n.last_error,
                started_at=n.started_at,
                finished_at=n.finished_at,
                duration_seconds=n.duration_seconds,
                fail_times=n.fail_times,
                always_fail=n.always_fail,
                max_retries=n.max_retries,
                retry_interval_seconds=n.retry_interval_seconds,
                x=n.pos_x,
                y=n.pos_y,
            )
            for n in run.nodes
        ],
    )


def run_to_summary(run: models.Run) -> RunSummary:
    return RunSummary(
        id=run.id,
        graph_id=run.graph_id,
        graph_name=run.graph.name if run.graph else "",
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def attempt_to_out(a: models.Attempt) -> AttemptOut:
    return AttemptOut(
        attempt_no=a.attempt_no,
        result=a.result,
        error=a.error,
        started_at=a.started_at,
        finished_at=a.finished_at,
    )
