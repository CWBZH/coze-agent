import { apiDelete, apiGet, apiPost, apiPut } from "./client";

export type KnowledgeList<T> = {
  items: T[];
  total: number;
};

export type SopRecord = {
  id: number;
  shop_id: string;
  domain: string;
  title: string;
  content: string;
  status: string;
  content_hash: string;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeVersion = {
  id: number;
  shop_id: string;
  source_type: string;
  source_id: string;
  domain: string;
  version: string;
  content_hash: string;
  snapshot_json: string;
  status: string;
  is_active: number | boolean;
  index_job_id: number | null;
  created_by: string;
  created_at: string;
  indexed_at: string | null;
  activated_at: string | null;
  retired_at: string | null;
  error_summary: string | null;
};

export type KnowledgeIndexJob = {
  id: number;
  shop_id: string;
  version_id: number;
  source_type: string;
  source_id: string;
  domain: string;
  version: string;
  status: string;
  chunk_count: number;
  embedded_count: number;
  indexed_count: number;
  error_summary: string | null;
  retry_count: number;
  index_run_id: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type SopCreatePayload = {
  shop_id: string;
  domain: string;
  title: string;
  content: string;
};

export type SopUpdatePayload = {
  title?: string;
  content?: string;
  expected_content_hash?: string;
};

export type SopPublishResponse = {
  sop: SopRecord;
  version: KnowledgeVersion;
  index_job: KnowledgeIndexJob;
};

export type ProductOverride = {
  id?: number | null;
  shop_id: string;
  goods_id: string;
  goods_name: string | null;
  usage_override: string | null;
  ingredients_override: string | null;
  warnings_override: string | null;
  shelf_life_override: string | null;
  manual_notes: string | null;
  specs_override: string | null;
  price_note_override: string | null;
  status: string;
  content_hash: string;
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ProductOverridePayload = Partial<
  Pick<
    ProductOverride,
    | "goods_name"
    | "usage_override"
    | "ingredients_override"
    | "warnings_override"
    | "shelf_life_override"
    | "manual_notes"
    | "specs_override"
    | "price_note_override"
  >
> & {
  expected_content_hash?: string;
};

export type EffectiveField = {
  value: string | string[] | number | null;
  source: "raw" | "manual_override" | "missing" | string;
};

export type EffectiveProduct = {
  shop_id: string;
  goods_id: string;
  goods_name: string;
  fields: Record<string, EffectiveField>;
  raw: Record<string, unknown>;
  override: ProductOverride | Record<string, unknown>;
};

export type ProductPublishResponse = {
  effective: EffectiveProduct;
  version: KnowledgeVersion;
  index_job: KnowledgeIndexJob;
};

export type IndexRunResponse = {
  version: KnowledgeVersion;
  index_job: KnowledgeIndexJob;
  index_mode?: string;
  error_type?: string;
};

export type IndexRunPayload = {
  mode?: "real";
  embedding_provider?: "doubao" | "ark" | "ollama";
  vector_store?: "pgvector";
};

export type VersionChunk = {
  chunk_id: string;
  version_id: number | null;
  shop_id: string;
  domain: string;
  source_type: string;
  source_id: string;
  version: string;
  content: string;
  content_hash: string;
  chunk_hash: string;
  index_run_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type VersionChunksResponse = {
  version_id: number;
  source_type: string;
  source_id: string;
  domain: string;
  version: string;
  chunks: VersionChunk[];
  warning: string | null;
};

export type SopQuery = {
  shop_id?: string;
  domain?: string;
  status?: string;
};

export type VersionQuery = {
  shop_id?: string;
  source_type?: string;
  source_id?: string;
  domain?: string;
  status?: string;
  is_active?: boolean | string;
};

export type IndexJobQuery = {
  shop_id?: string;
  status?: string;
  source_type?: string;
  source_id?: string;
  version_id?: number | string;
};

function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export function listSop(params: SopQuery = {}) {
  return apiGet<KnowledgeList<SopRecord>>(`/api/knowledge/sop${buildQuery(params)}`);
}

export function createSop(payload: SopCreatePayload) {
  return apiPost<SopRecord>("/api/knowledge/sop", payload);
}

export function getSop(id: number) {
  return apiGet<SopRecord>(`/api/knowledge/sop/${id}`);
}

export function updateSop(id: number, payload: SopUpdatePayload) {
  return apiPut<SopRecord>(`/api/knowledge/sop/${id}`, payload);
}

export function archiveSop(id: number) {
  return apiDelete<SopRecord>(`/api/knowledge/sop/${id}`);
}

export function publishSop(id: number) {
  return apiPost<SopPublishResponse>(`/api/knowledge/sop/${id}/publish`, {});
}

export function getProductOverride(goodsId: string, shopId: string) {
  return apiGet<ProductOverride>(
    `/api/knowledge/products/${encodeURIComponent(goodsId)}/overrides${buildQuery({ shop_id: shopId })}`
  );
}

export function saveProductOverride(goodsId: string, shopId: string, payload: ProductOverridePayload) {
  return apiPut<ProductOverride>(
    `/api/knowledge/products/${encodeURIComponent(goodsId)}/overrides${buildQuery({ shop_id: shopId })}`,
    payload
  );
}

export function getEffectiveProduct(goodsId: string, shopId: string) {
  return apiGet<EffectiveProduct>(
    `/api/knowledge/products/${encodeURIComponent(goodsId)}/effective${buildQuery({ shop_id: shopId })}`
  );
}

export function publishProduct(goodsId: string, shopId: string) {
  return apiPost<ProductPublishResponse>(
    `/api/knowledge/products/${encodeURIComponent(goodsId)}/publish${buildQuery({ shop_id: shopId })}`,
    {}
  );
}

export function listVersions(params: VersionQuery = {}) {
  return apiGet<KnowledgeList<KnowledgeVersion>>(`/api/knowledge/versions${buildQuery(params)}`);
}

export function getVersion(id: number) {
  return apiGet<KnowledgeVersion>(`/api/knowledge/versions/${id}`);
}

export function getVersionChunks(id: number, limit = 20) {
  return apiGet<VersionChunksResponse>(`/api/knowledge/versions/${id}/chunks${buildQuery({ limit })}`);
}

export function listIndexJobs(params: IndexJobQuery = {}) {
  return apiGet<KnowledgeList<KnowledgeIndexJob>>(`/api/knowledge/index-jobs${buildQuery(params)}`);
}

export function getIndexJob(id: number) {
  return apiGet<KnowledgeIndexJob>(`/api/knowledge/index-jobs/${id}`);
}

export function runIndexJob(
  id: number,
  payload: IndexRunPayload = { mode: "real", embedding_provider: "doubao", vector_store: "pgvector" }
) {
  return apiPost<IndexRunResponse>(`/api/knowledge/index-jobs/${id}/run`, {
    mode: "real",
    embedding_provider: "doubao",
    vector_store: "pgvector",
    ...payload,
  });
}

export function retryIndexJob(id: number) {
  return apiPost<KnowledgeIndexJob>(`/api/knowledge/index-jobs/${id}/retry`, {});
}
