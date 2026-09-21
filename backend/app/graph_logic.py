"""Pure graph algorithms & validation rules.

This module has no database or web dependencies: it operates on plain
``NodeSpec``/``EdgeSpec`` values so it can be unit-tested in isolation and
reused by both the API layer (validate on save) and the scheduler (defensive
re-validation before a run is admitted).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeSpec:
    key: str
    name: str
    duration_seconds: float = 1.0
    fail_times: int = 0
    always_fail: bool = False
    max_retries: int = 0
    retry_interval_seconds: float = 1.0


@dataclass(frozen=True)
class EdgeSpec:
    from_key: str
    to_key: str


class GraphValidationError(ValueError):
    """Raised when a graph spec is invalid. Carries human-readable reasons
    and, when a cycle is the problem, the exact cycle path."""

    def __init__(self, errors: list[str], cycle: list[str] | None = None):
        self.errors = errors
        self.cycle = cycle
        super().__init__("; ".join(errors))


def build_adjacency(node_keys: list[str], edges: list[EdgeSpec]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {k: [] for k in node_keys}
    for e in edges:
        if e.from_key in adj:
            adj[e.from_key].append(e.to_key)
    for k in adj:
        adj[k] = sorted(set(adj[k]))
    return adj


def find_cycle(node_keys: list[str], edges: list[EdgeSpec]) -> list[str] | None:
    """Return one concrete cycle as a node-key path (e.g. ["a","b","c","a"]),
    or None if the graph is acyclic. Iterative DFS with white/gray/black
    coloring; a back edge to a gray node reveals the cycle on the DFS stack.
    Deterministic: nodes and neighbors are visited in sorted key order."""
    adj = build_adjacency(node_keys, edges)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in adj}

    for start in sorted(adj):
        if color[start] != WHITE:
            continue
        # Stack entries: (node, iterator over sorted neighbors).
        stack: list[tuple[str, object]] = [(start, iter(adj[start]))]
        path: list[str] = [start]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:  # type: ignore[union-attr]
                if color.get(nxt) == GRAY:
                    # Back edge: cycle is the path slice from nxt, plus nxt again.
                    idx = path.index(nxt)
                    return path[idx:] + [nxt]
                if color.get(nxt) == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(adj[nxt])))
                    path.append(nxt)
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return None


def topological_order(node_keys: list[str], edges: list[EdgeSpec]) -> list[str]:
    """Deterministic Kahn's algorithm (min-heap on node key). Raises
    GraphValidationError with the cycle path if the graph is cyclic."""
    adj = build_adjacency(node_keys, edges)
    indegree = {k: 0 for k in adj}
    for e in edges:
        if e.to_key in indegree and e.from_key in indegree:
            indegree[e.to_key] += 1

    heap = [k for k, d in indegree.items() if d == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        node = heapq.heappop(heap)
        order.append(node)
        for nxt in adj[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, nxt)

    if len(order) != len(adj):
        cycle = find_cycle(node_keys, edges) or []
        raise GraphValidationError(
            ["图中存在环，无法拓扑排序: " + " -> ".join(cycle)], cycle=cycle
        )
    return order


def downstream_keys(edges: list[EdgeSpec], sources: list[str]) -> set[str]:
    """All nodes reachable from `sources` (exclusive) — used by the UI to
    explain which nodes a failure will propagate to."""
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e.from_key, []).append(e.to_key)
    seen: set[str] = set()
    stack = list(sources)
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def validate_graph(
    nodes: list[NodeSpec], edges: list[EdgeSpec], max_parallel: int
) -> list[str]:
    """Validate a graph spec. Returns the deterministic topological order on
    success; raises GraphValidationError otherwise.

    Rules enforced:
      * at least one node; unique, non-empty node keys
      * max_parallel must be a positive integer (并发上限非正 -> 拒绝)
      * per-node: duration >= 0, max_retries >= 0 (重试次数为负 -> 拒绝),
        retry_interval >= 0, fail_times >= 0
      * every edge endpoint must reference an existing node (连到不存在的节点 -> 拒绝)
      * the graph must be acyclic; the concrete cycle path is reported
    """
    errors: list[str] = []

    if not nodes:
        errors.append("图至少需要一个节点")

    if not isinstance(max_parallel, int) or max_parallel < 1:
        errors.append(f"并发上限必须为正整数，当前值: {max_parallel!r}")

    seen: set[str] = set()
    for n in nodes:
        if not n.key or not n.key.strip():
            errors.append("存在空标识的节点")
        elif n.key in seen:
            errors.append(f"节点标识重复: {n.key}")
        seen.add(n.key)
        if n.duration_seconds < 0:
            errors.append(f"节点 {n.key} 的模拟时长不能为负: {n.duration_seconds}")
        if n.max_retries < 0:
            errors.append(f"节点 {n.key} 的重试次数不能为负: {n.max_retries}")
        if n.retry_interval_seconds < 0:
            errors.append(f"节点 {n.key} 的重试间隔不能为负: {n.retry_interval_seconds}")
        if n.fail_times < 0:
            errors.append(f"节点 {n.key} 的失败次数设定不能为负: {n.fail_times}")

    for e in edges:
        if e.from_key not in seen:
            errors.append(f"连线的起点指向不存在的节点: {e.from_key}")
        if e.to_key not in seen:
            errors.append(f"连线的终点指向不存在的节点: {e.to_key}")
        if e.from_key == e.to_key and e.from_key in seen:
            errors.append(f"节点 {e.from_key} 存在自环")

    if errors:
        raise GraphValidationError(errors)

    # Cycle check last, on a structurally sane graph.
    node_keys = [n.key for n in nodes]
    cycle = find_cycle(node_keys, edges)
    if cycle:
        raise GraphValidationError(
            ["图中存在环: " + " -> ".join(cycle)], cycle=cycle
        )
    return topological_order(node_keys, edges)
