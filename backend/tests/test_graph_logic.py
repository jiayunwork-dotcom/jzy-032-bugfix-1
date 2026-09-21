"""Unit tests for cycle detection, topological ordering and validation rules."""
import pytest

from app.graph_logic import (
    EdgeSpec,
    GraphValidationError,
    NodeSpec,
    find_cycle,
    topological_order,
    validate_graph,
)


def node(key: str, **kw) -> NodeSpec:
    return NodeSpec(key=key, name=key, **kw)


class TestFindCycle:
    def test_acyclic_graph_has_no_cycle(self):
        edges = [EdgeSpec("a", "b"), EdgeSpec("a", "c"), EdgeSpec("b", "d"), EdgeSpec("c", "d")]
        assert find_cycle(["a", "b", "c", "d"], edges) is None

    def test_cycle_is_detected_and_path_named(self):
        edges = [EdgeSpec("a", "b"), EdgeSpec("b", "c"), EdgeSpec("c", "a"), EdgeSpec("a", "d")]
        cycle = find_cycle(["a", "b", "c", "d"], edges)
        assert cycle is not None
        # Path is a real cycle: starts and ends on the same node...
        assert cycle[0] == cycle[-1]
        assert len(cycle) == 4  # three distinct nodes + return to start
        assert set(cycle[:-1]) == {"a", "b", "c"}
        # ...and every consecutive pair is an actual edge of the graph.
        pairs = {(e.from_key, e.to_key) for e in edges}
        for u, v in zip(cycle, cycle[1:]):
            assert (u, v) in pairs

    def test_self_loop_is_a_cycle(self):
        cycle = find_cycle(["a"], [EdgeSpec("a", "a")])
        assert cycle == ["a", "a"]

    def test_cycle_in_disconnected_component(self):
        edges = [EdgeSpec("x", "y"), EdgeSpec("y", "x"), EdgeSpec("p", "q")]
        cycle = find_cycle(["p", "q", "x", "y"], edges)
        assert cycle is not None
        assert set(cycle[:-1]) == {"x", "y"}


class TestTopologicalOrder:
    def test_respects_dependencies(self):
        edges = [EdgeSpec("a", "b"), EdgeSpec("a", "c"), EdgeSpec("b", "d"), EdgeSpec("c", "d")]
        order = topological_order(["a", "b", "c", "d"], edges)
        pos = {k: i for i, k in enumerate(order)}
        for e in edges:
            assert pos[e.from_key] < pos[e.to_key]

    def test_deterministic_across_input_permutations(self):
        edges = [EdgeSpec("b", "c"), EdgeSpec("a", "c")]
        o1 = topological_order(["a", "b", "c"], edges)
        o2 = topological_order(["c", "b", "a"], edges)
        assert o1 == o2 == ["a", "b", "c"]

    def test_cyclic_graph_raises_with_cycle(self):
        edges = [EdgeSpec("a", "b"), EdgeSpec("b", "a")]
        with pytest.raises(GraphValidationError) as excinfo:
            topological_order(["a", "b"], edges)
        assert excinfo.value.cycle is not None


class TestValidateGraph:
    def test_valid_graph_returns_topo_order(self):
        nodes = [node("a"), node("b")]
        order = validate_graph(nodes, [EdgeSpec("a", "b")], max_parallel=2)
        assert order == ["a", "b"]

    def test_empty_graph_rejected(self):
        with pytest.raises(GraphValidationError, match="至少需要一个节点"):
            validate_graph([], [], max_parallel=1)

    @pytest.mark.parametrize("bad", [0, -1, -10])
    def test_non_positive_concurrency_rejected(self, bad):
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a")], [], max_parallel=bad)
        assert any("并发上限必须为正整数" in e for e in excinfo.value.errors)

    def test_negative_retries_rejected(self):
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a", max_retries=-1)], [], max_parallel=1)
        assert any("重试次数不能为负" in e for e in excinfo.value.errors)

    def test_negative_duration_rejected(self):
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a", duration_seconds=-0.5)], [], max_parallel=1)
        assert any("模拟时长不能为负" in e for e in excinfo.value.errors)

    def test_negative_retry_interval_rejected(self):
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a", retry_interval_seconds=-1)], [], max_parallel=1)
        assert any("重试间隔不能为负" in e for e in excinfo.value.errors)

    def test_edge_to_missing_node_rejected(self):
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a")], [EdgeSpec("a", "ghost")], max_parallel=1)
        assert any("不存在的节点" in e and "ghost" in e for e in excinfo.value.errors)

    def test_edge_from_missing_node_rejected(self):
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a")], [EdgeSpec("ghost", "a")], max_parallel=1)
        assert any("不存在的节点" in e and "ghost" in e for e in excinfo.value.errors)

    def test_duplicate_node_key_rejected(self):
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a"), node("a")], [], max_parallel=1)
        assert any("重复" in e for e in excinfo.value.errors)

    def test_cycle_rejected_with_path(self):
        edges = [EdgeSpec("a", "b"), EdgeSpec("b", "c"), EdgeSpec("c", "a")]
        with pytest.raises(GraphValidationError) as excinfo:
            validate_graph([node("a"), node("b"), node("c")], edges, max_parallel=1)
        assert excinfo.value.cycle is not None
        assert set(excinfo.value.cycle[:-1]) == {"a", "b", "c"}
        assert any("环" in e for e in excinfo.value.errors)
