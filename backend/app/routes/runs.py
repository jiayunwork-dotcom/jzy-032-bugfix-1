"""Run endpoints: start a run from a graph, observe run/node state, retry history."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, service
from ..db import get_db
from ..graph_logic import GraphValidationError
from ..schemas import AttemptOut, RunOut, RunSummary
from ..serialize import attempt_to_out, run_to_out, run_to_summary

router = APIRouter(prefix="/api", tags=["runs"])


@router.post("/graphs/{graph_id}/runs", response_model=RunOut, status_code=201)
def start_run(graph_id: int, db: Session = Depends(get_db)):
    graph = db.get(models.Graph, graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="图不存在")
    try:
        run = service.create_run(db, graph)  # re-validates: cyclic graphs never enter the scheduler
    except GraphValidationError as exc:
        raise HTTPException(status_code=400, detail={"errors": exc.errors, "cycle": exc.cycle})
    db.commit()
    db.refresh(run)
    return run_to_out(run)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(graph_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Run).order_by(models.Run.id.desc())
    if graph_id is not None:
        q = q.filter(models.Run.graph_id == graph_id)
    return [run_to_summary(r) for r in q.limit(200).all()]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return run_to_out(run)


@router.get("/runs/{run_id}/nodes/{node_key}/attempts", response_model=list[AttemptOut])
def get_node_attempts(run_id: int, node_key: str, db: Session = Depends(get_db)):
    run = db.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    attempts = (
        db.query(models.Attempt)
        .filter_by(run_id=run_id, node_key=node_key)
        .order_by(models.Attempt.attempt_no)
        .all()
    )
    return [attempt_to_out(a) for a in attempts]
