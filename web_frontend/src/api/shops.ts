import { apiGet, apiPost } from "./client";

export type Shop = {
  shop_id: string;
  shop_name: string;
  channel: string;
  internal_enabled: boolean;
  rag_enabled: boolean;
  llm_enabled: boolean;
  intent_classifier_enabled: boolean;
  answer_generator_enabled: boolean;
  account_status: string;
  websocket_status: string;
  no_send: boolean;
  shadow_enabled: boolean;
  last_activity: string | null;
};

export type ShopDetail = {
  shop_id: string;
  shop_name: string;
  channel: string;
  internal_engine_summary: Record<string, boolean | string | number>;
  product_knowledge_count: number;
  sop_coverage: Record<string, string | number | boolean>;
  rag_index_status: Record<string, string | number | boolean>;
  recent_trace_summary: Record<string, string | number | boolean>;
  warning?: string | null;
};

export type WorkerCommandStatus = "pending" | "running" | "succeeded" | "failed";

export type WorkerCommand = {
  id: string;
  shop_id: string;
  command: "start" | "stop" | "restart";
  status: WorkerCommandStatus;
  requested_by: string | null;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_type: string | null;
  error_summary: string | null;
  trace_id: string;
};

export type WorkerCommandRequest = {
  operator?: string;
  reason?: string | null;
};

export type WorkerCommandListResponse = {
  items: WorkerCommand[];
  total: number;
};

export function getShops() {
  return apiGet<{ items: Shop[]; total: number; warning?: string }>("/api/shops");
}

export function getShop(shopId: string) {
  return apiGet<ShopDetail>(`/api/shops/${encodeURIComponent(shopId)}`);
}

export function requestWorkerStart(shopId: string, body: WorkerCommandRequest = {}) {
  return apiPost<WorkerCommand>(`/api/shops/${encodeURIComponent(shopId)}/worker/start`, body);
}

export function requestWorkerStop(shopId: string, body: WorkerCommandRequest = {}) {
  return apiPost<WorkerCommand>(`/api/shops/${encodeURIComponent(shopId)}/worker/stop`, body);
}

export function requestWorkerRestart(shopId: string, body: WorkerCommandRequest = {}) {
  return apiPost<WorkerCommand>(`/api/shops/${encodeURIComponent(shopId)}/worker/restart`, body);
}

export function getWorkerCommands(shopId: string, limit = 10) {
  return apiGet<WorkerCommandListResponse>(`/api/shops/${encodeURIComponent(shopId)}/worker/commands?limit=${limit}`);
}
