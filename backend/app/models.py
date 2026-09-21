"""ORM models: orchestration graphs, runs, per-run node states, attempt records."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow

# --- Node lifecycle statuses -------------------------------------------------
NODE_PENDING = "pending"        # 等待：上游尚未全部成功
NODE_READY = "ready"            # 就绪：可调度，等待并发额度
NODE_RUNNING = "running"        # 运行中
NODE_RETRY_WAIT = "retry_wait"  # 重试等待：失败后退避中
NODE_SUCCEEDED = "succeeded"    # 成功
NODE_FAILED = "failed"          # 失败（重试用尽）
NODE_SKIPPED = "skipped"        # 不满足：上游失败/被跳过，按策略跳过

TERMINAL_NODE_STATUSES = (NODE_SUCCEEDED, NODE_FAILED, NODE_SKIPPED)
ACTIVE_NODE_STATUSES = (NODE_PENDING, NODE_READY, NODE_RUNNING, NODE_RETRY_WAIT)

# --- Run lifecycle statuses --------------------------------------------------
RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
ACTIVE_RUN_STATUSES = (RUN_PENDING, RUN_RUNNING)

# --- Attempt results ---------------------------------------------------------
ATTEMPT_RUNNING = "running"
ATTEMPT_SUCCESS = "success"
ATTEMPT_FAILURE = "failure"
ATTEMPT_INTERRUPTED = "interrupted"  # 调度器重启时仍在运行，被标记为中断


class Graph(Base):
    """A saved orchestration graph (DAG) definition."""

    __tablename__ = "graphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    max_parallel: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    nodes: Mapped[list["GraphNode"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan", order_by="GraphNode.node_key"
    )
    edges: Mapped[list["GraphEdge"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan", order_by="GraphEdge.id"
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="graph")


class GraphNode(Base):
    """A task node of a graph, carrying its execution & retry policy."""

    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("graph_id", "node_key", name="uq_graph_node_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[int] = mapped_column(ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False)
    node_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Simulated execution time of one attempt, seconds.
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Failure policy: the first `fail_times` attempts fail; if `always_fail`
    # is set every attempt fails.
    fail_times: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    always_fail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Retry policy: at most `max_retries` retries, `retry_interval_seconds`
    # of backoff between attempts.
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_interval_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Canvas position, persisted so the editor restores the layout.
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    graph: Mapped[Graph] = relationship(back_populates="nodes")


class GraphEdge(Base):
    """A dependency edge: `from_key` must succeed before `to_key` can run."""

    __tablename__ = "graph_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[int] = mapped_column(ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False)
    from_key: Mapped[str] = mapped_column(String(100), nullable=False)
    to_key: Mapped[str] = mapped_column(String(100), nullable=False)

    graph: Mapped[Graph] = relationship(back_populates="edges")


class Run(Base):
    """One execution instance of a graph. Runs of the same graph are fully
    isolated: node configs, edges and the deterministic topological order are
    snapshotted at run creation."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[int] = mapped_column(ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RUN_PENDING)
    max_parallel: Mapped[int] = mapped_column(Integer, nullable=False)
    topo_order: Mapped[list] = mapped_column(JSON, nullable=False)          # list[str]
    edges_snapshot: Mapped[list] = mapped_column(JSON, nullable=False)      # list[{from_key,to_key}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    graph: Mapped[Graph] = relationship(back_populates="runs")
    nodes: Mapped[list["RunNode"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunNode.id"
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Attempt.id"
    )


class RunNode(Base):
    """State of one node within one run (the retry/state-machine record)."""

    __tablename__ = "run_nodes"
    __table_args__ = (UniqueConstraint("run_id", "node_key", name="uq_run_node_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=NODE_PENDING)
    # Number of finished attempts (interrupted attempts do not count).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # first attempt start
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # terminal time
    # --- snapshotted config (isolated from later graph edits) ---
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    fail_times: Mapped[int] = mapped_column(Integer, nullable=False)
    always_fail: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_interval_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    run: Mapped[Run] = relationship(back_populates="nodes")


class Attempt(Base):
    """One execution attempt of a run node — the retry history."""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_key: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False, default=ATTEMPT_RUNNING)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    run: Mapped[Run] = relationship(back_populates="attempts")
