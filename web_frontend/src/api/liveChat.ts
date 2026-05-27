import { apiPost } from "./client";

export type LiveChatSession = {
  session_id: string;
  no_send: boolean;
  engine: string;
  shop_id?: string | null;
  buyer_id?: string | null;
};

export type LiveChatMessageRequest = {
  shop_id: string;
  buyer_id?: string | null;
  message: string;
  metadata?: {
    goods_id?: string | null;
    goods_name?: string | null;
  };
  use_rag?: boolean;
  use_llm_intent_classifier?: boolean;
  use_llm_answer_generator?: boolean;
  use_real_engine?: boolean;
  use_real_llm?: boolean;
  use_real_ollama?: boolean;
  use_real_pgvector?: boolean;
  use_real_intent_classifier?: boolean;
  use_real_answer_generator?: boolean;
  product_version?: string;
  sop_version?: string;
  rag_top_k?: number;
  smoke_profile?: string;
  no_send?: boolean;
};

export type LiveChatResponse = {
  reply: string;
  action: string;
  intent: string;
  domain: string | null;
  session_id: string;
  no_send: boolean;
  trace: Record<string, unknown>;
};

export function createLiveChatSession(shopId: string, buyerId?: string) {
  return apiPost<LiveChatSession>("/api/live-chat/sessions", { shop_id: shopId, buyer_id: buyerId });
}

export function sendLiveChatMessage(sessionId: string, body: LiveChatMessageRequest) {
  return apiPost<LiveChatResponse>(`/api/live-chat/sessions/${sessionId}/messages`, body);
}
