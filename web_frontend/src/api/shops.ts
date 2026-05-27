import { apiGet } from "./client";

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

export function getShops() {
  return apiGet<{ items: Shop[]; total: number; warning?: string }>("/api/shops");
}

export function getShop(shopId: string) {
  return apiGet<ShopDetail>(`/api/shops/${encodeURIComponent(shopId)}`);
}
