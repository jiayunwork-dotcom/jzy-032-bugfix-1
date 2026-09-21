/** Status display metadata (colors shared by canvas nodes, badges, legend)
 * and small formatting helpers. */

export const NODE_STATUS_META: Record<
  string,
  { label: string; color: string; bg: string; border: string }
> = {
  pending: { label: "等待", color: "#6b7280", bg: "#f3f4f6", border: "#d1d5db" },
  ready: { label: "就绪", color: "#1d4ed8", bg: "#dbeafe", border: "#3b82f6" },
  running: { label: "运行中", color: "#b45309", bg: "#fef3c7", border: "#f59e0b" },
  retry_wait: { label: "重试等待", color: "#c2410c", bg: "#ffedd5", border: "#f97316" },
  succeeded: { label: "成功", color: "#15803d", bg: "#dcfce7", border: "#22c55e" },
  failed: { label: "失败", color: "#b91c1c", bg: "#fee2e2", border: "#ef4444" },
  skipped: { label: "跳过(不满足)", color: "#4b5563", bg: "#e5e7eb", border: "#9ca3af" },
};

export const RUN_STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: "等待调度", color: "#6b7280", bg: "#f3f4f6" },
  running: { label: "运行中", color: "#b45309", bg: "#fef3c7" },
  succeeded: { label: "成功", color: "#15803d", bg: "#dcfce7" },
  failed: { label: "失败", color: "#b91c1c", bg: "#fee2e2" },
};

export const ATTEMPT_RESULT_LABEL: Record<string, string> = {
  running: "执行中",
  success: "成功",
  failure: "失败",
  interrupted: "中断(重启)",
};

/** Backend timestamps are naive UTC ISO strings; parse them as UTC. */
export function parseUtc(s: string | null | undefined): Date | null {
  if (!s) return null;
  return new Date(s.endsWith("Z") ? s : s + "Z");
}

export function fmtTime(s: string | null | undefined): string {
  const d = parseUtc(s);
  return d ? d.toLocaleTimeString("zh-CN", { hour12: false }) : "—";
}

export function fmtDateTime(s: string | null | undefined): string {
  const d = parseUtc(s);
  return d ? d.toLocaleString("zh-CN", { hour12: false }) : "—";
}

export function fmtDuration(start: string | null | undefined, end: string | null | undefined): string {
  const a = parseUtc(start);
  const b = parseUtc(end);
  if (!a || !b) return "—";
  const sec = (b.getTime() - a.getTime()) / 1000;
  return sec < 1 ? `${Math.round(sec * 1000)}ms` : `${sec.toFixed(2)}s`;
}
