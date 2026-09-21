"""Pydantic schemas for the HTTP API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NodeIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(default="", max_length=200)
    duration_seconds: float = 1.0
    fail_times: int = 0
    always_fail: bool = False
    max_retries: int = 0
    retry_interval_seconds: float = 1.0
    x: float = 0.0
    y: float = 0.0


class EdgeIn(BaseModel):
    from_key: str
    to_key: str


class GraphIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    max_parallel: int = 4
    nodes: list[NodeIn] = []
    edges: list[EdgeIn] = []


class NodeOut(NodeIn):
    pass


class GraphOut(BaseModel):
    id: int
    name: str
    max_parallel: int
    created_at: datetime
    updated_at: datetime
    nodes: list[NodeOut]
    edges: list[EdgeIn]


class GraphSummary(BaseModel):
    id: int
    name: str
    max_parallel: int
    node_count: int
    edge_count: int
    updated_at: datetime


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = []
    cycle: list[str] | None = None
    topo_order: list[str] | None = None


class RunNodeOut(BaseModel):
    node_key: str
    name: str
    status: str
    attempts: int
    next_retry_at: datetime | None
    last_error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float
    fail_times: int
    always_fail: bool
    max_retries: int
    retry_interval_seconds: float
    x: float
    y: float


class RunOut(BaseModel):
    id: int
    graph_id: int
    graph_name: str
    status: str
    max_parallel: int
    topo_order: list[str]
    edges: list[EdgeIn]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    nodes: list[RunNodeOut]


class RunSummary(BaseModel):
    id: int
    graph_id: int
    graph_name: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AttemptOut(BaseModel):
    attempt_no: int
    result: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None


NodeStatus = Literal[
    "pending", "ready", "running", "retry_wait", "succeeded", "failed", "skipped"
]
