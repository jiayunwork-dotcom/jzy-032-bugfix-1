import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "../api";
import {
  ATTEMPT_RESULT_LABEL,
  NODE_STATUS_META,
  RUN_STATUS_META,
  fmtDateTime,
  fmtDuration,
  fmtTime,
} from "../status";
import type { Attempt, RunOut } from "../types";
import TaskNode, { type TaskFlowNode } from "./TaskNode";

const nodeTypes = { task: TaskNode };
const TERMINAL = new Set(["succeeded", "failed"]);

interface Props {
  runId: number;
  onBack: () => void;
  onEditGraph: (graphId: number) => void;
}

/** Read-only live view of one run: nodes colored by status, polling the
 * backend; clicking a node shows its retry history and timings. */
export default function RunView({ runId, onBack, onEditGraph }: Props) {
  const [run, setRun] = useState<RunOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api.getRun(runId);
        if (stop) return;
        setRun(r);
        if (!TERMINAL.has(r.status)) {
          timer = setTimeout(poll, 600);
        }
      } catch (e) {
        if (!stop) setError(e instanceof Error ? e.message : String(e));
      }
    };
    poll();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [runId]);

  const loadAttempts = useCallback(
    async (nodeKey: string) => {
      try {
        setAttempts(await api.getNodeAttempts(runId, nodeKey));
      } catch {
        setAttempts([]);
      }
    },
    [runId]
  );

  useEffect(() => {
    if (selectedKey) loadAttempts(selectedKey);
  }, [selectedKey, loadAttempts, run]); // refresh history as the run progresses

  const flowNodes: TaskFlowNode[] = useMemo(
    () =>
      (run?.nodes ?? []).map((n) => ({
        id: n.node_key,
        type: "task" as const,
        position: { x: n.x, y: n.y },
        data: {
          name: n.name,
          duration_seconds: n.duration_seconds,
          fail_times: n.fail_times,
          always_fail: n.always_fail,
          max_retries: n.max_retries,
          retry_interval_seconds: n.retry_interval_seconds,
          status: n.status,
          attempts: n.attempts,
        },
      })),
    [run]
  );
  const flowEdges: Edge[] = useMemo(
    () =>
      (run?.edges ?? []).map((e) => ({
        id: `${e.from_key}->${e.to_key}`,
        source: e.from_key,
        target: e.to_key,
        markerEnd: { type: MarkerType.ArrowClosed },
      })),
    [run]
  );

  const selected = run?.nodes.find((n) => n.node_key === selectedKey) ?? null;
  const runMeta = run ? RUN_STATUS_META[run.status] : null;

  if (error) {
    return (
      <div className="panel-page">
        <button className="btn" onClick={onBack}>← 返回</button>
        <div className="banner banner-error">加载运行失败: {error}</div>
      </div>
    );
  }
  if (!run) return <div className="panel-page">加载中…</div>;

  return (
    <div className="editor-layout">
      <div className="toolbar">
        <button className="btn" onClick={onBack}>← 返回</button>
        <span className="run-title">
          运行 #{run.id} · {run.graph_name}
        </span>
        {runMeta && (
          <span className="badge" style={{ color: runMeta.color, background: runMeta.bg }}>
            {runMeta.label}
          </span>
        )}
        <span className="muted">并发上限 {run.max_parallel}</span>
        <span className="muted">拓扑序: {run.topo_order.join(" → ")}</span>
        <span className="spacer" />
        <span className="muted">
          开始 {fmtTime(run.started_at)} · 结束 {fmtTime(run.finished_at)} · 总耗时{" "}
          {fmtDuration(run.started_at, run.finished_at)}
        </span>
        <button className="btn" onClick={() => onEditGraph(run.graph_id)}>编辑图</button>
      </div>

      <div className="legend">
        {Object.entries(NODE_STATUS_META).map(([key, m]) => (
          <span key={key} className="legend-item">
            <i style={{ background: m.bg, borderColor: m.border }} />
            {m.label}
          </span>
        ))}
      </div>

      <div className="canvas-row">
        <div className="canvas-wrap">
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            onNodeClick={(_, node) => setSelectedKey(node.id)}
            onPaneClick={() => setSelectedKey(null)}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={16} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>

        {selected && (
          <aside className="side-panel">
            <div className="panel-title">
              <span>节点 · {selected.name}</span>
              <button className="btn btn-ghost" onClick={() => setSelectedKey(null)}>✕</button>
            </div>
            <div className="kv">
              <span>状态</span>
              <b style={{ color: NODE_STATUS_META[selected.status].color }}>
                {NODE_STATUS_META[selected.status].label}
              </b>
            </div>
            <div className="kv"><span>尝试次数</span><b>{selected.attempts}</b></div>
            <div className="kv"><span>开始</span><b>{fmtTime(selected.started_at)}</b></div>
            <div className="kv"><span>结束</span><b>{fmtTime(selected.finished_at)}</b></div>
            <div className="kv">
              <span>耗时</span><b>{fmtDuration(selected.started_at, selected.finished_at)}</b>
            </div>
            <div className="kv">
              <span>策略</span>
              <b>
                ⏱{selected.duration_seconds}s · ↻{selected.max_retries}次/
                {selected.retry_interval_seconds}s
                {selected.always_fail ? " · 必失败" : selected.fail_times > 0 ? ` · 前${selected.fail_times}次失败` : ""}
              </b>
            </div>
            {selected.last_error && <div className="node-error">{selected.last_error}</div>}

            <div className="panel-subtitle">重试历史</div>
            {attempts.length === 0 ? (
              <div className="muted">尚无执行记录</div>
            ) : (
              <table className="table">
                <thead>
                  <tr><th>#</th><th>结果</th><th>开始</th><th>耗时</th></tr>
                </thead>
                <tbody>
                  {attempts.map((a) => (
                    <tr key={a.attempt_no}>
                      <td>{a.attempt_no}</td>
                      <td>{ATTEMPT_RESULT_LABEL[a.result] ?? a.result}</td>
                      <td>{fmtDateTime(a.started_at)}</td>
                      <td>{fmtDuration(a.started_at, a.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
