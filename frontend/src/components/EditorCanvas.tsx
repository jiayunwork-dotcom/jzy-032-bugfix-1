import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, ApiError } from "../api";
import type { GraphIn, GraphOut } from "../types";
import TaskNode, { type TaskFlowNode } from "./TaskNode";
import NodePanel from "./NodePanel";

const nodeTypes = { task: TaskNode };

interface Props {
  graphId: number | null;
  onBack: () => void;
  onRunStarted: (runId: number) => void;
  onSaved: (id: number) => void;
}

let keyCounter = 1;
function nextKey(existing: Set<string>): string {
  while (existing.has(`n${keyCounter}`)) keyCounter += 1;
  return `n${keyCounter++}`;
}

function edgeId(source: string, target: string) {
  return `${source}->${target}`;
}

function graphToFlow(graph: GraphOut): { nodes: TaskFlowNode[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map((n) => ({
      id: n.key,
      type: "task" as const,
      position: { x: n.x, y: n.y },
      data: {
        name: n.name,
        duration_seconds: n.duration_seconds,
        fail_times: n.fail_times,
        always_fail: n.always_fail,
        max_retries: n.max_retries,
        retry_interval_seconds: n.retry_interval_seconds,
      },
    })),
    edges: graph.edges.map((e) => ({
      id: edgeId(e.from_key, e.to_key),
      source: e.from_key,
      target: e.to_key,
      markerEnd: { type: MarkerType.ArrowClosed },
    })),
  };
}

/** Demo graph: diamond + independent branch + a flaky node that recovers on retry. */
function sampleFlow(): { nodes: TaskFlowNode[]; edges: Edge[] } {
  const specs: Array<[string, number, number, Partial<TaskFlowNode["data"]>]> = [
    ["extract", 60, 60, { duration_seconds: 1 }],
    ["transform_a", 320, 0, { duration_seconds: 1.5 }],
    ["transform_b", 320, 140, { duration_seconds: 1 }],
    ["flaky_job", 320, 280, { duration_seconds: 0.8, fail_times: 1, max_retries: 2, retry_interval_seconds: 1 }],
    ["join", 580, 70, { duration_seconds: 0.5 }],
    ["report", 580, 280, { duration_seconds: 0.5 }],
  ];
  const nodes: TaskFlowNode[] = specs.map(([key, x, y, patch]) => ({
    id: key,
    type: "task" as const,
    position: { x, y },
    data: {
      name: key,
      duration_seconds: 1,
      fail_times: 0,
      always_fail: false,
      max_retries: 0,
      retry_interval_seconds: 1,
      ...patch,
    },
  }));
  const links: Array<[string, string]> = [
    ["extract", "transform_a"],
    ["extract", "transform_b"],
    ["extract", "flaky_job"],
    ["transform_a", "join"],
    ["transform_b", "join"],
    ["flaky_job", "report"],
  ];
  return {
    nodes,
    edges: links.map(([a, b]) => ({
      id: edgeId(a, b),
      source: a,
      target: b,
      markerEnd: { type: MarkerType.ArrowClosed },
    })),
  };
}

export default function EditorCanvas({ graphId, onBack, onRunStarted, onSaved }: Props) {
  const [name, setName] = useState("未命名编排");
  const [maxParallel, setMaxParallel] = useState("3");
  const [nodes, setNodes] = useState<TaskFlowNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [cycle, setCycle] = useState<string[] | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (graphId == null) return;
    api
      .getGraph(graphId)
      .then((g) => {
        const flow = graphToFlow(g);
        setName(g.name);
        setMaxParallel(String(g.max_parallel));
        setNodes(flow.nodes);
        setEdges(flow.edges);
      })
      .catch((e) => setErrors([`加载图失败: ${e.message}`]));
  }, [graphId]);

  const onNodesChange = useCallback(
    (changes: NodeChange<TaskFlowNode>[]) => setNodes((ns) => applyNodeChanges(changes, ns)),
    []
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges((es) => applyEdgeChanges(changes, es)),
    []
  );
  const onConnect = useCallback((conn: Connection) => {
    if (!conn.source || !conn.target) return;
    setEdges((es) => {
      const id = edgeId(conn.source, conn.target);
      if (es.some((e) => e.id === id)) return es;
      return addEdge({ ...conn, id, markerEnd: { type: MarkerType.ArrowClosed } }, es);
    });
  }, []);

  const buildPayload = useCallback((): GraphIn => {
    return {
      name: name.trim() || "未命名编排",
      max_parallel: Number.parseInt(maxParallel, 10),
      nodes: nodes.map((n) => ({
        key: n.id,
        name: n.data.name || n.id,
        duration_seconds: n.data.duration_seconds,
        fail_times: n.data.fail_times,
        always_fail: n.data.always_fail,
        max_retries: n.data.max_retries,
        retry_interval_seconds: n.data.retry_interval_seconds,
        x: n.position.x,
        y: n.position.y,
      })),
      edges: edges.map((e) => ({ from_key: e.source, to_key: e.target })),
    };
  }, [name, maxParallel, nodes, edges]);

  const showFailure = useCallback((e: unknown) => {
    if (e instanceof ApiError) {
      setErrors(e.errors);
      setCycle(e.cycle);
    } else if (e instanceof Error) {
      setErrors([e.message]);
    }
    setInfo(null);
  }, []);

  /** Returns the saved graph id, or null when validation rejected the graph. */
  const save = useCallback(async (): Promise<number | null> => {
    setBusy(true);
    setErrors([]);
    setCycle(null);
    try {
      const payload = buildPayload();
      const saved = graphId
        ? await api.updateGraph(graphId, payload)
        : await api.createGraph(payload);
      setInfo(`已保存 · 拓扑序: ${saved.nodes.map((n) => n.key).join(" → ") || "(空)"}`);
      if (!graphId) onSaved(saved.id);
      return saved.id;
    } catch (e) {
      showFailure(e);
      return null;
    } finally {
      setBusy(false);
    }
  }, [buildPayload, graphId, onSaved, showFailure]);

  const handleValidate = useCallback(async () => {
    setBusy(true);
    try {
      const result = await api.validateGraph(buildPayload());
      if (result.ok) {
        setErrors([]);
        setCycle(null);
        setInfo(`校验通过 · 拓扑序: ${(result.topo_order ?? []).join(" → ")}`);
      } else {
        setErrors(result.errors);
        setCycle(result.cycle);
        setInfo(null);
      }
    } catch (e) {
      showFailure(e);
    } finally {
      setBusy(false);
    }
  }, [buildPayload, showFailure]);

  const handleRun = useCallback(async () => {
    const id = await save();
    if (id == null) return; // 校验失败（如成环）时阻止运行
    setBusy(true);
    try {
      const run = await api.startRun(id);
      onRunStarted(run.id);
    } catch (e) {
      showFailure(e);
    } finally {
      setBusy(false);
    }
  }, [save, onRunStarted, showFailure]);

  const addNode = useCallback(() => {
    setNodes((ns) => {
      const key = nextKey(new Set(ns.map((n) => n.id)));
      const idx = ns.length;
      return [
        ...ns,
        {
          id: key,
          type: "task" as const,
          position: { x: 60 + (idx % 4) * 240, y: 60 + Math.floor(idx / 4) * 130 },
          data: {
            name: key,
            duration_seconds: 1,
            fail_times: 0,
            always_fail: false,
            max_retries: 0,
            retry_interval_seconds: 1,
          },
        },
      ];
    });
  }, []);

  const loadSample = useCallback(() => {
    const flow = sampleFlow();
    setName("示例：ETL 编排");
    setMaxParallel("3");
    setNodes(flow.nodes);
    setEdges(flow.edges);
    setErrors([]);
    setCycle(null);
    setInfo("已载入示例图，保存后可运行");
  }, []);

  const updateSelected = useCallback(
    (patch: Partial<TaskFlowNode["data"]>) => {
      if (!selectedKey) return;
      setNodes((ns) =>
        ns.map((n) => (n.id === selectedKey ? { ...n, data: { ...n.data, ...patch } } : n))
      );
    },
    [selectedKey]
  );

  const deleteSelected = useCallback(() => {
    if (!selectedKey) return;
    setNodes((ns) => ns.filter((n) => n.id !== selectedKey));
    setEdges((es) => es.filter((e) => e.source !== selectedKey && e.target !== selectedKey));
    setSelectedKey(null);
  }, [selectedKey]);

  const cycleSet = useMemo(() => new Set(cycle ?? []), [cycle]);
  const displayNodes = useMemo(
    () =>
      nodes.map((n) => ({
        ...n,
        data: { ...n.data, inCycle: cycleSet.has(n.id) },
      })),
    [nodes, cycleSet]
  );
  const selectedNode = nodes.find((n) => n.id === selectedKey) ?? null;

  return (
    <div className="editor-layout">
      <div className="toolbar">
        <button className="btn" onClick={onBack}>← 返回</button>
        <input
          className="graph-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="编排名称"
        />
        <label className="inline-field">
          并发上限
          <input
            type="number"
            min={1}
            step={1}
            value={maxParallel}
            onChange={(e) => setMaxParallel(e.target.value)}
          />
        </label>
        <button className="btn" onClick={addNode}>+ 添加节点</button>
        <button className="btn" onClick={loadSample}>载入示例</button>
        <span className="spacer" />
        <button className="btn" disabled={busy} onClick={handleValidate}>校验</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>保存</button>
        <button
          className="btn btn-success"
          disabled={busy || nodes.length === 0}
          onClick={handleRun}
        >
          ▶ 保存并运行
        </button>
      </div>

      {errors.length > 0 && (
        <div className="banner banner-error">
          <strong>{cycle ? "保存被拒绝：图中存在环" : "校验未通过"}</strong>
          <ul>
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
          {cycle && <div className="cycle-path">环路: {cycle.join(" → ")}</div>}
        </div>
      )}
      {info && <div className="banner banner-info">{info}</div>}

      <div className="canvas-row">
        <div className="canvas-wrap">
          <ReactFlow
            nodes={displayNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelectedKey(node.id)}
            onPaneClick={() => setSelectedKey(null)}
            deleteKeyCode={["Backspace", "Delete"]}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={16} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        {selectedNode && (
          <NodePanel
            nodeKey={selectedNode.id}
            data={selectedNode.data}
            onChange={updateSelected}
            onDelete={deleteSelected}
            onClose={() => setSelectedKey(null)}
          />
        )}
      </div>
      <div className="hint">
        操作：拖拽移动节点 · 从节点右侧圆点拖到另一节点左侧圆点建立依赖 · 选中后 Delete 删除 · 点击节点配置时长/成败/重试
      </div>
    </div>
  );
}
