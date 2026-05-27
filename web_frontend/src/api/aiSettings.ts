import { apiGet, apiPut } from "./client";

export type AISettings = {
  shop_id: string;
  internal_enabled: boolean;
  shadow_enabled: boolean;
  send_enabled: boolean;
  no_send_mode: boolean;
  rag_enabled: boolean;
  llm_enabled: boolean;
  intent_classifier_enabled: boolean;
  answer_generator_enabled: boolean;
  guardrail_enabled: boolean;
  product_version: string;
  sop_version: string;
  rag_top_k: number;
  similarity_threshold: number;
  guardrail_strictness: string;
  secret_status: Record<string, string>;
  warning?: string;
};

export function getAISettings(shopId: string) {
  return apiGet<AISettings>(`/api/shops/${shopId}/ai-settings`);
}

export function updateAISettings(shopId: string, body: Partial<AISettings>) {
  return apiPut<AISettings>(`/api/shops/${shopId}/ai-settings`, body);
}
