"""Graph CRUD + validation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, service
from ..db import get_db
from ..graph_logic import GraphValidationError, validate_graph
from ..schemas import GraphIn, GraphOut, GraphSummary, ValidationResult
from ..serialize import graph_to_out, graph_to_summary

router = APIRouter(prefix="/api/graphs", tags=["graphs"])


def _validation_http_error(exc: GraphValidationError) -> HTTPException:
    # Structured detail so the UI can both list the reasons and highlight
    # the exact cycle on the canvas.
    return HTTPException(status_code=400, detail={"errors": exc.errors, "cycle": exc.cycle})


@router.get("", response_model=list[GraphSummary])
def list_graphs(db: Session = Depends(get_db)):
    graphs = db.query(models.Graph).order_by(models.Graph.updated_at.desc()).all()
    return [graph_to_summary(g) for g in graphs]


@router.post("", response_model=GraphOut, status_code=201)
def create_graph(payload: GraphIn, db: Session = Depends(get_db)):
    nodes, edges = service.spec_from_payload(payload)
    try:
        validate_graph(nodes, edges, payload.max_parallel)
    except GraphValidationError as exc:
        raise _validation_http_error(exc)
    graph = models.Graph()
    service.replace_graph_content(graph, payload)
    db.add(graph)
    db.commit()
    db.refresh(graph)
    return graph_to_out(graph)


@router.get("/{graph_id}", response_model=GraphOut)
def get_graph(graph_id: int, db: Session = Depends(get_db)):
    graph = db.get(models.Graph, graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="图不存在")
    return graph_to_out(graph)


@router.put("/{graph_id}", response_model=GraphOut)
def update_graph(graph_id: int, payload: GraphIn, db: Session = Depends(get_db)):
    graph = db.get(models.Graph, graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="图不存在")
    nodes, edges = service.spec_from_payload(payload)
    try:
        validate_graph(nodes, edges, payload.max_parallel)
    except GraphValidationError as exc:
        raise _validation_http_error(exc)
    service.replace_graph_content(graph, payload)
    db.commit()
    db.refresh(graph)
    return graph_to_out(graph)


@router.delete("/{graph_id}", status_code=204)
def delete_graph(graph_id: int, db: Session = Depends(get_db)):
    graph = db.get(models.Graph, graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="图不存在")
    db.delete(graph)
    db.commit()


@router.post("/validate", response_model=ValidationResult)
def validate_payload(payload: GraphIn):
    """Validate a graph spec without saving — used by the editor for live
    feedback (cycle highlighting etc.)."""
    nodes, edges = service.spec_from_payload(payload)
    try:
        topo = validate_graph(nodes, edges, payload.max_parallel)
    except GraphValidationError as exc:
        return ValidationResult(ok=False, errors=exc.errors, cycle=exc.cycle)
    return ValidationResult(ok=True, topo_order=topo)
