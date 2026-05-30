type TracePanelProps = {
  trace?: Record<string, unknown> | null;
};

type TraceField = {
  key: string;
  label: string;
};

const fieldGroups: Array<{ title: string; fields: TraceField[] }> = [
  {
    title: "链路身份与安全边界",
    fields: [
      { key: "trace_id", label: "Trace ID" },
      { key: "engine", label: "引擎" },
      { key: "smoke_profile", label: "调试模式" },
      { key: "engine_mode", label: "引擎模式" },
      { key: "engine_adapter_status", label: "引擎适配状态" },
      { key: "real_engine_called", label: "真实引擎已调用" },
      { key: "no_send", label: "no-send 模式" },
      { key: "sends_pdd", label: "发送 PDD 消息" }
    ]
  },
  {
    title: "LLM 调用证据",
    fields: [
      { key: "calls_llm", label: "调用 LLM" },
      { key: "llm_provider", label: "LLM provider" },
      { key: "llm_model", label: "LLM model" },
      { key: "llm_http_status", label: "LLM HTTP 状态" },
      { key: "llm_latency_ms", label: "LLM 耗时 ms" },
      { key: "llm_prompt_tokens", label: "Prompt tokens" },
      { key: "llm_completion_tokens", label: "Completion tokens" },
      { key: "llm_total_tokens", label: "Total tokens" },
      { key: "answer_generation_status", label: "回答生成状态" },
      { key: "answer_provider_host", label: "Provider host" },
      { key: "prompt_hash", label: "Prompt hash" },
      { key: "answer_hash", label: "Answer hash" }
    ]
  },
  {
    title: "RAG / Embedding / pgvector 证据",
    fields: [
      { key: "connects_pgvector", label: "连接 pgvector" },
      { key: "vector_store", label: "向量库" },
      { key: "embedding_provider", label: "Embedding provider" },
      { key: "embedding_model", label: "Embedding model" },
      { key: "embedding_latency_ms", label: "Embedding 耗时 ms" },
      { key: "pgvector_query_latency_ms", label: "pgvector 查询耗时 ms" },
      { key: "rag_total_latency_ms", label: "RAG 总耗时 ms" },
      { key: "rag_status", label: "RAG 状态" },
      { key: "rag_hit_count", label: "命中数量" },
      { key: "rag_domains", label: "命中领域" },
      { key: "rag_top_score", label: "Top score" },
      { key: "retrieval_mode", label: "检索模式" },
      { key: "top_hit_source", label: "Top hit 来源" },
      { key: "retrieved_chunks_unavailable", label: "命中但未返回片段" },
      { key: "retrieved_chunks_unavailable_reason", label: "未返回原因" }
    ]
  },
  {
    title: "上下文 / 意图 / 安全",
    fields: [
      { key: "product_context_status", label: "商品上下文状态" },
      { key: "product_anchor_source", label: "商品锚点来源" },
      { key: "history_message_count", label: "历史消息数" },
      { key: "intent", label: "意图" },
      { key: "domain", label: "领域" },
      { key: "action", label: "动作" },
      { key: "intent_classifier_status", label: "意图分类状态" },
      { key: "guardrail_status", label: "安全状态" },
      { key: "use_real_engine", label: "配置: real engine" },
      { key: "use_real_pgvector", label: "配置: pgvector" },
      { key: "use_real_llm", label: "配置: LLM" },
      { key: "use_real_intent_classifier", label: "配置: intent" },
      { key: "use_real_answer_generator", label: "配置: answer" }
    ]
  }
];

export function TracePanel({ trace }: TracePanelProps) {
  if (!trace) {
    return (
      <aside className="trace-panel">
        <h3>链路 Trace</h3>
        <p className="muted">选择或发送一条消息后，可以查看 InternalEngine 的完整调试链路。</p>
      </aside>
    );
  }

  return (
    <aside className="trace-panel trace-panel-detailed">
      <h3>链路 Trace</h3>
      <div className="trace-evidence-strip">
        <EvidencePill label="LLM" active={trace.calls_llm === true} />
        <EvidencePill label="pgvector" active={trace.connects_pgvector === true} />
        <EvidencePill label="RAG 命中" active={Number(trace.rag_hit_count ?? 0) > 0} />
        <EvidencePill label="no-send" active={trace.no_send === true} />
        <EvidencePill label="未发送 PDD" active={trace.sends_pdd === false} />
      </div>

      {fieldGroups.map((group) => (
        <TraceFieldGroup key={group.title} title={group.title} fields={group.fields} trace={trace} />
      ))}

      <TraceSection title="买家消息" value={trace.buyer_message} />
      <TraceSection title="AI 回复" value={trace.ai_reply} />
      <TraceSection title="RAG 查询" value={trace.rag_query} />
      <TraceSection title="商品上下文" value={trace.product_context} json />
      <TraceSection title="服务状态" value={trace.provider_status} json />
      <TraceSection title="阶段状态" value={trace.stage_status} json />
      <TraceSection title="耗时拆分" value={trace.latency_ms ?? trace.stage_timing} json />
      <TraceChunks trace={trace} />
      <TraceSection title="Prompt" value={trace.prompt} />
      <TraceSection title="模型原始响应" value={trace.raw_response} />
    </aside>
  );
}

function EvidencePill({ label, active }: { label: string; active: boolean }) {
  return <span className={active ? "trace-evidence-pill active" : "trace-evidence-pill"}>{label}: {active ? "是" : "否"}</span>;
}

function TraceFieldGroup({ title, fields, trace }: { title: string; fields: TraceField[]; trace: Record<string, unknown> }) {
  const visibleFields = fields.filter((field) => trace[field.key] !== undefined && trace[field.key] !== null && trace[field.key] !== "");
  if (!visibleFields.length) return null;
  return (
    <section className="trace-field-group">
      <h4>{title}</h4>
      <dl className="trace-kv-list">
        {visibleFields.map((field) => (
          <div className="trace-kv-row" key={field.key}>
            <dt title={field.key}>{field.label}</dt>
            <dd title={String(formatValue(trace[field.key]))}>{formatValue(trace[field.key])}</dd>
          </div>
        ))}
      </dl>
    </section>
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
          引擎报告 RAG 命中，但本次 trace 未携带 chunk 内容。原因：{formatValue(trace.retrieved_chunks_unavailable_reason)}
        </div>
      ) : null}
      {chunks.length === 0 ? (
        <p className="muted">本次没有返回正式知识 chunk。若 RAG 命中数为 0，说明当前问题没有匹配到已索引知识。</p>
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
      <dl className="trace-kv-list trace-chunk-meta">
        <div className="trace-kv-row"><dt>chunk_id</dt><dd>{formatValue(data.chunk_id ?? data.id)}</dd></div>
        <div className="trace-kv-row"><dt>score</dt><dd>{formatValue(data.score)}</dd></div>
        <div className="trace-kv-row"><dt>source_type</dt><dd>{formatValue(sourceType)}</dd></div>
        <div className="trace-kv-row"><dt>source_id</dt><dd>{formatValue(data.source_id)}</dd></div>
        <div className="trace-kv-row"><dt>version</dt><dd>{formatValue(data.version)}</dd></div>
        <div className="trace-kv-row"><dt>content_hash</dt><dd>{formatValue(data.content_hash)}</dd></div>
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

function TraceSection({ title, value, json = false }: { title: string; value: unknown; json?: boolean }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <details className="trace-section" open={title === "买家消息" || title === "AI 回复"}>
      <summary>{title}</summary>
      <pre>{json ? JSON.stringify(value, null, 2) : String(value)}</pre>
    </details>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function chunkKey(chunk: unknown, index: number) {
  const data = asRecord(chunk);
  return String(data.chunk_id ?? data.id ?? index);
}

function formatValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "无";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
