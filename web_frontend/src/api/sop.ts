import { apiGet } from "./client";

export type SopRecord = {
  id: string;
  shop_id: string;
  domain: string;
  title: string;
  version: string;
  status: string;
  indexed: boolean;
  updated_at: string;
};

export type SopDetail = SopRecord & {
  content: string;
  published_at: string | null;
};

export function getSopRecords() {
  return apiGet<{ items: SopRecord[]; total: number }>("/api/sop");
}

export function getSopDetail(id: string) {
  return apiGet<SopDetail>(`/api/sop/${id}`);
}
