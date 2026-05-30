import { useCallback, useEffect, useMemo, useState } from "react";

import { getTrace, getTraces, TraceSummary } from "../api/traces";
import { StatusBadge } from "../components/StatusBadge";
import { TracePanel } from "../components/TracePanel";

function traceStatusTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (!status) return "neutral";
  if (["ok", "success", "safe", "reply"].includes(status)) return "success";
  if (["failed", "error", "blocked"].includes(status)) return "danger";
  if (["fallback", "warning", "partial_failed"].includes(status)) return "warning";
  return "neutral";
}

function formatTraceTime(value: string) {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function isErrorTrace(trace: TraceSummary) {
  const status = String(trace.final_status ?? "").toLowerCase();
  return Boolean(status && !["ok", "success", "safe", "reply"].includes(status));
}

export function TraceLogs() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [query, setQuery] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const loadTraces = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const data = await getTraces();
      setTraces(data.items);
      setLastUpdatedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
      if (!detail && data.items[0]) {
        const first = await getTrace(data.items[0].trace_id);
        setDetail(first);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "链路日志加载失败");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [detail]);

  useEffect(() => {
    void loadTraces(true);
  }, [loadTraces]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => void loadTraces(false), 3000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, loadTraces]);

  const filteredTraces = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return traces.filter((trace) => {
      if (onlyErrors && !isErrorTrace(trace)) return false;
      if (!keyword) return true;
      return [
        trace.trace_id,
        trace.shop_id,
        trace.buyer_id,
        trace.session_id,
        trace.intent,
        trace.domain,
        trace.action,
        trace.final_status
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    });
  }, [onlyErrors, query, traces]);

  async function selectTrace(traceId: string) {
    setDetailLoading(true);
    setError(null);
    try {
      setDetail(await getTrace(traceId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Trace 详情加载失败");
    } finally {
      setDetailLoading(false);
    }
  }

  const selectedTraceId = typeof detail?.trace_id === "string" ? detail.trace_id : "";

  return (
    <div className="trace-log-layout">
      <section className="panel trace-log-list-panel">
        <div className="page-intro">
          <h2>调试日志</h2>
          <p>
            实时查看 InternalEngine no-send 链路状态，包括 LLM 调用证据、Embedding、pgvector RAG 命中、意图、风控和最终回复。
            这里只展示排查用业务信息，不展示密钥、cookie、token 或密码。
          </p>
        </div>

        <div className="trace-toolbar">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索 trace_id / shop_id / buyer_id / intent / domain"
          />
          <label className="trace-checkbox">
            <input checked={onlyErrors} onChange={(event) => setOnlyErrors(event.target.checked)} type="checkbox" />
            仅看异常
          </label>
          <label className="trace-checkbox">
            <input checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} type="checkbox" />
            3 秒实时刷新
          </label>
          <button type="button" onClick={() => void loadTraces(true)} disabled={loading}>
            {loading ? "刷新中..." : "立即刷新"}
          </button>
        </div>

        <div className="trace-log-summary">
          <span>当前列表 {filteredTraces.length} 条</span>
          <span>总计 {traces.length} 条</span>
          <span>最近刷新 {lastUpdatedAt || "未刷新"}</span>
          {autoRefresh ? <StatusBadge tone="success">实时刷新中</StatusBadge> : <StatusBadge tone="neutral">手动刷新</StatusBadge>}
        </div>

        {error ? <div className="warning-banner error-state">{error}</div> : null}
        {filteredTraces.length === 0 ? <div className="state-card">当前没有符合条件的链路日志。</div> : null}

        <div className="trace-log-list">
          {filteredTraces.map((trace) => (
            <button
              className={trace.trace_id === selectedTraceId ? "trace-log-row selected" : "trace-log-row"}
              key={trace.trace_id}
              onClick={() => void selectTrace(trace.trace_id)}
              type="button"
            >
              <div className="trace-row-head">
                <strong>{trace.trace_id}</strong>
                <StatusBadge tone={traceStatusTone(trace.final_status)}>{trace.final_status || "unknown"}</StatusBadge>
              </div>
              <div className="trace-row-meta">
                <span>{formatTraceTime(trace.time)}</span>
                <span>shop: {trace.shop_id || "unknown"}</span>
                <span>buyer: {trace.buyer_id || "unknown"}</span>
                <span>session: {trace.session_id || "unknown"}</span>
              </div>
              <div className="trace-row-badges">
                <StatusBadge tone="info">{trace.intent || "no_intent"}</StatusBadge>
                <StatusBadge tone="neutral">{trace.domain || "no_domain"}</StatusBadge>
                <StatusBadge tone={trace.action === "reply" ? "success" : "warning"}>{trace.action || "no_action"}</StatusBadge>
                <StatusBadge tone={trace.rag_hit_count > 0 ? "success" : "neutral"}>{`RAG ${trace.rag_hit_count}`}</StatusBadge>
                <StatusBadge tone={trace.no_send ? "info" : "danger"}>{trace.no_send ? "no-send" : "may-send"}</StatusBadge>
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="trace-log-detail-panel">
        {detailLoading ? <div className="state-card">正在加载 Trace 详情...</div> : null}
        <TracePanel trace={detail} />
        {detail ? (
          <details className="trace-section raw-trace-json">
            <summary>原始 Trace JSON</summary>
            <pre>{JSON.stringify(detail, null, 2)}</pre>
          </details>
        ) : null}
      </section>
    </div>
  );
}
