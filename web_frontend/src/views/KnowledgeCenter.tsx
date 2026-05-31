import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getShops, Shop } from "../api/shops";
import {
  archiveSop,
  createSop,
  getVersion,
  getVersionChunks,
  IndexJobQuery,
  KnowledgeIndexJob,
  KnowledgeVersion,
  listIndexJobs,
  listSop,
  listVersions,
  publishSop,
  retryIndexJob,
  runIndexJob,
  SopCreatePayload,
  SopRecord,
  SopUpdatePayload,
  updateSop,
  VersionChunk,
  VersionQuery
} from "../api/knowledgeCenter";
import { DataTable } from "../components/DataTable";
import { DrawerPanel } from "../components/DrawerPanel";
import { StatusBadge } from "../components/StatusBadge";

type TabKey = "sop" | "versions" | "jobs";
type LoadState = "idle" | "loading" | "loaded" | "error";

const DOMAINS = [
  "product_catalog",
  "logistics_policy",
  "after_sales_evidence",
  "promotion_policy",
  "sensitive_user_safety",
  "redline_escalation"
];

const emptySopForm: SopCreatePayload & { id?: number; expected_content_hash?: string } = {
  shop_id: "",
  domain: "logistics_policy",
  title: "",
  content: ""
};

function statusTone(status: string | boolean | number | null | undefined) {
  const value = String(status ?? "");
  if (["active", "succeeded", "draft"].includes(value)) return "success";
  if (["pending", "pending_index", "retrying", "indexing", "running"].includes(value)) return "warning";
  if (["failed", "archived"].includes(value)) return "danger";
  return "neutral";
}

function formatJson(value: unknown) {
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}

function FieldValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) return <span>{value.join(" / ") || "空"}</span>;
  if (value === null || value === undefined || value === "") return <span className="muted">空</span>;
  if (typeof value === "object") return <pre>{formatJson(value)}</pre>;
  return <span>{String(value)}</span>;
}

function validationLinks(version: KnowledgeVersion | null) {
  if (!version) {
    return {
      rag: "/products",
      liveChat: "/live-chat"
    };
  }
  const params = new URLSearchParams({
    shop_id: version.shop_id,
    source_type: version.source_type,
    source_id: version.source_id,
    domain: version.domain,
    version_id: String(version.id),
    version: version.version
  });
  if (version.source_type === "product") {
    params.set("goods_id", version.source_id);
  }
  return {
    rag: `/products?${params.toString()}`,
    liveChat: `/live-chat?${params.toString()}&smoke_profile=real_full`
  };
}

function ChunkPreview({ chunks, warning }: { chunks: VersionChunk[]; warning?: string | null }) {
  if (warning) {
    return <div className="state-card warning-state">{warning}</div>;
  }
  if (!chunks.length) {
    return <div className="state-card">暂无当前生效版本的知识片段。</div>;
  }
  return (
    <div className="chunk-preview-list">
      {chunks.slice(0, 5).map((chunk) => (
        <article className="chunk-preview-card" key={chunk.chunk_id}>
          <div className="debug-card-header">
            <strong>{chunk.chunk_id}</strong>
            <StatusBadge tone="info">{chunk.source_type}</StatusBadge>
          </div>
          <dl className="kv-grid">
            <div><dt>version_id</dt><dd>{chunk.version_id ?? "unknown"}</dd></div>
            <div><dt>source_id</dt><dd>{chunk.source_id}</dd></div>
            <div><dt>domain</dt><dd>{chunk.domain}</dd></div>
            <div><dt>index_run_id</dt><dd>{chunk.index_run_id || "无"}</dd></div>
            <div><dt>chunk_hash</dt><dd>{chunk.chunk_hash || chunk.content_hash}</dd></div>
          </dl>
          <pre className="chunk-preview-content">{chunk.content}</pre>
        </article>
      ))}
    </div>
  );
}

function ActiveVersionSummary({
  version,
  job,
  chunks,
  warning,
  title = "当前生效版本"
}: {
  version: KnowledgeVersion | null;
  job: KnowledgeIndexJob | null;
  chunks: VersionChunk[];
  warning?: string | null;
  title?: string;
}) {
  return (
    <section className="active-version-card">
      <div className="debug-card-header">
        <strong>{title}</strong>
        <StatusBadge tone={version ? "success" : "warning"}>{version ? "当前生效 active" : "缺失 missing"}</StatusBadge>
      </div>
      {version ? (
        <>
          <dl className="kv-grid">
            <div><dt>version_id</dt><dd>{version.id}</dd></div>
            <div><dt>version</dt><dd>{version.version}</dd></div>
            <div><dt>content_hash</dt><dd>{version.content_hash}</dd></div>
            <div><dt>indexed_at</dt><dd>{version.indexed_at ?? "未索引"}</dd></div>
            <div><dt>activated_at</dt><dd>{version.activated_at ?? "未生效"}</dd></div>
            <div><dt>latest_job</dt><dd>{job ? `${job.id} / ${job.status}` : "无"}</dd></div>
            <div><dt>生效片段数</dt><dd>{chunks.length}</dd></div>
          </dl>
          <details>
            <summary>当前生效 chunk 预览</summary>
            <ChunkPreview chunks={chunks} warning={warning} />
          </details>
        </>
      ) : (
        <p className="muted">草稿修改不会立即生效，必须发布并索引成功后才会成为 AI 当前使用的知识。</p>
      )}
    </section>
  );
}

function ValidationPanel({ version, job }: { version: KnowledgeVersion | null; job: KnowledgeIndexJob | null }) {
  const links = validationLinks(version);
  return (
    <section className="panel validation-panel">
      <h3>验证入口</h3>
      <p className="muted">发布会生成版本快照；只有索引任务成功后，该版本才会成为当前生效知识。</p>
      <div className="warning-banner">
        真实索引只写入绑定版本的 chunks，不会发送 PDD。上线前请先用 no-send 试聊验证。
      </div>
      <div className="button-row">
        <button type="button" disabled={!version}>查看版本快照</button>
        <Link className="button-link" to={links.rag}>打开 RAG 调试</Link>
        <Link className="button-link" to={links.liveChat}>打开试聊验证</Link>
      </div>
      {version ? (
        <dl className="kv-grid">
          <div><dt>shop_id</dt><dd>{version.shop_id}</dd></div>
          <div><dt>来源</dt><dd>{version.source_type}:{version.source_id}</dd></div>
          <div><dt>domain</dt><dd>{version.domain}</dd></div>
          <div><dt>version_id</dt><dd>{version.id}</dd></div>
          <div><dt>version</dt><dd>{version.version}</dd></div>
          <div><dt>状态</dt><dd><StatusBadge tone={statusTone(version.status)}>{version.status}</StatusBadge></dd></div>
          <div><dt>是否生效</dt><dd><StatusBadge tone={version.is_active ? "success" : "neutral"}>{version.is_active}</StatusBadge></dd></div>
          <div><dt>content_hash</dt><dd>{version.content_hash}</dd></div>
        </dl>
      ) : null}
      {job ? (
        <dl className="kv-grid">
          <div><dt>索引任务</dt><dd>{job.id}</dd></div>
          <div><dt>任务状态</dt><dd><StatusBadge tone={statusTone(job.status)}>{job.status}</StatusBadge></dd></div>
          <div><dt>片段/向量/写入</dt><dd>{job.chunk_count} / {job.embedded_count} / {job.indexed_count}</dd></div>
        </dl>
      ) : null}
      {version ? (
        <details>
          <summary>版本快照 Snapshot JSON</summary>
          <pre>{formatJson(version.snapshot_json)}</pre>
        </details>
      ) : null}
    </section>
  );
}

function SopTab({
  shops,
  onPublished
}: {
  shops: Shop[];
  onPublished: (version: KnowledgeVersion, job: KnowledgeIndexJob) => void;
}) {
  const [records, setRecords] = useState<SopRecord[]>([]);
  const [selected, setSelected] = useState<SopRecord | null>(null);
  const [form, setForm] = useState(emptySopForm);
  const [filters, setFilters] = useState({ shop_id: "", domain: "", status: "" });
  const [state, setState] = useState<LoadState>("idle");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [lastJob, setLastJob] = useState<KnowledgeIndexJob | null>(null);
  const [activeVersion, setActiveVersion] = useState<KnowledgeVersion | null>(null);
  const [activeJob, setActiveJob] = useState<KnowledgeIndexJob | null>(null);
  const [activeChunks, setActiveChunks] = useState<VersionChunk[]>([]);
  const [activeChunkWarning, setActiveChunkWarning] = useState<string | null>(null);

  function load() {
    setState("loading");
    setError("");
    listSop(filters)
      .then((data) => {
        setRecords(data.items);
        setState("loaded");
      })
      .catch((err: Error) => {
        setError(err.message);
        setState("error");
      });
  }

  useEffect(() => {
    load();
  }, [filters.shop_id, filters.domain, filters.status]);

  function edit(row: SopRecord) {
    setSelected(row);
    setForm({
      id: row.id,
      shop_id: row.shop_id,
      domain: row.domain,
      title: row.title,
      content: row.content,
      expected_content_hash: row.content_hash
    });
    setMessage("");
    loadActiveSummary(row);
  }

  function loadActiveSummary(row: SopRecord) {
    listVersions({
      shop_id: row.shop_id,
      source_type: "sop",
      source_id: String(row.id),
      domain: row.domain,
      is_active: true
    })
      .then((data) => {
        const active = data.items[0] ?? null;
        setActiveVersion(active);
        setActiveChunks([]);
        setActiveChunkWarning(null);
        if (active?.index_job_id) {
          listIndexJobs({ version_id: active.id }).then((jobs) => setActiveJob(jobs.items[0] ?? null));
          getVersionChunks(active.id).then((chunks) => {
            setActiveChunks(chunks.chunks);
            setActiveChunkWarning(chunks.warning);
          });
        } else {
          setActiveJob(null);
        }
      })
      .catch(() => {
        setActiveVersion(null);
        setActiveJob(null);
        setActiveChunks([]);
        setActiveChunkWarning("active_version_lookup_failed");
      });
  }

  function newSop() {
    setSelected(null);
    setForm({
      ...emptySopForm,
      shop_id: shops[0]?.shop_id ?? filters.shop_id
    });
    setMessage("");
    setActiveVersion(null);
    setActiveJob(null);
    setActiveChunks([]);
    setActiveChunkWarning(null);
  }

  function saveDraft() {
    setError("");
    const action = form.id
      ? updateSop(form.id, {
          title: form.title,
          content: form.content,
          expected_content_hash: form.expected_content_hash
        } satisfies SopUpdatePayload)
      : createSop({
          shop_id: form.shop_id,
          domain: form.domain,
          title: form.title,
          content: form.content
        });
    action
      .then((saved) => {
        setMessage("草稿已保存。");
        edit(saved);
        load();
      })
      .catch((err: Error) => setError(err.message));
  }

  function archiveCurrent() {
    if (!form.id) return;
    archiveSop(form.id)
      .then((archived) => {
        setMessage("SOP 已归档。");
        edit(archived);
        load();
      })
      .catch((err: Error) => setError(err.message));
  }

  function publishCurrent() {
    if (!form.id) return;
    publishSop(form.id)
      .then((result) => {
        setMessage(`SOP 已发布并执行真实索引。当前版本状态：${result.version.status}。`);
        setLastJob(result.index_job);
        onPublished(result.version, result.index_job);
        load();
      })
      .catch((err: Error) => setError(err.message));
  }

  function runLastJob() {
    if (!lastJob) return;
    if (!window.confirm("真实索引会调用 embedding 服务并写入 pgvector，但不会发送 PDD 消息。确认继续执行真实索引吗？")) {
      return;
    }
    runIndexJob(lastJob.id, { mode: "real", embedding_provider: "doubao", vector_store: "pgvector" })
      .then((result) => {
        setMessage(`真实索引已完成，当前版本状态：${result.version.status}。`);
        setLastJob(result.index_job);
        onPublished(result.version, result.index_job);
        getVersionChunks(result.version.id).then((chunks) => {
          setActiveVersion(result.version);
          setActiveJob(result.index_job);
          setActiveChunks(chunks.chunks);
          setActiveChunkWarning(chunks.warning);
        });
      })
      .catch((err: Error) => setError(err.message));
  }

  return (
    <div className="knowledge-grid">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>SOP 草稿</h2>
            <p className="muted">用于维护客服 SOP。发布只生成版本快照，不代表立即生效；索引成功后才会成为 AI 当前使用的知识。</p>
          </div>
          <button type="button" onClick={newSop}>新建 SOP</button>
        </div>
        <div className="filters knowledge-filter-grid">
          <select value={filters.shop_id} onChange={(event) => setFilters({ ...filters, shop_id: event.target.value })}>
            <option value="">全部店铺</option>
            {shops.map((shop) => <option key={shop.shop_id} value={shop.shop_id}>{shop.shop_name || shop.shop_id}</option>)}
          </select>
          <select value={filters.domain} onChange={(event) => setFilters({ ...filters, domain: event.target.value })}>
            <option value="">全部领域</option>
            {DOMAINS.map((domain) => <option key={domain} value={domain}>{domain}</option>)}
          </select>
          <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
            <option value="">全部状态</option>
            <option value="draft">draft</option>
            <option value="archived">archived</option>
          </select>
        </div>
        {state === "loading" ? <div className="state-card">正在加载 SOP...</div> : null}
        {state === "error" ? <div className="state-card error-state">{error}</div> : null}
        <DataTable<SopRecord>
          rows={records}
          emptyMessage="暂无 SOP 草稿。"
          onRowClick={edit}
          columns={[
            { key: "id", label: "id" },
            { key: "shop_id", label: "shop_id" },
            { key: "domain", label: "domain" },
            { key: "title", label: "标题" },
            { key: "status", label: "状态", render: (row) => <StatusBadge tone={statusTone(row.status)}>{row.status}</StatusBadge> },
            { key: "content_hash", label: "content_hash" },
            { key: "updated_at", label: "updated_at" }
          ]}
        />
      </section>

      <DrawerPanel title="SOP 编辑器">
        <div className="detail-stack">
          {message ? <div className="state-card">{message}</div> : null}
          {error ? <div className="state-card error-state">{error}</div> : null}
          <label>shop_id<select value={form.shop_id} onChange={(event) => setForm({ ...form, shop_id: event.target.value })}>
            <option value="">选择店铺</option>
            {shops.map((shop) => <option key={shop.shop_id} value={shop.shop_id}>{shop.shop_name || shop.shop_id}</option>)}
          </select></label>
          <label>domain<select value={form.domain} onChange={(event) => setForm({ ...form, domain: event.target.value })}>
            {DOMAINS.map((domain) => <option key={domain} value={domain}>{domain}</option>)}
          </select></label>
          <label>标题<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
          <label>内容<textarea rows={14} value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} /></label>
          {selected ? <span className="muted">当前 content_hash: {selected.content_hash}</span> : null}
          <div className="warning-banner">发布只会生成版本和索引任务，不代表立即生效。索引成功后才会成为 AI 当前使用的知识。</div>
          <div className="button-row">
            <button type="button" onClick={saveDraft} disabled={!form.shop_id || !form.title || !form.content}>保存草稿</button>
            <button type="button" onClick={publishCurrent} disabled={!form.id}>发布并真实索引</button>
            <button type="button" onClick={runLastJob} disabled={!lastJob || !["pending", "retrying", "failed"].includes(lastJob.status)}>重新执行真实索引</button>
            <button type="button" onClick={archiveCurrent} disabled={!form.id}>归档</button>
          </div>
          <ActiveVersionSummary
            version={activeVersion}
            job={activeJob}
            chunks={activeChunks}
            warning={activeChunkWarning}
            title="当前生效 SOP 版本"
          />
        </div>
      </DrawerPanel>
    </div>
  );
}

function VersionsTab({
  onSelectVersion
}: {
  onSelectVersion: (version: KnowledgeVersion) => void;
}) {
  const [filters, setFilters] = useState<VersionQuery>({});
  const [versions, setVersions] = useState<KnowledgeVersion[]>([]);
  const [selected, setSelected] = useState<KnowledgeVersion | null>(null);
  const [chunks, setChunks] = useState<VersionChunk[]>([]);
  const [chunkWarning, setChunkWarning] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState("");

  function load() {
    setState("loading");
    listVersions(filters)
      .then((data) => {
        setVersions(data.items);
        setState("loaded");
      })
      .catch((err: Error) => {
        setError(err.message);
        setState("error");
      });
  }

  useEffect(() => {
    load();
  }, [filters.shop_id, filters.source_type, filters.source_id, filters.domain, filters.status, filters.is_active]);

  function selectVersion(row: KnowledgeVersion) {
    getVersion(row.id)
      .then((version) => {
        setSelected(version);
        onSelectVersion(version);
        getVersionChunks(version.id).then((chunkResult) => {
          setChunks(chunkResult.chunks);
          setChunkWarning(chunkResult.warning);
        });
      })
      .catch((err: Error) => setError(err.message));
  }

  return (
    <div className="content-grid detail-layout">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>知识版本</h2>
            <p className="muted">当前生效版本是索引成功后的不可变快照，可在这里查看 snapshot_json 和 active 状态。</p>
          </div>
          <button type="button" onClick={load}>刷新</button>
        </div>
        <div className="filters knowledge-filter-grid">
          <input placeholder="shop_id" value={filters.shop_id ?? ""} onChange={(event) => setFilters({ ...filters, shop_id: event.target.value })} />
          <select value={filters.source_type ?? ""} onChange={(event) => setFilters({ ...filters, source_type: event.target.value })}>
            <option value="">全部 source_type</option>
            <option value="sop">sop</option>
            <option value="product">product</option>
          </select>
          <input placeholder="source_id" value={filters.source_id ?? ""} onChange={(event) => setFilters({ ...filters, source_id: event.target.value })} />
          <select value={filters.domain ?? ""} onChange={(event) => setFilters({ ...filters, domain: event.target.value })}>
            <option value="">全部领域</option>
            {DOMAINS.map((domain) => <option key={domain} value={domain}>{domain}</option>)}
          </select>
          <select value={filters.status ?? ""} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
            <option value="">全部状态</option>
            <option value="pending_index">pending_index</option>
            <option value="succeeded">succeeded</option>
            <option value="active">active</option>
            <option value="failed">failed</option>
            <option value="retired">retired</option>
          </select>
          <select value={String(filters.is_active ?? "")} onChange={(event) => setFilters({ ...filters, is_active: event.target.value })}>
            <option value="">全部生效状态</option>
            <option value="true">仅当前生效</option>
            <option value="false">仅未生效</option>
          </select>
        </div>
        {state === "loading" ? <div className="state-card">正在加载版本...</div> : null}
        {state === "error" ? <div className="state-card error-state">{error}</div> : null}
        <DataTable<KnowledgeVersion>
          rows={versions}
          emptyMessage="暂无版本。"
          onRowClick={selectVersion}
          columns={[
            { key: "id", label: "id" },
            { key: "shop_id", label: "shop_id" },
            { key: "source_type", label: "source_type" },
            { key: "source_id", label: "source_id" },
            { key: "domain", label: "domain" },
            { key: "version", label: "version" },
            { key: "content_hash", label: "content_hash" },
            { key: "status", label: "状态", render: (row) => <StatusBadge tone={statusTone(row.status)}>{row.status}</StatusBadge> },
            { key: "is_active", label: "当前生效", render: (row) => <StatusBadge tone={row.is_active ? "success" : "neutral"}>{row.is_active}</StatusBadge> },
            { key: "created_at", label: "created_at" }
          ]}
        />
      </section>
      <DrawerPanel title="版本快照">
        {selected ? (
          <div className="detail-stack">
            <strong>{selected.version}</strong>
            <span>index_job_id: {selected.index_job_id ?? "无"}</span>
            <span>indexed_at: {selected.indexed_at ?? "未索引"}</span>
            <span>activated_at: {selected.activated_at ?? "未生效"}</span>
            <span>error_summary: {selected.error_summary ?? "无"}</span>
            <details open={Boolean(selected.is_active)}>
              <summary>版本 chunks</summary>
              <ChunkPreview chunks={chunks} warning={chunkWarning} />
            </details>
            <pre>{formatJson(selected.snapshot_json)}</pre>
          </div>
        ) : <div className="state-card">请选择版本查看 snapshot_json。</div>}
      </DrawerPanel>
    </div>
  );
}

function IndexJobsTab({
  onSelectVersion,
  onSelectJob
}: {
  onSelectVersion: (version: KnowledgeVersion) => void;
  onSelectJob: (job: KnowledgeIndexJob) => void;
}) {
  const [filters, setFilters] = useState<IndexJobQuery>({});
  const [jobs, setJobs] = useState<KnowledgeIndexJob[]>([]);
  const [selected, setSelected] = useState<KnowledgeIndexJob | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  function load() {
    setState("loading");
    listIndexJobs(filters)
      .then((data) => {
        setJobs(data.items);
        setState("loaded");
      })
      .catch((err: Error) => {
        setError(err.message);
        setState("error");
      });
  }

  useEffect(() => {
    load();
  }, [filters.shop_id, filters.status, filters.source_type, filters.source_id, filters.version_id]);

  function runJob(job: KnowledgeIndexJob) {
    runIndexJob(job.id, { mode: "real", embedding_provider: "doubao", vector_store: "pgvector" })
      .then((result) => {
        setMessage(`任务 ${result.index_job.id} 已成功，版本 ${result.version.id} 已生效。`);
        setSelected(result.index_job);
        onSelectJob(result.index_job);
        onSelectVersion(result.version);
        load();
      })
      .catch((err: Error) => setError(err.message));
  }

  function retryJob(job: KnowledgeIndexJob) {
    retryIndexJob(job.id)
      .then((nextJob) => {
        setMessage(`任务 ${nextJob.id} 已进入 ${nextJob.status} 状态。`);
        setSelected(nextJob);
        onSelectJob(nextJob);
        load();
      })
      .catch((err: Error) => setError(err.message));
  }

  return (
    <div className="content-grid detail-layout">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>索引任务</h2>
            <p className="muted">查看和执行索引任务。生产环境统一执行真实索引，写入已配置的 pgvector；该过程不会发送 PDD 消息。</p>
          </div>
          <button type="button" onClick={load}>刷新</button>
        </div>
        <div className="filters knowledge-filter-grid">
          <input placeholder="shop_id" value={filters.shop_id ?? ""} onChange={(event) => setFilters({ ...filters, shop_id: event.target.value })} />
          <select value={filters.status ?? ""} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
            <option value="">全部状态</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
            <option value="succeeded">succeeded</option>
            <option value="failed">failed</option>
            <option value="retrying">retrying</option>
          </select>
          <select value={filters.source_type ?? ""} onChange={(event) => setFilters({ ...filters, source_type: event.target.value })}>
            <option value="">全部 source_type</option>
            <option value="sop">sop</option>
            <option value="product">product</option>
          </select>
          <input placeholder="source_id" value={filters.source_id ?? ""} onChange={(event) => setFilters({ ...filters, source_id: event.target.value })} />
          <input placeholder="version_id" value={filters.version_id ?? ""} onChange={(event) => setFilters({ ...filters, version_id: event.target.value })} />
        </div>
        {message ? <div className="state-card">{message}</div> : null}
        {state === "loading" ? <div className="state-card">正在加载索引任务...</div> : null}
        {state === "error" ? <div className="state-card error-state">{error}</div> : null}
        <DataTable<KnowledgeIndexJob>
          rows={jobs}
          emptyMessage="暂无索引任务。"
          onRowClick={(row) => {
            setSelected(row);
            onSelectJob(row);
          }}
          columns={[
            { key: "id", label: "id" },
            { key: "shop_id", label: "shop_id" },
            { key: "version_id", label: "version_id" },
            { key: "source_type", label: "source_type" },
            { key: "source_id", label: "source_id" },
            { key: "domain", label: "domain" },
            { key: "status", label: "状态", render: (row) => <StatusBadge tone={statusTone(row.status)}>{row.status}</StatusBadge> },
            { key: "chunk_count", label: "片段数" },
            { key: "embedded_count", label: "向量数" },
            { key: "indexed_count", label: "写入数" },
            { key: "retry_count", label: "retry_count" },
            { key: "finished_at", label: "finished_at" },
            {
              key: "actions",
              label: "操作",
              render: (row) => (
                <div className="inline-actions">
                  <button type="button" disabled={!["pending", "retrying"].includes(row.status)} onClick={(event) => { event.stopPropagation(); runJob(row); }}>执行</button>
                  <button type="button" disabled={row.status !== "failed"} onClick={(event) => { event.stopPropagation(); retryJob(row); }}>重试</button>
                </div>
              )
            }
          ]}
        />
      </section>
      <DrawerPanel title="索引任务详情">
        {selected ? (
          <div className="detail-stack">
            <strong>任务 {selected.id}</strong>
            <span>version_id: {selected.version_id}</span>
            <span>index_run_id: {selected.index_run_id}</span>
            <span>status: {selected.status}</span>
            <span>error_summary: {selected.error_summary ?? "无"}</span>
            <span>started_at: {selected.started_at ?? "未开始"}</span>
            <span>finished_at: {selected.finished_at ?? "未完成"}</span>
            <button type="button" onClick={() => getVersion(selected.version_id).then(onSelectVersion)}>查看版本快照</button>
          </div>
        ) : <div className="state-card">请选择索引任务查看详情。</div>}
      </DrawerPanel>
    </div>
  );
}

export function KnowledgeCenter() {
  const [activeTab, setActiveTab] = useState<TabKey>("sop");
  const [shops, setShops] = useState<Shop[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<KnowledgeVersion | null>(null);
  const [selectedJob, setSelectedJob] = useState<KnowledgeIndexJob | null>(null);

  useEffect(() => {
    getShops()
      .then((data) => setShops(data.items))
      .catch(() => setShops([]));
  }, []);

  const tabs: Array<{ key: TabKey; label: string }> = useMemo(() => [
    { key: "sop", label: "SOP" },
    { key: "versions", label: "版本" },
    { key: "jobs", label: "索引任务" }
  ], []);

  function setPublished(version: KnowledgeVersion, job: KnowledgeIndexJob) {
    setSelectedVersion(version);
    setSelectedJob(job);
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>知识库管理</h2>
            <p className="muted">用于维护 SOP 草稿、版本快照和索引任务，通过“草稿、发布、索引成功、当前生效”的闭环控制 AI 使用的知识版本。商品字段维护统一在“商品知识”页完成。</p>
          </div>
          <div className="header-badges">
            <StatusBadge tone="info">仅 InternalEngine</StatusBadge>
            <StatusBadge tone="warning">不发送 PDD</StatusBadge>
            <StatusBadge tone="neutral">按版本索引</StatusBadge>
          </div>
        </div>
        <div className="warning-banner">
          保存草稿不会立即生效；发布会生成版本快照并执行真实索引；只有索引成功后才会成为 AI 当前使用的知识。真实索引会写入 pgvector，不会发送 PDD 消息。
        </div>
        <div className="tab-row">
          {tabs.map((tab) => (
            <button
              type="button"
              key={tab.key}
              className={activeTab === tab.key ? "tab-button active" : "tab-button"}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      {activeTab === "sop" ? <SopTab shops={shops} onPublished={setPublished} /> : null}
      {activeTab === "versions" ? <VersionsTab onSelectVersion={setSelectedVersion} /> : null}
      {activeTab === "jobs" ? <IndexJobsTab onSelectVersion={setSelectedVersion} onSelectJob={setSelectedJob} /> : null}

      <ValidationPanel version={selectedVersion} job={selectedJob} />
    </div>
  );
}
