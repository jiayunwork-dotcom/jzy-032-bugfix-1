"""Recovery tests: unfinished runs survive a scheduler restart — in-flight
nodes are re-judged, finished work is never re-run."""
import asyncio

from app.models import Attempt, Run, RunNode
from app.recovery import recover_unfinished_runs
from app.scheduler import Scheduler

from .helpers import attempts_of, build_graph, make_session_factory, run_snapshot, start_run, wait_run

TICK = 0.01


async def test_recovery_requeues_interrupted_nodes_and_resumes_run():
    """fast node finishes, slow node is mid-flight when the scheduler
    'crashes'. A fresh scheduler must recover the run: slow node re-executes
    (interrupted attempt recorded), fast node is NOT re-run."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={
            "fast": {"duration": 0.02},
            "slow": {"duration": 0.5},
        },
        edges=[],
        max_parallel=2,
    )
    rid = start_run(sf, gid)

    sched1 = Scheduler(sf, tick_interval=TICK)
    await sched1.start()

    # Wait until 'fast' succeeded and 'slow' is running, then kill the
    # scheduler abruptly (no state is written back for in-flight nodes).
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        snap = run_snapshot(sf, rid)
        if (
            snap["nodes"]["fast"]["status"] == "succeeded"
            and snap["nodes"]["slow"]["status"] == "running"
        ):
            break
        assert asyncio.get_running_loop().time() < deadline, "slow node never started"
        await asyncio.sleep(0.01)
    await sched1.crash()

    # The crash left the run unfinished with 'slow' still marked running.
    snap = run_snapshot(sf, rid)
    assert snap["status"] in ("pending", "running")
    assert snap["nodes"]["slow"]["status"] == "running"

    # A new scheduler instance (process restart) recovers and finishes it.
    sched2 = Scheduler(sf, tick_interval=TICK)
    await sched2.start()
    try:
        status = await wait_run(sf, rid)
    finally:
        await sched2.stop()
    assert status == "succeeded"

    snap = run_snapshot(sf, rid)
    assert all(n["status"] == "succeeded" for n in snap["nodes"].values())

    attempts = attempts_of(sf, rid)
    fast_attempts = [a for a in attempts if a["node_key"] == "fast"]
    slow_attempts = [a for a in attempts if a["node_key"] == "slow"]
    # Finished work was not re-run.
    assert len(fast_attempts) == 1 and fast_attempts[0]["result"] == "success"
    # The interrupted attempt is recorded, then one successful re-execution.
    assert [a["result"] for a in slow_attempts] == ["interrupted", "success"]
    assert snap["nodes"]["slow"]["attempts"] == 1  # interrupted attempt doesn't consume budget


async def test_recover_unfinished_runs_resets_state_directly():
    """Unit-level: recover() marks open attempts interrupted, re-queues
    running nodes, and leaves succeeded/retry_wait nodes untouched."""
    sf = make_session_factory()
    gid = build_graph(
        sf,
        nodes={"a": {}, "b": {}, "c": {"max_retries": 1, "interval": 60}},
        edges=[],
    )
    rid = start_run(sf, gid)

    with sf() as s:
        run = s.get(Run, rid)
        run.status = "running"
        nodes = {n.node_key: n for n in s.query(RunNode).filter_by(run_id=rid)}
        nodes["a"].status = "succeeded"
        nodes["b"].status = "running"
        nodes["c"].status = "retry_wait"
        s.add(Attempt(run_id=rid, node_key="b", attempt_no=1, result="running"))
        s.commit()

    recovered = recover_unfinished_runs(sf)
    assert recovered == [rid]

    snap = run_snapshot(sf, rid)
    assert snap["nodes"]["a"]["status"] == "succeeded"      # untouched
    assert snap["nodes"]["b"]["status"] == "ready"          # re-queued
    assert snap["nodes"]["c"]["status"] == "retry_wait"     # backoff preserved
    (attempt,) = [a for a in attempts_of(sf, rid) if a["node_key"] == "b"]
    assert attempt["result"] == "interrupted"
    assert attempt["finished_at"] is not None


async def test_recovery_with_pending_run_picks_it_up():
    """A run created but never scheduled (scheduler down) is picked up after
    restart and runs to completion."""
    sf = make_session_factory()
    gid = build_graph(sf, nodes={"only": {"duration": 0.02}}, edges=[])
    rid = start_run(sf, gid)
    assert run_snapshot(sf, rid)["status"] == "pending"

    sched = Scheduler(sf, tick_interval=TICK)
    await sched.start()
    try:
        assert await wait_run(sf, rid) == "succeeded"
    finally:
        await sched.stop()
