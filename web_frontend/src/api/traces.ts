import { apiGet } from "./client";

export type TraceSummary = {
  time: string;
  trace_id: string;
  shop_id: string;
  buyer_id: string;
  session_id: string;
  intent: string;
  domain: string | null;
  action: string;
  rag_hit_count: number;
  final_status: string;
  latency_ms: number;
  no_send: boolean;
};

export function getTraces() {
  return apiGet<{ items: TraceSummary[]; total: number }>("/api/traces");
}

export function getTrace(traceId: string) {
  return apiGet<Record<string, unknown>>(`/api/traces/${traceId}`);
}
