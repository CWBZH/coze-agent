import { apiGet } from "./client";

export type ChainNode = {
  key: string;
  label: string;
  status: "passed" | "failed" | "warning" | "skipped" | string;
  summary: string;
};

export type RagChunk = {
  chunk_id?: string;
  domain?: string;
  source_type?: string;
  source_id?: string;
  title?: string;
  score?: number;
  version?: string;
  content_hash?: string;
  content?: string;
  metadata?: Record<string, unknown>;
};

export type ConversationSummary = {
  shop_id: string;
  buyer_id: string;
  session_id: string;
  last_message: string;
  last_send_text: string;
  last_status: string;
  last_status_label: string;
  failed_count: number;
  message_count: number;
  last_trace_id: string;
  last_active_at: string;
};

export type ConversationMessage = {
  trace_id: string;
  shop_id: string;
  user_id: string;
  buyer_id: string;
  session_id: string;
  message_type: string;
  buyer_message: string;
  generated_reply: string;
  send_text: string;
  final_status: string;
  final_status_label: string;
  status_explanation: string;
  recommended_action: string;
  rag_query: string;
  rag_hit_count: number;
  rag_chunks: RagChunk[];
  prompt_context: Record<string, unknown>;
  reply_generation: Record<string, unknown>;
  send_retry: Record<string, unknown>;
  nodes: ChainNode[];
  timing: Record<string, unknown>;
  technical: Record<string, unknown>;
  created_at_iso: string;
  updated_at_iso: string;
};

export function getConversations(params: { shopId?: string; limit?: number } = {}) {
  const search = new URLSearchParams();
  if (params.shopId) search.set("shop_id", params.shopId);
  if (params.limit) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<{ items: ConversationSummary[]; total: number; warning?: string | null }>(`/api/observability/conversations${suffix}`);
}

export function getConversationMessages(buyerId: string, params: { shopId?: string; limit?: number } = {}) {
  const search = new URLSearchParams();
  if (params.shopId) search.set("shop_id", params.shopId);
  if (params.limit) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<{ items: ConversationMessage[]; total: number }>(
    `/api/observability/conversations/${encodeURIComponent(buyerId)}/messages${suffix}`
  );
}

export function getObservabilityTrace(traceId: string) {
  return apiGet<ConversationMessage>(`/api/observability/traces/${encodeURIComponent(traceId)}`);
}
