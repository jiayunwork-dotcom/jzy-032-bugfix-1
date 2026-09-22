"""Behavioural tests of the scheduler: topological progression, parallel
branches, concurrency cap, failure propagation, retries and run isolation."""
import asyncio

from app.scheduler import Scheduler

from .helpers import (
    attempts_of,
    build_graph,
    make_session_factory,
    max_concurrency,
    overlap_seconds,
    run_snapshot,
    start_run,
    wait_run,
)

TICK = 0.01


async def run_to_completion(sf, run_id):
    sched = Scheduler(sf, tick_interval=TICK)
    await sched.start()
    try:
        status = await wait_run(sf, run_id)
    finally:
        await sched.stop()
    return status


async def test_topological_order_progression():
    """Chain a->b->c plus independent d: the chain executes in dependency
    order and the run succeeds."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={k: {"duration": 0.02} for k in ["a", "b", "c", "d"]},
        edges=[("a", "b"), ("b", "c")],
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "succeeded"

    snap = run_snapshot(sf, rid)
    assert all(n["status"] == "succeeded" for n in snap["nodes"].values())
    starts = {k: n["started_at"] for k, n in snap["nodes"].items()}
    assert starts["a"] < starts["b"] < starts["c"]
    # The persisted topo order is a valid linearisation of the dependencies.
    pos = {k: i for i, k in enumerate(snap["topo_order"])}
    assert pos["a"] < pos["b"] < pos["c"]


async def test_execution_order_is_reproducible():
    """Two runs of the same graph follow the same deterministic topo order."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={k: {"duration": 0.01} for k in ["a", "b", "c", "d"]},
        edges=[("a", "c"), ("b", "c"), ("c", "d")],
    )
    r1, r2 = start_run(sf, gid), start_run(sf, gid)
    assert await run_to_completion(sf, r1) == "succeeded"
    assert await run_to_completion(sf, r2) == "succeeded"
    snap1, snap2 = run_snapshot(sf, r1), run_snapshot(sf, r2)
    assert snap1["topo_order"] == snap2["topo_order"] == ["a", "b", "c", "d"]


async def test_independent_branches_run_in_parallel():
    """Two independent chains with generous concurrency: both roots start
    before either finishes (their execution intervals overlap)."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={k: {"duration": 0.15} for k in ["a", "b", "c", "d"]},
        edges=[("a", "b"), ("c", "d")],
        max_parallel=4,
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "succeeded"

    attempts = attempts_of(sf, rid)
    by_node = {a["node_key"]: a for a in attempts}
    assert overlap_seconds(by_node["a"], by_node["c"]) > 0.05
    # Downstream nodes only start after their own upstream finished.
    assert by_node["b"]["started_at"] >= by_node["a"]["finished_at"]
    assert by_node["d"]["started_at"] >= by_node["c"]["finished_at"]


async def test_concurrency_cap_is_enforced():
    """4 independent nodes, cap 2: never more than 2 running at once, and the
    cap is actually saturated (queueing with backfill, not serialization)."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={k: {"duration": 0.15} for k in ["n1", "n2", "n3", "n4"]},
        edges=[],
        max_parallel=2,
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "succeeded"

    attempts = attempts_of(sf, rid)
    assert len(attempts) == 4
    assert max_concurrency(attempts) == 2  # <= 2 always, and 2 reached


async def test_failed_upstream_skips_downstream_but_not_siblings():
    """a (always fails, no retries) -> b -> c; d independent.
    b and c must be skipped (not executed), d succeeds, run fails."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={
            "a": {"duration": 0.01, "always_fail": True},
            "b": {"duration": 0.01},
            "c": {"duration": 0.01},
            "d": {"duration": 0.01},
        },
        edges=[("a", "b"), ("b", "c")],
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "failed"

    nodes = run_snapshot(sf, rid)["nodes"]
    assert nodes["a"]["status"] == "failed"
    assert nodes["b"]["status"] == "skipped"
    assert nodes["c"]["status"] == "skipped"
    assert nodes["d"]["status"] == "succeeded"
    # Skipped nodes never executed.
    assert nodes["b"]["attempts"] == 0
    assert nodes["c"]["attempts"] == 0
    assert not any(a["node_key"] in ("b", "c") for a in attempts_of(sf, rid))


async def test_join_with_mixed_upstream_outcomes_is_skipped():
    """Regression: join node c with two upstreams — a always fails, b
    succeeds; d is independent. c must be marked skipped (never executed),
    and the run must finalize as failed instead of hanging with c stuck in
    pending forever."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={
            "a": {"duration": 0.01, "always_fail": True},
            "b": {"duration": 0.01},
            "c": {"duration": 0.01},
            "d": {"duration": 0.01},
        },
        edges=[("a", "c"), ("b", "c")],
    )
    rid = start_run(sf, gid)
    # Before the fix the run never reached a terminal status (c stayed
    # pending); wait_run would time out here.
    assert await run_to_completion(sf, rid) == "failed"

    nodes = run_snapshot(sf, rid)["nodes"]
    assert nodes["a"]["status"] == "failed"
    assert nodes["b"]["status"] == "succeeded"
    assert nodes["c"]["status"] == "skipped"
    assert nodes["d"]["status"] == "succeeded"
    # The join node never executed.
    assert nodes["c"]["attempts"] == 0
    assert not any(a["node_key"] == "c" for a in attempts_of(sf, rid))


async def test_join_with_skipped_and_succeeded_upstreams_is_skipped():
    """Mixed outcomes via propagation: x fails -> y is skipped; the join w
    (upstreams y skipped, z succeeded) must also be skipped, not left
    pending."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={
            "x": {"duration": 0.01, "always_fail": True},
            "y": {"duration": 0.01},
            "z": {"duration": 0.01},
            "w": {"duration": 0.01},
        },
        edges=[("x", "y"), ("y", "w"), ("z", "w")],
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "failed"

    nodes = run_snapshot(sf, rid)["nodes"]
    assert nodes["x"]["status"] == "failed"
    assert nodes["y"]["status"] == "skipped"
    assert nodes["z"]["status"] == "succeeded"
    assert nodes["w"]["status"] == "skipped"
    assert nodes["w"]["attempts"] == 0


async def test_join_waits_for_retrying_upstream_before_firing():
    """A flaky upstream that recovers on retry must not get its join skipped
    during backoff: fail_times=1 with one retry — the join fires only after
    the retried attempt succeeds, and the run succeeds."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={
            "flaky": {"duration": 0.01, "fail_times": 1, "max_retries": 1, "interval": 0.05},
            "ok": {"duration": 0.01},
            "join": {"duration": 0.01},
        },
        edges=[("flaky", "join"), ("ok", "join")],
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "succeeded"

    nodes = run_snapshot(sf, rid)["nodes"]
    assert nodes["flaky"]["status"] == "succeeded"
    assert nodes["flaky"]["attempts"] == 2
    assert nodes["join"]["status"] == "succeeded"
    assert nodes["join"]["attempts"] == 1
    # The join started only after the flaky upstream's final success.
    assert nodes["join"]["started_at"] >= nodes["flaky"]["finished_at"]


async def test_retry_exhaustion_then_failure_without_blocking_siblings():
    """x fails every attempt with max_retries=2 -> exactly 3 attempts, then
    failed. Sibling branch y completes while x is still backing off."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={
            "x": {"duration": 0.01, "always_fail": True, "max_retries": 2, "interval": 0.1},
            "y": {"duration": 0.01},
        },
        edges=[],
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "failed"

    nodes = run_snapshot(sf, rid)["nodes"]
    assert nodes["x"]["status"] == "failed"
    assert nodes["x"]["attempts"] == 3  # 1 initial + 2 retries, no more
    assert nodes["y"]["status"] == "succeeded"
    # Retry backoff did not block the unrelated branch.
    assert nodes["y"]["finished_at"] < nodes["x"]["finished_at"]

    x_attempts = [a for a in attempts_of(sf, rid) if a["node_key"] == "x"]
    assert [a["attempt_no"] for a in x_attempts] == [1, 2, 3]
    assert all(a["result"] == "failure" for a in x_attempts)


async def test_flaky_node_succeeds_on_retry():
    """fail_times=1 with one retry: first attempt fails, retry succeeds."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={"z": {"duration": 0.01, "fail_times": 1, "max_retries": 1, "interval": 0.02}},
        edges=[],
    )
    rid = start_run(sf, gid)
    assert await run_to_completion(sf, rid) == "succeeded"

    nodes = run_snapshot(sf, rid)["nodes"]
    assert nodes["z"]["status"] == "succeeded"
    assert nodes["z"]["attempts"] == 2
    results = [a["result"] for a in attempts_of(sf, rid)]
    assert results == ["failure", "success"]


async def test_runs_of_same_graph_are_isolated():
    """Two concurrent runs of one graph: independent state, independent
    concurrency budgets, independent retry histories."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={
            "bad": {"duration": 0.01, "always_fail": True, "max_retries": 1, "interval": 0.02},
            "good": {"duration": 0.02},
        },
        edges=[],
        max_parallel=1,
    )
    r1, r2 = start_run(sf, gid), start_run(sf, gid)
    assert r1 != r2

    sched = Scheduler(sf, tick_interval=TICK)
    await sched.start()
    try:
        s1, s2 = await asyncio.gather(wait_run(sf, r1), wait_run(sf, r2))
    finally:
        await sched.stop()
    assert s1 == s2 == "failed"  # both runs see 'bad' fail; neither is disturbed

    for rid in (r1, r2):
        nodes = run_snapshot(sf, rid)["nodes"]
        assert set(nodes) == {"bad", "good"}
        assert nodes["bad"]["status"] == "failed"
        assert nodes["bad"]["attempts"] == 2
        assert nodes["good"]["status"] == "succeeded"
        # Retry history is scoped to its own run.
        assert len(attempts_of(sf, rid)) == 3  # bad x2 + good x1
