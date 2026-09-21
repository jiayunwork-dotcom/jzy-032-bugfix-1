import type { TaskNodeData } from "./TaskNode";

interface Props {
  nodeKey: string;
  data: TaskNodeData;
  onChange: (patch: Partial<TaskNodeData>) => void;
  onDelete: () => void;
  onClose: () => void;
}

type FailMode = "never" | "always" | "times";

function failModeOf(d: TaskNodeData): FailMode {
  if (d.always_fail) return "always";
  if (d.fail_times > 0) return "times";
  return "never";
}

/** Side panel editing one node's simulated duration, failure policy and
 * retry strategy. */
export default function NodePanel({ nodeKey, data, onChange, onDelete, onClose }: Props) {
  const num =
    (key: keyof TaskNodeData, min = 0) =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = Number(e.target.value);
      onChange({ [key]: Number.isFinite(v) ? v : 0 } as Partial<TaskNodeData>);
      void min;
    };

  return (
    <aside className="side-panel">
      <div className="panel-title">
        <span>节点配置 · {nodeKey}</span>
        <button className="btn btn-ghost" onClick={onClose}>✕</button>
      </div>

      <label className="field">
        <span>名称</span>
        <input
          value={data.name}
          onChange={(e) => onChange({ name: e.target.value })}
        />
      </label>

      <label className="field">
        <span>模拟时长（秒）</span>
        <input
          type="number" min={0} step={0.1}
          value={data.duration_seconds}
          onChange={num("duration_seconds")}
        />
      </label>

      <label className="field">
        <span>成败策略</span>
        <select
          value={failModeOf(data)}
          onChange={(e) => {
            const mode = e.target.value as FailMode;
            if (mode === "always") onChange({ always_fail: true, fail_times: 0 });
            else if (mode === "times") onChange({ always_fail: false, fail_times: Math.max(1, data.fail_times) });
            else onChange({ always_fail: false, fail_times: 0 });
          }}
        >
          <option value="never">总是成功</option>
          <option value="always">总是失败</option>
          <option value="times">前 N 次失败后成功</option>
        </select>
      </label>

      {failModeOf(data) === "times" && (
        <label className="field">
          <span>失败次数 N</span>
          <input
            type="number" min={1} step={1}
            value={data.fail_times}
            onChange={num("fail_times")}
          />
        </label>
      )}

      <label className="field">
        <span>最大重试次数</span>
        <input
          type="number" min={0} step={1}
          value={data.max_retries}
          onChange={num("max_retries")}
        />
      </label>

      <label className="field">
        <span>重试间隔（秒）</span>
        <input
          type="number" min={0} step={0.1}
          value={data.retry_interval_seconds}
          onChange={num("retry_interval_seconds")}
        />
      </label>

      <button className="btn btn-danger" onClick={onDelete}>删除节点</button>
    </aside>
  );
}
