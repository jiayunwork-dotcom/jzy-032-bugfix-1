"""Persistence-facing helpers: convert between API payloads and ORM rows,
and create run instances as immutable snapshots of a graph."""
from __future__ import annotations

from sqlalchemy.orm import Session, object_session

from . import models
from .graph_logic import EdgeSpec, NodeSpec, topological_order, validate_graph
from .schemas import GraphIn


def spec_from_payload(payload: GraphIn) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes = [
        NodeSpec(
            key=n.key,
            name=n.name or n.key,
            duration_seconds=n.duration_seconds,
            fail_times=n.fail_times,
            always_fail=n.always_fail,
            max_retries=n.max_retries,
            retry_interval_seconds=n.retry_interval_seconds,
        )
        for n in payload.nodes
    ]
    edges = [EdgeSpec(from_key=e.from_key, to_key=e.to_key) for e in payload.edges]
    return nodes, edges


def spec_from_orm(graph: models.Graph) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes = [
        NodeSpec(
            key=n.node_key,
            name=n.name,
            duration_seconds=n.duration_seconds,
            fail_times=n.fail_times,
            always_fail=n.always_fail,
            max_retries=n.max_retries,
            retry_interval_seconds=n.retry_interval_seconds,
        )
        for n in graph.nodes
    ]
    edges = [EdgeSpec(from_key=e.from_key, to_key=e.to_key) for e in graph.edges]
    return nodes, edges


def replace_graph_content(graph: models.Graph, payload: GraphIn) -> None:
    """Overwrite a graph's scalar fields, nodes and edges from a payload.
    Caller is responsible for validation *before* calling this."""
    graph.name = payload.name
    graph.max_parallel = payload.max_parallel
    graph.nodes.clear()
    graph.edges.clear()
    session = object_session(graph)
    if session is not None:
        # Persist the delete-orphan removals before inserting replacements,
        # so new rows cannot collide with old ones on (graph_id, node_key).
        session.flush()
    for n in payload.nodes:
        graph.nodes.append(
            models.GraphNode(
                node_key=n.key,
                name=n.name or n.key,
                duration_seconds=n.duration_seconds,
                fail_times=n.fail_times,
                always_fail=n.always_fail,
                max_retries=n.max_retries,
                retry_interval_seconds=n.retry_interval_seconds,
                pos_x=n.x,
                pos_y=n.y,
            )
        )
    for e in payload.edges:
        graph.edges.append(models.GraphEdge(from_key=e.from_key, to_key=e.to_key))


def create_run(session: Session, graph: models.Graph) -> models.Run:
    """Create a run as a self-contained snapshot of the graph: node configs,
    edges and the deterministic topological order are copied so the run is
    isolated from later graph edits and from other runs of the same graph.

    The graph is re-validated here (defense in depth): a cyclic or otherwise
    invalid graph is rejected before it can reach the scheduler."""
    nodes, edges = spec_from_orm(graph)
    topo = validate_graph(nodes, edges, graph.max_parallel)
    # validate_graph already returns the topo order; recompute defensively if
    # a subclass ever changes that contract.
    assert topo == topological_order([n.key for n in nodes], edges)

    run = models.Run(
        graph_id=graph.id,
        status=models.RUN_PENDING,
        max_parallel=graph.max_parallel,
        topo_order=topo,
        edges_snapshot=[{"from_key": e.from_key, "to_key": e.to_key} for e in edges],
    )
    node_by_key = {n.node_key: n for n in graph.nodes}
    for key in topo:
        gn = node_by_key[key]
        run.nodes.append(
            models.RunNode(
                node_key=gn.node_key,
                name=gn.name,
                status=models.NODE_PENDING,
                duration_seconds=gn.duration_seconds,
                fail_times=gn.fail_times,
                always_fail=gn.always_fail,
                max_retries=gn.max_retries,
                retry_interval_seconds=gn.retry_interval_seconds,
                pos_x=gn.pos_x,
                pos_y=gn.pos_y,
            )
        )
    session.add(run)
    session.flush()
    return run
