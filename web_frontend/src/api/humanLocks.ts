import { apiGet, apiPost } from "./client";

export type HumanLockItem = {
  id: string;
  shop_id: string;
  buyer_id: string;
  session_id: string;
  status: string;
  reason: string;
  intent: string;
  source: string;
  trace_id: string;
  last_message_preview: string;
  locked_at: string;
  updated_at: string;
  can_unlock: boolean;
};

export type HumanLockListResponse = {
  items: HumanLockItem[];
  total: number;
  shop_id: string;
  warning?: string | null;
};

export type HumanLockUnlockResult = {
  id: string;
  shop_id: string;
  unlocked: boolean;
  already_unlocked: boolean;
  operator: string;
  reason: string;
  updated_at: string;
};

export type HumanLockBatchUnlockResult = {
  shop_id: string;
  matched_count: number;
  unlocked_count: number;
  operator: string;
  reason: string;
};

export type HumanLockListParams = {
  shop_id: string;
  buyer_id?: string;
  session_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
};

function toQuery(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  return search.toString();
}

export function listHumanLocks(params: HumanLockListParams) {
  return apiGet<HumanLockListResponse>(`/api/human-locks?${toQuery(params)}`);
}

export function unlockHumanLock(id: string, payload: { shop_id: string; operator: string; reason: string }) {
  return apiPost<HumanLockUnlockResult>(`/api/human-locks/${encodeURIComponent(id)}/unlock`, payload);
}

export function unlockHumanLocksBySession(payload: {
  shop_id: string;
  buyer_id?: string;
  session_id?: string;
  operator: string;
  reason: string;
}) {
  return apiPost<HumanLockBatchUnlockResult>("/api/human-locks/unlock-by-session", payload);
}

export function bulkUnlockHumanLocks(payload: { shop_id: string; operator: string; reason: string; limit: number }) {
  return apiPost<HumanLockBatchUnlockResult>("/api/human-locks/bulk-unlock", payload);
}
