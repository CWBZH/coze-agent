import { apiGet, apiPost } from "./client";

export type ProductSyncJobItem = {
  id: string;
  job_id: string;
  shop_id: string;
  goods_id?: string | null;
  goods_name?: string | null;
  status: string;
  error_summary?: string | null;
  created_at: string;
  updated_at: string;
};

export type ProductSyncJob = {
  id: string;
  shop_id: string;
  internal_shop_id?: number | null;
  status: string;
  mode: string;
  total_count: number;
  succeeded_count: number;
  failed_count: number;
  skipped_count: number;
  coverage_json?: Record<string, unknown> | null;
  error_summary?: string | null;
  created_by?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at: string;
  items?: ProductSyncJobItem[];
};

export type ProductSyncCoverage = {
  shop_id: string;
  total: number;
  has_price: number;
  has_specs: number;
  has_usage: number;
  has_ingredients: number;
  has_shelf_life: number;
  has_warnings: number;
  has_manual_notes: number;
  last_sync_at?: string | null;
  warning?: string | null;
};

export function createProductSyncJob(shopId: string, limit = 10) {
  return apiPost<ProductSyncJob>(`/api/shops/${encodeURIComponent(shopId)}/product-sync/jobs`, {
    mode: "full",
    operator: "local_admin",
    limit
  });
}

export function listProductSyncJobs(shopId: string, limit = 20) {
  return apiGet<ProductSyncJob[]>(`/api/shops/${encodeURIComponent(shopId)}/product-sync/jobs?limit=${limit}`);
}

export function getProductSyncJob(shopId: string, jobId: string) {
  return apiGet<ProductSyncJob>(`/api/shops/${encodeURIComponent(shopId)}/product-sync/jobs/${encodeURIComponent(jobId)}`);
}

export function retryProductSyncJob(shopId: string, jobId: string) {
  return apiPost<ProductSyncJob>(`/api/shops/${encodeURIComponent(shopId)}/product-sync/jobs/${encodeURIComponent(jobId)}/retry`, {});
}

export function getProductSyncCoverage(shopId: string) {
  return apiGet<ProductSyncCoverage>(`/api/shops/${encodeURIComponent(shopId)}/product-sync/coverage`);
}
