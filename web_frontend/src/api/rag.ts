import { apiGet, apiPost } from "./client";

export type RagJob = {
  job_id: string;
  shop_id: string;
  source_type: string;
  domain: string;
  version: string;
  status: string;
  chunk_count: number;
  embedded_count: number;
  indexed_count: number;
  dry_run: boolean;
};

export function getRagJobs() {
  return apiGet<{ items: RagJob[]; total: number }>("/api/rag/jobs");
}

export function createRagJob(body: Partial<RagJob>) {
  return apiPost<RagJob>("/api/rag/jobs", body);
}

export type RagDebugRequest = {
  shop_id: string;
  query: string;
  domain: string;
  version?: string;
  top_k: number;
  goods_id?: string;
};

export type RagDebugHit = {
  chunk_id: string;
  content: string;
  score: number;
  domain: string;
  source_type: string;
  source_id: string;
  version: string;
  metadata: Record<string, unknown>;
};

export type RagDebugResponse = {
  query: string;
  shop_id: string;
  domain: string;
  version: string;
  hits: RagDebugHit[];
  connects_pgvector: boolean;
  calls_ollama: boolean;
  warning?: string | null;
};

export function retrieveDebug(body: RagDebugRequest) {
  return apiPost<RagDebugResponse>("/api/rag/retrieve-debug", body);
}
