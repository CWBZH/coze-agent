import { useEffect, useMemo, useState } from "react";

import { getShops, Shop } from "../api/shops";
import {
  getProduct,
  getProductChunks,
  getProductCoverage,
  getProducts,
  Product,
  ProductChunk,
  ProductCoverage,
  ProductDetail,
  ProductQuery
} from "../api/products";
import { retrieveDebug, RagDebugHit } from "../api/rag";
import { DrawerPanel } from "../components/DrawerPanel";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";

type LoadState = "idle" | "loading" | "loaded" | "error";

const COVERAGE_FIELDS: Array<{ key: keyof ProductCoverage; label: string }> = [
  { key: "total", label: "商品总数" },
  { key: "has_price", label: "价格覆盖" },
  { key: "has_specs", label: "规格覆盖" },
  { key: "has_usage", label: "用法覆盖" },
  { key: "has_ingredients", label: "成分覆盖" },
  { key: "has_shelf_life", label: "保质期覆盖" },
  { key: "has_warnings", label: "注意事项覆盖" },
  { key: "has_manual_notes", label: "人工备注覆盖" }
];

function statusTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (!status) return "neutral";
  if (["synced", "ready", "indexed", "succeeded", "active"].includes(status)) return "success";
  if (["archived", "warning", "partial_failed"].includes(status)) return "warning";
  if (["failed", "error"].includes(status)) return "danger";
  return "neutral";
}

function formatDisplayDate(value: string) {
  if (!value) return "未更新";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function joinSpecs(specs: string[]) {
  return specs.length > 0 ? specs.join(" / ") : "暂无规格";
}

function CoveragePanel({ coverage }: { coverage: ProductCoverage | null }) {
  if (!coverage) return <div className="state-card">字段覆盖率尚未加载。</div>;
  const total = coverage.total || 0;
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h3>商品知识字段覆盖率</h3>
          <p className="muted">来自 product_knowledge 的真实统计，用于判断商品知识是否足够支撑自动回复。</p>
        </div>
      </div>
      {coverage.warning ? <div className="warning-banner">覆盖率提醒：{coverage.warning}</div> : null}
      <div className="coverage-grid">
        {COVERAGE_FIELDS.map(({ key, label }) => {
          const value = Number(coverage[key] ?? 0);
          const percent = key === "total" || total === 0 ? 100 : Math.round((value / total) * 100);
          return (
            <div className="coverage-item" key={key}>
              <div className="coverage-row">
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
              <div className="progress-track">
                <span style={{ width: `${Math.min(percent, 100)}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ChunkCard({ chunk }: { chunk: ProductChunk }) {
  return (
    <article className="debug-card">
      <div className="debug-card-header">
        <strong>{chunk.chunk_id}</strong>
        <StatusBadge tone="info">{chunk.domain}</StatusBadge>
      </div>
      <dl className="kv-grid">
        <div><dt>source_type</dt><dd>{chunk.source_type}</dd></div>
        <div><dt>source_id</dt><dd>{chunk.source_id}</dd></div>
        <div><dt>version</dt><dd>{chunk.version || "无"}</dd></div>
        <div><dt>content_hash</dt><dd>{chunk.content_hash || "无"}</dd></div>
        <div><dt>created_at</dt><dd>{chunk.created_at || "无"}</dd></div>
      </dl>
      <p className="debug-content">{chunk.content}</p>
      <details>
        <summary>metadata / 字段来源</summary>
        <pre>{JSON.stringify(chunk.metadata, null, 2)}</pre>
      </details>
    </article>
  );
}

function RagHitCard({ hit }: { hit: RagDebugHit }) {
  return (
    <article className="debug-card">
      <div className="debug-card-header">
        <strong>{hit.chunk_id}</strong>
        <StatusBadge tone="success">{`score ${hit.score}`}</StatusBadge>
      </div>
      <dl className="kv-grid">
        <div><dt>domain</dt><dd>{hit.domain}</dd></div>
        <div><dt>source_type</dt><dd>{hit.source_type}</dd></div>
        <div><dt>source_id</dt><dd>{hit.source_id}</dd></div>
        <div><dt>version</dt><dd>{hit.version || "无"}</dd></div>
      </dl>
      <p className="debug-content">{hit.content}</p>
      <details>
        <summary>metadata / 字段来源</summary>
        <pre>{JSON.stringify(hit.metadata, null, 2)}</pre>
      </details>
    </article>
  );
}

function ProductKnowledgeList({
  products,
  selectedProductKey,
  onSelect
}: {
  products: Product[];
  selectedProductKey?: string;
  onSelect: (product: Product) => void;
}) {
  if (products.length === 0) {
    return <div className="state-card">当前筛选条件下没有商品。</div>;
  }

  return (
    <div className="product-knowledge-list" role="list">
      {products.map((product) => {
        const title = product.goods_name || product.product_title || product.goods_id;
        const productKey = `${product.shop_id}-${product.goods_id}`;
        const isSelected = productKey === selectedProductKey;
        return (
          <button
            className={isSelected ? "product-knowledge-row selected" : "product-knowledge-row"}
            key={productKey}
            onClick={() => onSelect(product)}
            type="button"
          >
            <div className="product-row-main">
              <div className="product-row-title-line">
                <strong>{title}</strong>
                <StatusBadge tone={statusTone(product.knowledge_status)}>{product.knowledge_status || "unknown"}</StatusBadge>
                <StatusBadge tone={statusTone(product.indexed_status)}>{product.indexed_status || "unknown"}</StatusBadge>
              </div>
              <div className="product-row-meta">
                <span>goods_id: {product.goods_id}</span>
                <span>shop: {product.shop_name || product.shop_id}</span>
                <span>version: {product.version || "未发布版本"}</span>
                <span>updated: {formatDisplayDate(product.updated_at)}</span>
              </div>
              {product.archived_at ? <div className="warning-text">已归档：{product.archive_reason || "未填写原因"}</div> : null}
            </div>
            <div className="product-row-facts">
              <span><b>价格</b>{product.price || "未覆盖"}</span>
              <span><b>规格</b>{Array.isArray(product.specs) && product.specs.length ? `${product.specs.length} 项` : "未覆盖"}</span>
              <span><b>用法</b>{product.usage ? "已补充" : "未覆盖"}</span>
              <span><b>注意事项</b>{product.warnings ? "已补充" : "未覆盖"}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function Products() {
  const [shops, setShops] = useState<Shop[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [coverage, setCoverage] = useState<ProductCoverage | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [chunks, setChunks] = useState<ProductChunk[]>([]);
  const [ragHits, setRagHits] = useState<RagDebugHit[]>([]);
  const [warning, setWarning] = useState<string | null>(null);
  const [chunksWarning, setChunksWarning] = useState<string | null>(null);
  const [ragWarning, setRagWarning] = useState<string | null>(null);
  const [listState, setListState] = useState<LoadState>("idle");
  const [coverageState, setCoverageState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [chunksState, setChunksState] = useState<LoadState>("idle");
  const [ragState, setRagState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [chunksError, setChunksError] = useState<string | null>(null);
  const [ragError, setRagError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [shopId, setShopId] = useState("");
  const [version, setVersion] = useState("");
  const [indexedStatus, setIndexedStatus] = useState("");
  const [knowledgeStatus, setKnowledgeStatus] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [ragQuery, setRagQuery] = useState("");
  const [ragDomain, setRagDomain] = useState("product_catalog");
  const [ragVersion, setRagVersion] = useState("real-product-v1");
  const [ragTopK, setRagTopK] = useState(5);

  useEffect(() => {
    getShops()
      .then((data) => setShops(data.items))
      .catch(() => setShops([]));
  }, []);

  useEffect(() => {
    const params: ProductQuery = {
      shop_id: shopId || undefined,
      q: query.trim() || undefined,
      version: version || undefined,
      indexed_status: indexedStatus || undefined,
      include_archived: includeArchived,
      page_size: 100
    };
    setListState("loading");
    setError(null);
    getProducts(params)
      .then((data) => {
        setProducts(data.items);
        setWarning(data.warning ?? null);
        setListState("loaded");
        setDetail(null);
        setChunks([]);
        setChunksWarning(null);
        setRagHits([]);
        setRagWarning(null);
      })
      .catch((err: Error) => {
        setProducts([]);
        setError(err.message);
        setListState("error");
      });
  }, [includeArchived, indexedStatus, query, shopId, version]);

  useEffect(() => {
    setCoverageState("loading");
    getProductCoverage(shopId || undefined)
      .then((data) => {
        setCoverage(data);
        setCoverageState("loaded");
      })
      .catch(() => {
        setCoverage(null);
        setCoverageState("error");
      });
  }, [shopId]);

  function loadProductDetail(row: Product) {
    setDetailState("loading");
    setDetailError(null);
    setChunks([]);
    setChunksWarning(null);
    setChunksState("idle");
    setRagHits([]);
    setRagWarning(null);
    setRagQuery(row.goods_name || row.product_title || row.goods_id);
    setRagVersion("");
    getProduct(row.goods_id, row.shop_id, includeArchived)
      .then((data) => {
        setDetail(data);
        setDetailState("loaded");
      })
      .catch((err: Error) => {
        setDetail(null);
        setDetailError(err.message);
        setDetailState("error");
      });
  }

  function loadChunks() {
    if (!detail) return;
    setChunksState("loading");
    setChunksError(null);
    getProductChunks(detail.goods_id, {
      shop_id: detail.shop_id,
      domain: "product_catalog",
      source_type: "product",
      limit: 20
    })
      .then((data) => {
        setChunks(data.chunks);
        setChunksWarning(data.warning ?? null);
        setChunksState("loaded");
      })
      .catch((err: Error) => {
        setChunks([]);
        setChunksError(err.message);
        setChunksState("error");
      });
  }

  function runRetrieveDebug() {
    if (!detail) return;
    setRagState("loading");
    setRagError(null);
    retrieveDebug({
      shop_id: detail.shop_id,
      query: ragQuery || detail.goods_name || detail.product_title,
      domain: ragDomain,
      version: ragVersion || undefined,
      top_k: ragTopK,
      goods_id: detail.goods_id
    })
      .then((data) => {
        setRagHits(data.hits);
        setRagWarning(data.warning ?? null);
        setRagState("loaded");
      })
      .catch((err: Error) => {
        setRagHits([]);
        setRagError(err.message);
        setRagState("error");
      });
  }

  const filteredProducts = useMemo(() => {
    if (!knowledgeStatus) return products;
    return products.filter((product) => product.knowledge_status === knowledgeStatus);
  }, [knowledgeStatus, products]);

  const knowledgeOptions = Array.from(new Set(products.map((product) => product.knowledge_status))).filter(Boolean);

  return (
    <div className="page-stack">
      <section className="panel intro-panel">
        <h2>商品知识</h2>
        <p>
          查看真实 product_knowledge、字段覆盖、商品详情、正式 RAG chunk 和检索调试。这里不展示密钥凭证，也不会发送 PDD 消息。
        </p>
      </section>

      <CoveragePanel coverage={coverageState === "error" ? null : coverage} />
      {coverageState === "error" ? <div className="warning-banner">字段覆盖率加载失败。</div> : null}

      <div className="content-grid detail-layout">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>商品知识列表</h2>
              <p className="muted">点击商品查看详情、已写入的 chunk，以及一次真实 pgvector 检索结果。</p>
            </div>
            <div className="filters filter-grid products-filter-grid">
              <select value={shopId} onChange={(event) => setShopId(event.target.value)}>
                <option value="">全部店铺</option>
                {shops.map((shop) => <option key={shop.shop_id} value={shop.shop_id}>{shop.shop_name || shop.shop_id}</option>)}
              </select>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 goods_id / 商品名 / 标题" />
              <input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="版本 version" />
              <select value={indexedStatus} onChange={(event) => setIndexedStatus(event.target.value)}>
                <option value="">全部索引状态</option>
                <option value="unknown">unknown</option>
                <option value="indexed">indexed</option>
                <option value="not_indexed">not_indexed</option>
              </select>
              <select value={knowledgeStatus} onChange={(event) => setKnowledgeStatus(event.target.value)}>
                <option value="">全部知识状态</option>
                {knowledgeOptions.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
              <label className="checkbox-row">
                <input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />
                显示归档商品
              </label>
            </div>
          </div>

          <div className="metrics-grid compact-metrics">
            <MetricCard label="当前可见商品" value={filteredProducts.length} caption={`接口加载 ${products.length} 条`} />
            <MetricCard label="覆盖率总数" value={coverage?.total ?? 0} caption="当前店铺筛选" />
            <MetricCard label="有价格" value={coverage?.has_price ?? 0} caption="价格字段覆盖" />
            <MetricCard label="有规格" value={coverage?.has_specs ?? 0} caption="规格字段覆盖" />
          </div>

          {warning ? <div className="warning-banner">接口提醒：{warning}</div> : null}
          {listState === "loading" ? <div className="state-card">正在加载商品...</div> : null}
          {listState === "error" ? <div className="state-card error-state">加载商品失败：{error}</div> : null}
          {listState !== "loading" && listState !== "error" ? (
            <ProductKnowledgeList
              products={filteredProducts}
              selectedProductKey={detail ? `${detail.shop_id}-${detail.goods_id}` : undefined}
              onSelect={loadProductDetail}
            />
          ) : null}
        </section>

        <DrawerPanel title="商品详情">
          {detailState === "loading" ? <div className="state-card">正在加载商品详情...</div> : null}
          {detailState === "error" ? <div className="state-card error-state">加载商品详情失败：{detailError}</div> : null}
          {detail ? (
            <div className="detail-stack">
              {detail.warning ? <div className="warning-banner">详情提醒：{detail.warning}</div> : null}
              <strong>{detail.product_title || detail.goods_name}</strong>
              <dl className="kv-grid">
                <div><dt>goods_id</dt><dd>{detail.goods_id}</dd></div>
                <div><dt>shop_id</dt><dd>{detail.shop_id}</dd></div>
                <div><dt>version</dt><dd>{detail.version}</dd></div>
                <div><dt>状态</dt><dd>{detail.knowledge_status}</dd></div>
                <div><dt>价格</dt><dd>{detail.price || "暂无价格"}</dd></div>
                <div><dt>规格</dt><dd>{joinSpecs(detail.specs)}</dd></div>
                <div><dt>用法</dt><dd>{detail.usage || "暂无用法"}</dd></div>
                <div><dt>成分</dt><dd>{detail.ingredients || "暂无成分"}</dd></div>
                <div><dt>保质期</dt><dd>{detail.shelf_life || "暂无保质期"}</dd></div>
                <div><dt>注意事项</dt><dd>{detail.warnings || "暂无注意事项"}</dd></div>
                <div><dt>人工备注</dt><dd>{detail.manual_notes || "暂无人工备注"}</dd></div>
              </dl>

              <details>
                <summary>原始详情 JSON</summary>
                <pre>{JSON.stringify(detail.raw_detail_json, null, 2)}</pre>
              </details>

              <details open>
                <summary>知识片段 Chunks</summary>
                <div className="button-row">
                  <button type="button" onClick={loadChunks}>加载知识片段</button>
                  <button type="button" onClick={loadChunks}>刷新知识片段</button>
                </div>
                {chunksWarning ? <div className="warning-banner">知识片段提醒：{chunksWarning}</div> : null}
                {chunksState === "loading" ? <div className="state-card">正在加载知识片段...</div> : null}
                {chunksState === "error" ? <div className="state-card error-state">加载知识片段失败：{chunksError}</div> : null}
                {chunksState === "loaded" && chunks.length === 0 ? <p className="muted">当前商品暂未写入正式知识片段。</p> : null}
                {chunks.length > 0 ? (
                  <div className="debug-card-list">
                    {chunks.map((chunk) => <ChunkCard key={chunk.chunk_id} chunk={chunk} />)}
                  </div>
                ) : null}
              </details>

              <details open>
                <summary>RAG 检索调试</summary>
                <div className="rag-debug-form">
                  <input value={ragQuery} onChange={(event) => setRagQuery(event.target.value)} placeholder="检索问题 query" />
                  <select value={ragDomain} onChange={(event) => setRagDomain(event.target.value)}>
                    <option value="product_catalog">product_catalog</option>
                    <option value="product_basic">product_basic</option>
                    <option value="logistics_policy">logistics_policy</option>
                    <option value="after_sales_evidence">after_sales_evidence</option>
                    <option value="promotion_policy">promotion_policy</option>
                    <option value="sensitive_user_safety">sensitive_user_safety</option>
                    <option value="redline_escalation">redline_escalation</option>
                  </select>
                  <input value={ragVersion} onChange={(event) => setRagVersion(event.target.value)} placeholder="版本 version" />
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={ragTopK}
                    onChange={(event) => setRagTopK(Number(event.target.value) || 5)}
                    placeholder="top_k"
                  />
                  <button type="button" onClick={runRetrieveDebug}>执行 RAG 调试</button>
                </div>
                {ragWarning ? <div className="warning-banner">RAG 提醒：{ragWarning}</div> : null}
                {ragState === "loading" ? <div className="state-card">正在执行 RAG 检索调试...</div> : null}
                {ragState === "error" ? <div className="state-card error-state">RAG 检索调试失败：{ragError}</div> : null}
                {ragState === "loaded" ? <p className="muted">命中数量：{ragHits.length}</p> : null}
                {ragHits.length > 0 ? (
                  <div className="debug-card-list">
                    {ragHits.map((hit) => <RagHitCard key={hit.chunk_id} hit={hit} />)}
                  </div>
                ) : null}
              </details>
            </div>
          ) : null}
          {!detail && detailState === "idle" ? <div className="state-card">请选择一个商品查看完整知识详情。</div> : null}
        </DrawerPanel>
      </div>
    </div>
  );
}
