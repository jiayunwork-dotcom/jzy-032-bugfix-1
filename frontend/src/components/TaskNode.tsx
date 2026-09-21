import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { NODE_STATUS_META } from "../status";
import type { NodeStatus } from "../types";

export type TaskNodeData = {
  name: string;
  duration_seconds: number;
  fail_times: number;
  always_fail: boolean;
  max_retries: number;
  retry_interval_seconds: number;
  // run-observation fields (absent in edit mode)
  status?: NodeStatus | null;
  attempts?: number;
  inCycle?: boolean;
};

export type TaskFlowNode = Node<TaskNodeData, "task">;

/** Custom canvas node: shows the task name, its execution/retry policy and,
 * during a run, its live status coloring. */
export default function TaskNode({ data, selected }: NodeProps<TaskFlowNode>) {
  const meta = data.status ? NODE_STATUS_META[data.status] : null;
  const policy = data.always_fail
    ? "必失败"
    : data.fail_times > 0
      ? `前${data.fail_times}次失败`
      : "成功";
  const style: React.CSSProperties = {
    borderColor: data.inCycle ? "#dc2626" : meta ? meta.border : "#94a3b8",
    background: meta ? meta.bg : "#ffffff",
    boxShadow: data.inCycle ? "0 0 0 3px rgba(220,38,38,.35)" : undefined,
  };
  return (
    <div className={`task-node${selected ? " selected" : ""}${data.status === "running" ? " pulsing" : ""}`} style={style}>
      <Handle type="target" position={Position.Left} />
      <div className="task-node-name">{data.name}</div>
      <div className="task-node-sub">
        ⏱ {data.duration_seconds}s · {policy} · ↻{data.max_retries}
      </div>
      {meta && (
        <div className="task-node-status" style={{ color: meta.color }}>
          {meta.label}
          {typeof data.attempts === "number" && data.attempts > 0 && ` · ${data.attempts}次尝试`}
        </div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
