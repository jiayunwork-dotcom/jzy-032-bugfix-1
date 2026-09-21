/** Thin fetch wrapper around the backend API. */
import type {
  Attempt,
  GraphIn,
  GraphOut,
  GraphSummary,
  RunOut,
  RunSummary,
  ValidationResult,
} from "./types";

export class ApiError extends Error {
  errors: string[];
  cycle: string[] | null;

  constructor(errors: string[], cycle: string[] | null = null, status = 0) {
    super(errors.join("；"));
    this.errors = errors;
    this.cycle = cycle;
    this.name = `ApiError(${status})`;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let errors = [`请求失败: HTTP ${resp.status}`];
    let cycle: string[] | null = null;
    try {
      const body = await resp.json();
      if (body?.detail && typeof body.detail === "object" && "errors" in body.detail) {
        errors = body.detail.errors;
        cycle = body.detail.cycle ?? null;
      } else if (typeof body?.detail === "string") {
        errors = [body.detail];
      }
    } catch {
      /* keep default message */
    }
    throw new ApiError(errors, cycle, resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  listGraphs: () => request<GraphSummary[]>("/api/graphs"),
  getGraph: (id: number) => request<GraphOut>(`/api/graphs/${id}`),
  createGraph: (g: GraphIn) =>
    request<GraphOut>("/api/graphs", { method: "POST", body: JSON.stringify(g) }),
  updateGraph: (id: number, g: GraphIn) =>
    request<GraphOut>(`/api/graphs/${id}`, { method: "PUT", body: JSON.stringify(g) }),
  deleteGraph: (id: number) => request<void>(`/api/graphs/${id}`, { method: "DELETE" }),
  validateGraph: (g: GraphIn) =>
    request<ValidationResult>("/api/graphs/validate", { method: "POST", body: JSON.stringify(g) }),
  startRun: (graphId: number) =>
    request<RunOut>(`/api/graphs/${graphId}/runs`, { method: "POST" }),
  listRuns: (graphId?: number) =>
    request<RunSummary[]>(graphId ? `/api/runs?graph_id=${graphId}` : "/api/runs"),
  getRun: (id: number) => request<RunOut>(`/api/runs/${id}`),
  getNodeAttempts: (runId: number, nodeKey: string) =>
    request<Attempt[]>(`/api/runs/${runId}/nodes/${encodeURIComponent(nodeKey)}/attempts`),
};
