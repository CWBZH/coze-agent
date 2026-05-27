import { apiGet } from "./client";

export type Product = {
  goods_id: string;
  goods_name: string;
  product_title: string;
  shop_id: string;
  shop_name: string;
  version: string;
  knowledge_status: string;
  indexed_status: string;
  updated_at: string;
  price: string;
  specs: string[];
  usage: string;
  ingredients: string;
  shelf_life: string;
  warnings: string;
};

export type ProductCoverage = {
  total: number;
  has_price: number;
  has_specs: number;
  has_usage: number;
  has_ingredients: number;
  has_shelf_life: number;
  has_warnings: number;
  has_manual_notes: number;
  warning?: string;
};

export type ProductDetail = Product & {
  manual_notes: string;
  raw_detail_json: Record<string, unknown>;
  chunks: ProductChunk[];
  warning?: string | null;
};

export type ProductChunk = {
  chunk_id: string;
  shop_id: string;
  domain: string;
  source_type: string;
  source_id: string;
  version: string;
  content: string;
  content_hash: string;
  metadata: Record<string, unknown>;
  created_at: string;
  score?: number | null;
};

export type ProductChunksResponse = {
  goods_id: string;
  shop_id: string;
  version: string;
  chunks: ProductChunk[];
  warning?: string | null;
};

export type ProductQuery = {
  shop_id?: string;
  q?: string;
  version?: string;
  indexed_status?: string;
  page?: number;
  page_size?: number;
};

function buildQuery(params: ProductQuery): string {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export function getProducts(params: ProductQuery = {}) {
  return apiGet<{ items: Product[]; total: number; page: number; page_size: number; warning?: string }>(
    `/api/products${buildQuery(params)}`
  );
}

export function getProduct(goodsId: string, shopId?: string) {
  const query = shopId ? `?shop_id=${encodeURIComponent(shopId)}` : "";
  return apiGet<ProductDetail>(`/api/products/${encodeURIComponent(goodsId)}${query}`);
}

export function getProductCoverage(shopId?: string) {
  const query = shopId ? `?shop_id=${encodeURIComponent(shopId)}` : "";
  return apiGet<ProductCoverage>(`/api/products/coverage${query}`);
}

export function getProductChunks(
  goodsId: string,
  params: { shop_id?: string; version?: string; domain?: string; source_type?: string; limit?: number } = {}
) {
  return apiGet<ProductChunksResponse>(`/api/products/${encodeURIComponent(goodsId)}/chunks${buildQuery(params)}`);
}
