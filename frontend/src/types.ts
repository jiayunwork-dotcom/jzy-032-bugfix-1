/** API payload types mirroring the backend schemas. */

export interface NodeSpec {
  key: string;
  name: string;
  duration_seconds: number;
  fail_times: number;
  always_fail: boolean;
  max_retries: number;
  retry_interval_seconds: number;
  x: number;
  y: number;
}

export interface EdgeSpec {
  from_key: string;
  to_key: string;
}

export interface GraphIn {
  name: string;
  max_parallel: number;
  nodes: NodeSpec[];
  edges: EdgeSpec[];
}

export interface GraphOut extends GraphIn {
  id: number;
  created_at: string;
  updated_at: string;
}

export interface GraphSummary {
  id: number;
  name: string;
  max_parallel: number;
  node_count: number;
  edge_count: number;
  updated_at: string;
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  cycle: string[] | null;
  topo_order: string[] | null;
}

export type NodeStatus =
  | "pending"
  | "ready"
  | "running"
  | "retry_wait"
  | "succeeded"
  | "failed"
  | "skipped";

export interface RunNode {
  node_key: string;
  name: string;
  status: NodeStatus;
  attempts: number;
  next_retry_at: string | null;
  last_error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number;
  fail_times: number;
  always_fail: boolean;
  max_retries: number;
  retry_interval_seconds: number;
  x: number;
  y: number;
}

export interface RunOut {
  id: number;
  graph_id: number;
  graph_name: string;
  status: string;
  max_parallel: number;
  topo_order: string[];
  edges: EdgeSpec[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  nodes: RunNode[];
}

export interface RunSummary {
  id: number;
  graph_id: number;
  graph_name: string;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Attempt {
  attempt_no: number;
  result: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}
