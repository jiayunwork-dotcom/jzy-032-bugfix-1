import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { RUN_STATUS_META, fmtDateTime, fmtDuration } from "../status";
import type { GraphSummary, RunSummary } from "../types";

interface Props {
  onEdit: (graphId: number | null) => void;
  onOpenRun: (runId: number) => void;
}

/** Landing page: orchestration graphs with run/edit actions, plus recent runs. */
export default function GraphList({ onEdit, onOpenRun }: Props) {
  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [g, r] = await Promise.all([api.listGraphs(), api.listRuns()]);
      setGraphs(g);
      setRuns(r);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [load]);

  const handleRun = async (graphId: number) => {
    try {
      const run = await api.startRun(graphId);
      onOpenRun(run.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.errors.join("；") : String(e));
    }
  };

  const handleDelete = async (graphId: number) => {
    if (!window.confirm("确定删除该编排图及其所有运行记录？")) return;
    await api.deleteGraph(graphId);
    load();
  };

  return (
    <div className="panel-page">
      <div className="section-head">
        <h2>编排图</h2>
        <button className="btn btn-primary" onClick={() => onEdit(null)}>+ 新建编排</button>
      </div>
      {error && <div className="banner banner-error">{error}</div>}
      {graphs.length === 0 ? (
        <div className="empty">还没有编排图，点击「新建编排」开始拖拽设计。</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>ID</th><th>名称</th><th>节点数</th><th>连线数</th><th>并发上限</th><th>更新时间</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {graphs.map((g) => (
              <tr key={g.id}>
                <td>{g.id}</td>
                <td>{g.name}</td>
                <td>{g.node_count}</td>
                <td>{g.edge_count}</td>
                <td>{g.max_parallel}</td>
                <td>{fmtDateTime(g.updated_at)}</td>
                <td className="actions">
                  <button className="btn btn-success" onClick={() => handleRun(g.id)}>▶ 运行</button>
                  <button className="btn" onClick={() => onEdit(g.id)}>编辑</button>
                  <button className="btn btn-danger" onClick={() => handleDelete(g.id)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="section-head">
        <h2>运行记录</h2>
      </div>
      {runs.length === 0 ? (
        <div className="empty">暂无运行。</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>运行</th><th>编排图</th><th>状态</th><th>创建时间</th><th>耗时</th><th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const meta = RUN_STATUS_META[r.status] ?? RUN_STATUS_META.pending;
              return (
                <tr key={r.id}>
                  <td>#{r.id}</td>
                  <td>{r.graph_name}</td>
                  <td>
                    <span className="badge" style={{ color: meta.color, background: meta.bg }}>
                      {meta.label}
                    </span>
                  </td>
                  <td>{fmtDateTime(r.created_at)}</td>
                  <td>{fmtDuration(r.started_at, r.finished_at)}</td>
                  <td className="actions">
                    <button className="btn" onClick={() => onOpenRun(r.id)}>查看</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
