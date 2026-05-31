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
import {
  archiveProduct,
  clearProductOverride,
  EffectiveField,
  EffectiveProduct,
  getEffectiveProduct,
  getProductOverride,
  getVersionChunks,
  KnowledgeVersion,
  listVersions,
  ProductOverride,
  ProductOverridePayload,
  publishProduct,
  restoreProduct,
  saveProductOverride,
  VersionChunk
} from "../api/knowledgeCenter";

type LoadState = "idle" | "loading" | "loaded" | "error";
type TabKey = "fields" | "editor" | "chunks" | "versions" | "raw";

const FIELD_LABELS: Array<{ key: string; label: string }> = [
  { key: "goods_name", label: "商品名" },
  { key: "price", label: "价格" },
  { key: "price_note", label: "价格说明" },
  { key: "specs", label: "规格" },
  { key: "usage", label: "使用方法" },
  { key: "ingredients", label: "成分/卖点" },
  { key: "shelf_life", label: "保质期" },
  { key: "warnings", label: "注意事项" },
  { key: "manual_notes", label: "人工备注" }
];

const COVERAGE_FILTERS = [
  { value: "", label: "全部覆盖" },
  { value: "needs_attention", label: "待补充" },
  { value: "good", label: "覆盖较好" }
];

function statusTone(status?: string | null): "success" | "warning" | "danger" | "info" | "neutral" {
  if (!status) return "neutral";
  if (["active", "published", "synced", "indexed", "succeeded", "ready"].includes(status)) return "success";
  if (["draft", "pending", "pending_index", "running", "partial_failed", "not_indexed", "missing"].includes(status)) return "warning";
  if (["failed", "error", "archived", "index_failed"].includes(status)) return "danger";
  return "neutral";
}

function statusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    synced: "已同步",
    draft: "有草稿",
    published: "已发布",
    archived: "已归档",
    active: "已生效",
    indexed: "已索引",
    not_indexed: "未索引",
    unknown: "未知",
    failed: "失败",
    index_failed: "索引失败",
    missing: "未索引",
    good: "覆盖较好",
    needs_attention: "待补充",
    succeeded: "成功",
    running: "执行中",
    pending_index: "待索引"
  };
  if (!status) return "未知";
  return labels[status] ?? status;
}

function Badge({ status, children }: { status?: string | null; children?: string }) {
  return <span className={`status-badge status-${statusTone(status)}`}>{children ?? statusLabel(status)}</span>;
}

function formatDate(value?: string | null) {
  if (!value) return "无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) return value.join(" / ");
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function productKey(product: Pick<Product, "shop_id" | "goods_id">) {
  return `${product.shop_id}:${product.goods_id}`;
}

function getCoverageStatus(product: Product) {
  const filled = [
    product.price,
    Array.isArray(product.specs) && product.specs.length ? product.specs.join(" ") : "",
    product.usage,
    product.ingredients,
    product.shelf_life,
    product.warnings
  ].filter((item) => String(item || "").trim()).length;
  return filled >= 4 ? "good" : "needs_attention";
}

function shortText(value: unknown, fallback = "未覆盖") {
  const text = formatFieldValue(value);
  if (!text) return fallback;
  return text.length > 26 ? `${text.slice(0, 26)}...` : text;
}

function FieldSourceBadge({ field }: { field?: EffectiveField }) {
  if (!field) return <Badge status="missing" />;
  const labels: Record<string, string> = {
    raw: "PDD 原始",
    manual_override: "人工增强",
    missing: "待补充"
  };
  const status = field.source === "missing" ? "needs_attention" : "good";
  return <Badge status={status}>{labels[field.source] ?? field.source}</Badge>;
}

function CoverageMetrics({ coverage }: { coverage: ProductCoverage | null }) {
  const total = coverage?.total ?? 0;
  const metrics = [
    { label: "商品总数", value: total, caption: "当前筛选店铺" },
    { label: "价格覆盖", value: coverage?.has_price ?? 0, caption: total ? `${Math.round(((coverage?.has_price ?? 0) / total) * 100)}%` : "无数据" },
    { label: "规格覆盖", value: coverage?.has_specs ?? 0, caption: total ? `${Math.round(((coverage?.has_specs ?? 0) / total) * 100)}%` : "无数据" },
    { label: "待补字段", value: Math.max(0, total - (coverage?.has_usage ?? 0)), caption: "重点补用法/注意事项" }
  ];

  return (
    <div className="product-v2-metrics">
      {metrics.map((metric) => (
        <section className="product-v2-metric" key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
          <small>{metric.caption}</small>
        </section>
      ))}
    </div>
  );
}

function ProductCard({
  product,
  selected,
  onSelect
}: {
  product: Product;
  selected: boolean;
  onSelect: (product: Product) => void;
}) {
  const title = product.product_title || product.goods_name || product.goods_id;
  const coverageStatus = getCoverageStatus(product);

  return (
    <button
      type="button"
      className={selected ? "product-v2-card active" : "product-v2-card"}
      onClick={() => onSelect(product)}
    >
      <div className="product-v2-card-main">
        <strong>{title}</strong>
        <div className="product-v2-card-meta">
          <span>goods_id: {product.goods_id}</span>
          <span>shop: {product.shop_name || product.shop_id}</span>
          <span>updated: {formatDate(product.updated_at)}</span>
        </div>
        <div className="product-v2-card-badges">
          <Badge status={product.knowledge_status} />
          <Badge status={product.indexed_status || "unknown"} />
          <Badge status={coverageStatus} />
        </div>
      </div>
      <div className="product-v2-card-facts">
        <span><b>价格</b>{shortText(product.price)}</span>
        <span><b>规格</b>{Array.isArray(product.specs) && product.specs.length ? `${product.specs.length} 项` : "未覆盖"}</span>
        <span><b>用法</b>{product.usage ? "已覆盖" : "未覆盖"}</span>
        <span><b>注意事项</b>{product.warnings ? "已覆盖" : "未覆盖"}</span>
      </div>
    </button>
  );
}

function FieldGrid({ effective, detail }: { effective: EffectiveProduct | null; detail: ProductDetail | null }) {
  return (
    <div className="product-v2-field-grid">
      {FIELD_LABELS.map(({ key, label }) => {
        const field = effective?.fields?.[key];
        const fallback = detail ? (detail as unknown as Record<string, unknown>)[key] : "";
        const value = field ? formatFieldValue(field.value) : formatFieldValue(fallback);
        return (
          <article className="product-v2-info-card" key={key}>
            <header>
              <h4>{label}</h4>
              <FieldSourceBadge field={field} />
            </header>
            <p>{value || "未覆盖，建议补充后再发布索引。"}</p>
          </article>
        );
      })}
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: ProductChunk | VersionChunk }) {
  const versionId = "version_id" in chunk ? chunk.version_id : null;
  const hash = "chunk_hash" in chunk ? chunk.chunk_hash || chunk.content_hash : chunk.content_hash;

  return (
    <article className="product-v2-chunk">
      <header>
        <strong>{chunk.chunk_id}</strong>
        <Badge status="active">{chunk.domain}</Badge>
      </header>
      <dl className="product-v2-kv">
        <div><dt>source_type</dt><dd>{chunk.source_type}</dd></div>
        <div><dt>source_id</dt><dd>{chunk.source_id}</dd></div>
        <div><dt>version</dt><dd>{chunk.version || "无"}</dd></div>
        {versionId ? <div><dt>version_id</dt><dd>{versionId}</dd></div> : null}
        <div><dt>content_hash</dt><dd>{hash || "无"}</dd></div>
      </dl>
      <pre className="product-v2-code">{chunk.content}</pre>
      <details>
        <summary>metadata / 字段来源</summary>
        <pre>{JSON.stringify(chunk.metadata, null, 2)}</pre>
      </details>
    </article>
  );
}

function VersionRow({ version, onLoadChunks }: { version: KnowledgeVersion; onLoadChunks: (versionId: number) => void }) {
  return (
    <article className="product-v2-version-row">
      <div>
        <strong>{version.version}</strong>
        <dl className="product-v2-kv compact">
          <div><dt>version_id</dt><dd>{version.id}</dd></div>
          <div><dt>状态</dt><dd>{statusLabel(version.status)}</dd></div>
          <div><dt>是否生效</dt><dd>{version.is_active ? "是" : "否"}</dd></div>
          <div><dt>索引时间</dt><dd>{formatDate(version.indexed_at)}</dd></div>
          <div><dt>错误</dt><dd>{version.error_summary || "无"}</dd></div>
        </dl>
      </div>
      <div className="button-row">
        <Badge status={version.status} />
        <button type="button" className="compact-button" onClick={() => onLoadChunks(version.id)}>查看 chunk</button>
      </div>
    </article>
  );
}

export function Products() {
  const [shops, setShops] = useState<Shop[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [coverage, setCoverage] = useState<ProductCoverage | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [effective, setEffective] = useState<EffectiveProduct | null>(null);
  const [override, setOverride] = useState<ProductOverride | null>(null);
  const [versions, setVersions] = useState<KnowledgeVersion[]>([]);
  const [chunks, setChunks] = useState<Array<ProductChunk | VersionChunk>>([]);
  const [activeTab, setActiveTab] = useState<TabKey>("fields");
  const [shopId, setShopId] = useState("");
  const [query, setQuery] = useState("");
  const [knowledgeStatus, setKnowledgeStatus] = useState("");
  const [indexedStatus, setIndexedStatus] = useState("");
  const [coverageFilter, setCoverageFilter] = useState("");
  const [versionQuery, setVersionQuery] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [listState, setListState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [actionState, setActionState] = useState<LoadState>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getShops().then((data) => {
      setShops(data.items);
      if (!shopId && data.items.length === 1) {
        setShopId(data.items[0].shop_id);
      }
    }).catch(() => setShops([]));
  }, []);

  useEffect(() => {
    const params: ProductQuery = {
      shop_id: shopId || undefined,
      q: query.trim() || undefined,
      version: versionQuery || undefined,
      indexed_status: indexedStatus || undefined,
      include_archived: includeArchived,
      page_size: 100
    };
    setListState("loading");
    setError(null);
    getProducts(params)
      .then((data) => {
        setProducts(data.items);
        setListState("loaded");
        if (data.items.length && !detail) {
          void selectProduct(data.items[0]);
        }
      })
      .catch((err: Error) => {
        setProducts([]);
        setError(err.message);
        setListState("error");
      });
  }, [includeArchived, indexedStatus, query, shopId, versionQuery]);

  useEffect(() => {
    getProductCoverage(shopId || undefined)
      .then(setCoverage)
      .catch(() => setCoverage(null));
  }, [shopId]);

  const visibleProducts = useMemo(() => {
    return products.filter((product) => {
      const knowledgeMatch = !knowledgeStatus || product.knowledge_status === knowledgeStatus;
      const coverageMatch = !coverageFilter || getCoverageStatus(product) === coverageFilter;
      return knowledgeMatch && coverageMatch;
    });
  }, [coverageFilter, knowledgeStatus, products]);

  const knowledgeOptions = useMemo(() => {
    return Array.from(new Set(products.map((product) => product.knowledge_status).filter(Boolean)));
  }, [products]);

  async function selectProduct(product: Product) {
    setDetailState("loading");
    setMessage(null);
    setError(null);
    setActiveTab("fields");
    try {
      const [productDetail, productEffective, productOverride, productVersions, productChunks] = await Promise.all([
        getProduct(product.goods_id, product.shop_id, includeArchived),
        getEffectiveProduct(product.goods_id, product.shop_id).catch(() => null),
        getProductOverride(product.goods_id, product.shop_id).catch(() => null),
        listVersions({
          shop_id: product.shop_id,
          source_type: "product",
          source_id: product.goods_id,
          domain: "product_catalog"
        }).catch(() => ({ items: [], total: 0 })),
        getProductChunks(product.goods_id, {
          shop_id: product.shop_id,
          domain: "product_catalog",
          source_type: "product",
          limit: 20
        }).catch(() => ({ chunks: [] }))
      ]);
      setDetail(productDetail);
      setEffective(productEffective);
      setOverride(productOverride);
      setVersions(productVersions.items);
      setChunks(productChunks.chunks);
      setDetailState("loaded");
    } catch (err) {
      setDetail(null);
      setEffective(null);
      setOverride(null);
      setVersions([]);
      setChunks([]);
      setError(err instanceof Error ? err.message : "商品详情加载失败");
      setDetailState("error");
    }
  }

  function setOverrideField(field: keyof ProductOverridePayload, value: string) {
    if (!detail) return;
    setOverride((current) => ({
      id: current?.id,
      shop_id: detail.shop_id,
      goods_id: detail.goods_id,
      goods_name: current?.goods_name ?? detail.goods_name,
      usage_override: current?.usage_override ?? null,
      ingredients_override: current?.ingredients_override ?? null,
      warnings_override: current?.warnings_override ?? null,
      shelf_life_override: current?.shelf_life_override ?? null,
      manual_notes: current?.manual_notes ?? null,
      specs_override: current?.specs_override ?? null,
      price_note_override: current?.price_note_override ?? null,
      status: current?.status ?? "draft",
      content_hash: current?.content_hash ?? "",
      [field]: value
    }));
  }

  async function saveOverride() {
    if (!detail || !override) return;
    setActionState("loading");
    setMessage(null);
    setError(null);
    try {
      const saved = await saveProductOverride(detail.goods_id, detail.shop_id, {
        goods_name: override.goods_name || detail.goods_name,
        usage_override: override.usage_override || "",
        ingredients_override: override.ingredients_override || "",
        warnings_override: override.warnings_override || "",
        shelf_life_override: override.shelf_life_override || "",
        manual_notes: override.manual_notes || "",
        specs_override: override.specs_override || "",
        price_note_override: override.price_note_override || "",
        expected_content_hash: override.content_hash || undefined
      });
      setOverride(saved);
      setEffective(await getEffectiveProduct(detail.goods_id, detail.shop_id));
      setMessage("人工增强字段已保存为草稿。发布并索引成功后才会生效。");
      setActionState("loaded");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存人工增强字段失败");
      setActionState("error");
    }
  }

  async function publishSelectedProduct() {
    if (!detail) return;
    setActionState("loading");
    setMessage(null);
    setError(null);
    try {
      const result = await publishProduct(detail.goods_id, detail.shop_id);
      setEffective(result.effective);
      const productVersions = await listVersions({
        shop_id: detail.shop_id,
        source_type: "product",
        source_id: detail.goods_id,
        domain: "product_catalog"
      });
      setVersions(productVersions.items);
      const versionChunks = await getVersionChunks(result.version.id, 20).catch(() => ({ chunks: [] as VersionChunk[] }));
      setChunks(versionChunks.chunks);
      setMessage(`商品知识已发布并执行真实索引。版本状态：${result.version.status}。`);
      setActionState("loaded");
      setActiveTab("chunks");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发布商品知识失败");
      setActionState("error");
    }
  }

  async function clearOverride() {
    if (!detail) return;
    if (!window.confirm("确认清空该商品的人工增强字段吗？PDD 原始商品数据不会被删除。")) return;
    setActionState("loading");
    setMessage(null);
    setError(null);
    try {
      const cleared = await clearProductOverride(detail.goods_id, detail.shop_id);
      setOverride(cleared);
      setEffective(await getEffectiveProduct(detail.goods_id, detail.shop_id));
      setMessage("人工增强字段已清空。");
      setActionState("loaded");
    } catch (err) {
      setError(err instanceof Error ? err.message : "清空人工增强字段失败");
      setActionState("error");
    }
  }

  async function archiveSelectedProduct() {
    if (!detail) return;
    const reason = window.prompt("请输入归档原因。归档后该商品不会进入商品列表和 RAG 当前知识。", "manual_archive");
    if (!reason) return;
    setActionState("loading");
    setMessage(null);
    setError(null);
    try {
      await archiveProduct(detail.goods_id, detail.shop_id, reason);
      setMessage("商品知识已归档。");
      setActionState("loaded");
      setProducts((items) => items.filter((item) => productKey(item) !== productKey(detail)));
      setDetail(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "归档商品知识失败");
      setActionState("error");
    }
  }

  async function restoreSelectedProduct() {
    if (!detail) return;
    setActionState("loading");
    setMessage(null);
    setError(null);
    try {
      await restoreProduct(detail.goods_id, detail.shop_id);
      setMessage("商品知识已恢复，请重新发布并索引后再用于 AI。");
      setActionState("loaded");
      await selectProduct(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复商品知识失败");
      setActionState("error");
    }
  }

  async function loadVersionChunks(versionId: number) {
    setActionState("loading");
    setMessage(null);
    setError(null);
    try {
      const result = await getVersionChunks(versionId, 20);
      setChunks(result.chunks);
      setActiveTab("chunks");
      setMessage(`已加载版本 ${result.version} 的 ${result.chunks.length} 个 chunk。`);
      setActionState("loaded");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载版本 chunk 失败");
      setActionState("error");
    }
  }

  const selectedKey = detail ? productKey(detail) : "";
  const archived = Boolean(detail?.archived_at || effective?.archived_at || detail?.knowledge_status === "archived");

  return (
    <div className="page-stack product-page-v2">
      <section className="panel product-v2-intro">
        <div>
          <h2>商品知识</h2>
          <p className="muted">管理 PDD 商品同步数据、人工增强字段、发布版本和真实 RAG chunk。保存草稿不会生效，发布并索引成功后才成为 AI 当前知识。</p>
        </div>
        <div className="status-list">
          <Badge status="configured">真实索引已配置</Badge>
          <Badge status="no_send">不发送 PDD</Badge>
          <Badge status="active">PDD 原始字段只读</Badge>
        </div>
      </section>

      <section className="panel product-v2-toolbar">
        <div className="panel-header">
          <div>
            <h3>查询与筛选</h3>
            <p className="muted">先筛选商品，再点击商品查看字段覆盖、人工增强、当前版本和 chunk。</p>
          </div>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              setQuery("");
              setKnowledgeStatus("");
              setIndexedStatus("");
              setCoverageFilter("");
              setVersionQuery("");
              setIncludeArchived(false);
            }}
          >
            重置筛选
          </button>
        </div>
        <div className="product-v2-filter-grid">
          <label>
            <span>搜索</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="商品名 / goods_id / 关键词" />
          </label>
          <label>
            <span>店铺</span>
            <select value={shopId} onChange={(event) => setShopId(event.target.value)}>
              <option value="">全部店铺</option>
              {shops.map((shop) => <option key={shop.shop_id} value={shop.shop_id}>{shop.shop_name || shop.shop_id}</option>)}
            </select>
          </label>
          <label>
            <span>知识状态</span>
            <select value={knowledgeStatus} onChange={(event) => setKnowledgeStatus(event.target.value)}>
              <option value="">全部状态</option>
              {knowledgeOptions.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
            </select>
          </label>
          <label>
            <span>索引状态</span>
            <select value={indexedStatus} onChange={(event) => setIndexedStatus(event.target.value)}>
              <option value="">全部索引</option>
              <option value="indexed">已索引</option>
              <option value="not_indexed">未索引</option>
              <option value="failed">索引失败</option>
              <option value="unknown">未知</option>
            </select>
          </label>
          <label>
            <span>字段覆盖</span>
            <select value={coverageFilter} onChange={(event) => setCoverageFilter(event.target.value)}>
              {COVERAGE_FILTERS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label>
            <span>版本</span>
            <input value={versionQuery} onChange={(event) => setVersionQuery(event.target.value)} placeholder="version" />
          </label>
          <label className="checkbox-row product-v2-checkbox">
            <input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />
            显示归档商品
          </label>
        </div>
      </section>

      {message ? <div className="state-card">{message}</div> : null}
      {error ? <div className="state-card error-state">{error}</div> : null}

      <div className="product-v2-layout">
        <section className="panel product-v2-list-panel">
          <div className="panel-header">
            <div>
              <h3>商品列表</h3>
              <p className="muted">当前显示 {visibleProducts.length} 个商品，接口加载 {products.length} 个商品。</p>
            </div>
            <Badge status="active">{shopId ? `店铺 ${shopId}` : "全部店铺"}</Badge>
          </div>

          <CoverageMetrics coverage={coverage} />

          {listState === "loading" ? <div className="state-card">正在加载商品...</div> : null}
          {listState === "error" ? <div className="state-card error-state">商品列表加载失败。</div> : null}
          {listState !== "loading" && visibleProducts.length === 0 ? (
            <div className="state-card">没有匹配商品。请调整筛选条件，或回到店铺接入页重新同步商品。</div>
          ) : null}

          <div className="product-v2-list">
            {visibleProducts.map((product) => (
              <ProductCard
                key={productKey(product)}
                product={product}
                selected={selectedKey === productKey(product)}
                onSelect={selectProduct}
              />
            ))}
          </div>
        </section>

        <aside className="panel product-v2-detail">
          <div className="panel-header">
            <div>
              <h3>{detail ? detail.product_title || detail.goods_name || detail.goods_id : "请选择商品"}</h3>
              <p className="muted">
                {detail ? `shop_id ${detail.shop_id} · goods_id ${detail.goods_id} · 当前版本 ${detail.version || "无"}` : "从左侧列表选择一个商品后查看详情。"}
              </p>
            </div>
            {detail ? <Badge status={detail.knowledge_status} /> : null}
          </div>

          {detailState === "loading" ? <div className="state-card">正在加载商品详情...</div> : null}
          {detailState === "error" ? <div className="state-card error-state">商品详情加载失败。</div> : null}
          {!detail && detailState !== "loading" ? <div className="state-card">请选择商品后编辑人工知识。</div> : null}

          {detail ? (
            <>
              <div className="product-v2-actions">
                <button type="button" onClick={() => setActiveTab("editor")}>编辑人工字段</button>
                <button type="button" className="secondary-button" disabled={actionState === "loading"} onClick={saveOverride}>保存草稿</button>
                <button type="button" disabled={actionState === "loading" || archived} onClick={publishSelectedProduct}>发布并真实索引</button>
                <button type="button" className="secondary-button" disabled={actionState === "loading"} onClick={() => selectProduct(detail)}>刷新详情</button>
                {archived ? (
                  <button type="button" disabled={actionState === "loading"} onClick={restoreSelectedProduct}>恢复商品知识</button>
                ) : (
                  <button type="button" className="danger-button" disabled={actionState === "loading"} onClick={archiveSelectedProduct}>归档商品知识</button>
                )}
              </div>

              <div className="tab-row product-v2-tabs">
                {[
                  ["fields", "字段覆盖"],
                  ["editor", "人工增强"],
                  ["chunks", "当前 chunk"],
                  ["versions", "版本记录"],
                  ["raw", "原始 JSON"]
                ].map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={activeTab === key ? "tab-button active" : "tab-button"}
                    onClick={() => setActiveTab(key as TabKey)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {activeTab === "fields" ? <FieldGrid effective={effective} detail={detail} /> : null}

              {activeTab === "editor" ? (
                <section className="product-v2-editor">
                  <div className="warning-banner">人工增强字段只覆盖 AI 知识，不修改 PDD 商品原始数据。发布并索引成功后才生效。</div>
                  <div className="product-v2-editor-grid">
                    <label>
                      <span>商品别名 / 展示名</span>
                      <input value={override?.goods_name ?? detail.goods_name ?? ""} onChange={(event) => setOverrideField("goods_name", event.target.value)} />
                    </label>
                    <label>
                      <span>价格说明</span>
                      <input value={override?.price_note_override ?? ""} onChange={(event) => setOverrideField("price_note_override", event.target.value)} placeholder="例如：价格随规格变化，实际以商品页和结算页为准。" />
                    </label>
                    <label>
                      <span>规格补充</span>
                      <textarea value={override?.specs_override ?? ""} onChange={(event) => setOverrideField("specs_override", event.target.value)} />
                    </label>
                    <label>
                      <span>使用方法</span>
                      <textarea value={override?.usage_override ?? ""} onChange={(event) => setOverrideField("usage_override", event.target.value)} />
                    </label>
                    <label>
                      <span>成分 / 卖点</span>
                      <textarea value={override?.ingredients_override ?? ""} onChange={(event) => setOverrideField("ingredients_override", event.target.value)} />
                    </label>
                    <label>
                      <span>保质期</span>
                      <textarea value={override?.shelf_life_override ?? ""} onChange={(event) => setOverrideField("shelf_life_override", event.target.value)} />
                    </label>
                    <label>
                      <span>注意事项 / 售后口径</span>
                      <textarea value={override?.warnings_override ?? ""} onChange={(event) => setOverrideField("warnings_override", event.target.value)} />
                    </label>
                    <label>
                      <span>人工备注</span>
                      <textarea value={override?.manual_notes ?? ""} onChange={(event) => setOverrideField("manual_notes", event.target.value)} />
                    </label>
                  </div>
                  <div className="button-row">
                    <button type="button" disabled={actionState === "loading"} onClick={saveOverride}>保存草稿</button>
                    <button type="button" className="secondary-button" disabled={actionState === "loading"} onClick={clearOverride}>清空人工字段</button>
                  </div>
                </section>
              ) : null}

              {activeTab === "chunks" ? (
                <section className="product-v2-tab-panel">
                  {chunks.length === 0 ? <div className="state-card">当前商品没有生效 chunk。请发布商品知识并执行真实索引，或查看索引失败原因。</div> : null}
                  <div className="product-v2-chunk-list">
                    {chunks.map((chunk, index) => <ChunkCard key={`${chunk.chunk_id}-${index}`} chunk={chunk} />)}
                  </div>
                </section>
              ) : null}

              {activeTab === "versions" ? (
                <section className="product-v2-tab-panel">
                  {versions.length === 0 ? <div className="state-card">暂无发布版本。保存草稿后发布并索引，才会产生版本记录。</div> : null}
                  <div className="product-v2-version-list">
                    {versions.map((version) => <VersionRow key={version.id} version={version} onLoadChunks={loadVersionChunks} />)}
                  </div>
                </section>
              ) : null}

              {activeTab === "raw" ? (
                <section className="product-v2-tab-panel">
                  <pre>{JSON.stringify({
                    detail,
                    effective,
                    override,
                    versions
                  }, null, 2)}</pre>
                </section>
              ) : null}
            </>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
