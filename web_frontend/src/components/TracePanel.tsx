type TracePanelProps = {
  trace?: Record<string, unknown> | null;
};

const primaryFields = [
  "trace_id",
  "engine",
  "smoke_profile",
  "engine_mode",
  "engine_adapter_status",
  "real_engine_called",
  "product_context_status",
  "product_anchor_source",
  "history_message_count",
  "intent_classifier_status",
  "rag_status",
  "rag_hit_count",
  "retrieved_chunks_unavailable",
  "retrieved_chunks_unavailable_reason",
  "answer_generation_status",
  "guardrail_status",
  "calls_llm",
  "calls_ollama",
  "connects_pgvector",
  "use_real_engine",
  "use_real_pgvector",
  "use_real_ollama",
  "use_real_llm",
  "use_real_intent_classifier",
  "use_real_answer_generator",
  "sends_pdd",
  "no_send"
];

export function TracePanel({ trace }: TracePanelProps) {
  if (!trace) {
    return (
      <aside className="trace-panel">
        <h3>链路 Trace</h3>
        <p className="muted">选择或发送一条消息后，可查看 InternalEngine 调试链路。</p>
      </aside>
    );
  }

  return (
    <aside className="trace-panel trace-panel-detailed">
      <h3>链路 Trace</h3>
      <dl className="kv-grid">
        {primaryFields.map((field) => (
          <div key={field}>
            <dt>{field}</dt>
            <dd>{formatValue(trace[field])}</dd>
          </div>
        ))}
      </dl>

      <TraceSection title="买家消息" value={trace.buyer_message} />
      <TraceSection title="AI 回复" value={trace.ai_reply} />
      <TraceSection title="RAG 查询" value={trace.rag_query} />
      <TraceSection title="商品上下文" value={trace.product_context} json />
      <TraceSection title="服务状态" value={trace.provider_status} json />
      <TraceSection title="阶段状态" value={trace.stage_status} json />
      <TraceSection title="耗时拆分" value={trace.latency_ms} json />
      <TraceChunks trace={trace} />
      <TraceSection title="Prompt" value={trace.prompt} />
      <TraceSection title="模型原始响应" value={trace.raw_response} />
    </aside>
  );
}

function TraceChunks({ trace }: { trace: Record<string, unknown> }) {
  const unavailable = trace.retrieved_chunks_unavailable === true;
  const chunks = Array.isArray(trace.retrieved_chunks) ? trace.retrieved_chunks : [];
  return (
    <details className="trace-section" open>
      <summary>检索命中片段</summary>
      {unavailable ? (
        <div className="warning-banner">
          引擎报告有 RAG 命中，但本次 trace 未携带 chunk 内容。
          原因：{formatValue(trace.retrieved_chunks_unavailable_reason)}
        </div>
      ) : null}
      {chunks.length === 0 ? (
        <p className="muted">本次没有返回正式知识 chunk。若只看到临时商品上下文，说明真实 RAG 未命中或未启用。</p>
      ) : (
        <div className="trace-chunk-list">
          {chunks.map((chunk, index) => (
            <TraceChunkCard key={chunkKey(chunk, index)} chunk={chunk} index={index} />
          ))}
        </div>
      )}
    </details>
  );
}

function TraceChunkCard({ chunk, index }: { chunk: unknown; index: number }) {
  const data = asRecord(chunk);
  const sourceType = String(data.source_type ?? data.source ?? "");
  const isSessionContext = sourceType === "session_product_context";
  const content = String(data.content ?? data.content_summary ?? data.approved_answer ?? "");
  const metadata = asRecord(data.metadata);
  return (
    <article className={isSessionContext ? "trace-chunk-card trace-chunk-card-warning" : "trace-chunk-card"}>
      <div className="trace-chunk-head">
        <strong>#{index + 1} {String(data.domain ?? "unknown")}</strong>
        <span>{isSessionContext ? "临时会话上下文" : "正式知识命中"}</span>
      </div>
      <dl className="kv-grid trace-chunk-meta">
        <div><dt>chunk_id</dt><dd>{formatValue(data.chunk_id ?? data.id)}</dd></div>
        <div><dt>score</dt><dd>{formatValue(data.score)}</dd></div>
        <div><dt>source_type</dt><dd>{formatValue(sourceType)}</dd></div>
        <div><dt>source_id</dt><dd>{formatValue(data.source_id)}</dd></div>
        <div><dt>version</dt><dd>{formatValue(data.version)}</dd></div>
        <div><dt>content_hash</dt><dd>{formatValue(data.content_hash)}</dd></div>
      </dl>
      <pre>{content}</pre>
      {Object.keys(metadata).length ? (
        <details>
          <summary>metadata / 字段来源</summary>
          <pre>{JSON.stringify(metadata, null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function chunkKey(chunk: unknown, index: number) {
  const data = asRecord(chunk);
  return String(data.chunk_id ?? data.id ?? index);
}

function TraceSection({ title, value, json = false }: { title: string; value: unknown; json?: boolean }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <details className="trace-section" open={title === "买家消息" || title === "AI 回复"}>
      <summary>{title}</summary>
      <pre>{json ? JSON.stringify(value, null, 2) : String(value)}</pre>
    </details>
  );
}

function formatValue(value: unknown) {
  if (value === undefined || value === null) return "无";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
