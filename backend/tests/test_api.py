"""API-level tests: invalid orchestrations are rejected with reasons, valid
graphs are stored, and cyclic graphs can never be run — even if one is
planted in the database directly."""
import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:  # runs lifespan: creates tables, scheduler disabled
        yield c


@pytest.fixture(autouse=True)
def clean_db(client):
    # Depends on `client` so the app lifespan has already created the tables.
    with SessionLocal() as s:
        for model in (models.Attempt, models.RunNode, models.Run, models.GraphEdge, models.GraphNode, models.Graph):
            s.query(model).delete()
        s.commit()


def valid_payload(**overrides):
    payload = {
        "name": "demo",
        "max_parallel": 2,
        "nodes": [
            {"key": "a", "name": "A", "duration_seconds": 0.5},
            {"key": "b", "name": "B", "duration_seconds": 0.5, "max_retries": 1},
        ],
        "edges": [{"from_key": "a", "to_key": "b"}],
    }
    payload.update(overrides)
    return payload


class TestGraphValidationApi:
    def test_cycle_rejected_with_cycle_path(self, client):
        payload = valid_payload(
            nodes=[{"key": k} for k in ("a", "b", "c")],
            edges=[
                {"from_key": "a", "to_key": "b"},
                {"from_key": "b", "to_key": "c"},
                {"from_key": "c", "to_key": "a"},
            ],
        )
        resp = client.post("/api/graphs", json=payload)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["cycle"] is not None
        assert set(detail["cycle"][:-1]) == {"a", "b", "c"}
        assert any("环" in e for e in detail["errors"])

    def test_edge_to_missing_node_rejected(self, client):
        payload = valid_payload(edges=[{"from_key": "a", "to_key": "ghost"}])
        resp = client.post("/api/graphs", json=payload)
        assert resp.status_code == 400
        assert any("不存在的节点" in e and "ghost" in e for e in resp.json()["detail"]["errors"])

    def test_non_positive_concurrency_rejected(self, client):
        for bad in (0, -3):
            resp = client.post("/api/graphs", json=valid_payload(max_parallel=bad))
            assert resp.status_code == 400
            assert any("并发上限必须为正整数" in e for e in resp.json()["detail"]["errors"])

    def test_negative_retries_rejected(self, client):
        payload = valid_payload(nodes=[{"key": "a", "max_retries": -1}])
        resp = client.post("/api/graphs", json=payload)
        assert resp.status_code == 400
        assert any("重试次数不能为负" in e for e in resp.json()["detail"]["errors"])

    def test_negative_duration_rejected(self, client):
        payload = valid_payload(nodes=[{"key": "a", "duration_seconds": -2}])
        resp = client.post("/api/graphs", json=valid_payload(nodes=[{"key": "a", "duration_seconds": -2}]))
        assert resp.status_code == 400
        assert any("模拟时长不能为负" in e for e in resp.json()["detail"]["errors"])

    def test_validate_endpoint_reports_cycle_without_saving(self, client):
        payload = valid_payload(
            nodes=[{"key": "a"}, {"key": "b"}],
            edges=[{"from_key": "a", "to_key": "b"}, {"from_key": "b", "to_key": "a"}],
        )
        resp = client.post("/api/graphs/validate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["cycle"] is not None
        assert client.get("/api/graphs").json() == []  # nothing persisted

    def test_validate_endpoint_ok_with_topo_order(self, client):
        resp = client.post("/api/graphs/validate", json=valid_payload())
        body = resp.json()
        assert body["ok"] is True
        assert body["topo_order"] == ["a", "b"]


class TestGraphAndRunFlow:
    def test_create_get_update_delete_graph(self, client):
        resp = client.post("/api/graphs", json=valid_payload())
        assert resp.status_code == 201
        graph = resp.json()
        assert graph["max_parallel"] == 2
        assert [n["key"] for n in graph["nodes"]] == ["a", "b"]

        got = client.get(f"/api/graphs/{graph['id']}").json()
        assert got["edges"] == [{"from_key": "a", "to_key": "b"}]

        updated = client.put(f"/api/graphs/{graph['id']}", json=valid_payload(name="renamed"))
        assert updated.status_code == 200
        assert updated.json()["name"] == "renamed"

        assert client.delete(f"/api/graphs/{graph['id']}").status_code == 204
        assert client.get(f"/api/graphs/{graph['id']}").status_code == 404

    def test_update_rejects_cycle(self, client):
        graph = client.post("/api/graphs", json=valid_payload()).json()
        bad = valid_payload(edges=[{"from_key": "a", "to_key": "b"}, {"from_key": "b", "to_key": "a"}])
        resp = client.put(f"/api/graphs/{graph['id']}", json=bad)
        assert resp.status_code == 400
        assert resp.json()["detail"]["cycle"] is not None

    def test_start_run_snapshots_and_isolation(self, client):
        graph = client.post("/api/graphs", json=valid_payload()).json()
        r1 = client.post(f"/api/graphs/{graph['id']}/runs").json()
        r2 = client.post(f"/api/graphs/{graph['id']}/runs").json()
        assert r1["id"] != r2["id"]
        assert r1["topo_order"] == ["a", "b"]
        assert {n["node_key"] for n in r1["nodes"]} == {"a", "b"}
        # Each run carries its own node-state rows.
        assert all(n["status"] == "pending" for n in r2["nodes"])

        runs = client.get("/api/runs", params={"graph_id": graph["id"]}).json()
        assert {r["id"] for r in runs} == {r1["id"], r2["id"]}

    def test_cyclic_graph_planted_in_db_cannot_be_run(self, client):
        """Defense in depth: even a cyclic graph that bypasses API validation
        is rejected at run start and never reaches the scheduler."""
        with SessionLocal() as s:
            g = models.Graph(name="evil", max_parallel=1)
            g.nodes.append(models.GraphNode(node_key="a", name="a", duration_seconds=0.1))
            g.nodes.append(models.GraphNode(node_key="b", name="b", duration_seconds=0.1))
            g.edges.append(models.GraphEdge(from_key="a", to_key="b"))
            g.edges.append(models.GraphEdge(from_key="b", to_key="a"))
            s.add(g)
            s.commit()
            gid = g.id

        resp = client.post(f"/api/graphs/{gid}/runs")
        assert resp.status_code == 400
        assert resp.json()["detail"]["cycle"] is not None
        assert client.get("/api/runs").json() == []  # no run was created
