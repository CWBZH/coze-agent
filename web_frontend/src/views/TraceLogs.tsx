import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ChainNode,
  ConversationMessage,
  ConversationSummary,
  getConversationMessages,
  getConversations,
  RagChunk
} from "../api/observability";
import { StatusBadge } from "../components/StatusBadge";

type DetailTab = "nodes" | "context" | "rag" | "reply" | "send" | "tech";

const DETAIL_TABS: Array<{ key: DetailTab; label: string }> = [
  { key: "nodes", label: "链路节点" },
  { key: "context", label: "上下文拼接" },
  { key: "rag", label: "RAG 命中" },
  { key: "reply", label: "回复生成" },
  { key: "send", label: "发送与重试" },
  { key: "tech", label: "技术字段" }
];

function statusTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  const text = String(status || "").toLowerCase();
  if (["sent", "reply_sent", "done", "passed", "ok", "safe", "succeeded"].includes(text)) return "success";
  if (text.includes("fail") || text.includes("blocked") || text.includes("dead") || text.includes("error")) return "danger";
  if (text.includes("unknown") || text.includes("retry") || text.includes("suppressed") || text.includes("pending")) return "warning";
  return "neutral";
}

function timestamp(value?: string) {
  if (!value) return 0;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function formatTime(value?: string) {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function shortText(value?: string, max = 96) {
  const text = String(value || "").trim();
  if (!text) return "无";
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function valueLabel(value: unknown) {
  if (value === null || value === undefined || value === "") return "无";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function truthLabel(value: unknown) {
  if (value === true) return "是";
  if (value === false) return "否";
  return "未记录";
}

function intentFrom(message: ConversationMessage) {
  const reply = asRecord(message.reply_generation);
  const technical = asRecord(message.technical);
  const evidence = asRecord(message.intent_evidence);
  return String(evidence.intent || reply.intent || technical.intent || "").trim();
}

function conversationKey(conversation: Pick<ConversationSummary, "shop_id" | "buyer_id">) {
  return `${conversation.shop_id}|${conversation.buyer_id}`;
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="observability-json">{typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)}</pre>;
}

function KeyValues({ data, emptyText = "暂无数据。" }: { data: Record<string, unknown>; emptyText?: string }) {
  const entries = Object.entries(data || {});
  if (entries.length === 0) return <div className="state-card">{emptyText}</div>;
  return (
    <dl className="observability-kv">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{valueLabel(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function MetricCard({ label, value, note }: { label: string; value: string | number; note: string }) {
  return (
    <section className="observability-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </section>
  );
}

function NodeList({ nodes }: { nodes: ChainNode[] }) {
  if (!nodes.length) return <div className="state-card">暂无链路节点。请检查后端是否已写入 observability trace。</div>;
  return (
    <div className="observability-node-list">
      {nodes.map((node, index) => (
        <div className="observability-node" key={`${node.key}-${index}`}>
          <div>
            <strong>{index + 1}. {node.label}</strong>
            <p>{node.summary || "无节点说明"}</p>
          </div>
          <StatusBadge tone={statusTone(node.status)}>{node.status}</StatusBadge>
        </div>
      ))}
    </div>
  );
}

function ChunkList({ chunks }: { chunks: RagChunk[] }) {
  if (!chunks.length) {
    return <div className="state-card">本条消息没有命中正式知识 chunk。请检查商品知识或 SOP 是否已发布并索引成功。</div>;
  }
  return (
    <div className="observability-chunk-list">
      {chunks.map((chunk, index) => (
        <article className="observability-chunk" key={`${chunk.chunk_id || index}-${index}`}>
          <header>
            <strong>#{index + 1} {chunk.domain || "unknown"}</strong>
            <div className="header-badges">
              <StatusBadge tone="info">{chunk.source_type || "unknown"}</StatusBadge>
              <StatusBadge tone="neutral">{chunk.score === undefined ? "score 无" : `score ${chunk.score}`}</StatusBadge>
            </div>
          </header>
          <dl className="observability-kv compact">
            <div><dt>chunk_id</dt><dd>{chunk.chunk_id || "无"}</dd></div>
            <div><dt>source_id</dt><dd>{chunk.source_id || "无"}</dd></div>
            <div><dt>version</dt><dd>{chunk.version || "无"}</dd></div>
            <div><dt>content_hash</dt><dd>{chunk.content_hash || "无"}</dd></div>
          </dl>
          <div className="observability-content">{chunk.content || "无内容"}</div>
          {chunk.metadata ? (
            <details className="observability-nested-details">
              <summary>metadata / 字段来源</summary>
              <JsonBlock value={chunk.metadata} />
            </details>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function ContextTab({ message }: { message: ConversationMessage }) {
  const promptContext = asRecord(message.prompt_context);

  return (
    <div className="observability-tab-pane">
      <div className="observability-message-summary">
        <section>
          <span>买家消息</span>
          <p>{message.buyer_message || "无"}</p>
        </section>
        <section>
          <span>商品/会话上下文</span>
          <p>{shortText(valueLabel(message.prompt_context), 260)}</p>
        </section>
        <section>
          <span>历史对话拼接</span>
          <p>{shortText(String(promptContext.history || promptContext.conversation_history || "见完整 JSON"), 260)}</p>
        </section>
      </div>
      <div className="observability-two-up">
        <section>
          <h4>Prompt 上下文字段</h4>
          <KeyValues data={promptContext} />
        </section>
        <section>
          <h4>完整上下文 JSON</h4>
          <JsonBlock value={message.prompt_context} />
        </section>
      </div>
    </div>
  );
}

function ReplyTab({ message }: { message: ConversationMessage }) {
  const reply = asRecord(message.reply_generation);
  const technical = asRecord(message.technical);
  const intent = asRecord(message.intent_evidence);
  const evidence = {
    calls_llm: technical.calls_llm ?? reply.calls_llm,
    answer_generation_status: reply.answer_generation_status ?? technical.answer_generation_status,
    answer_generator_called: reply.answer_generator_called ?? technical.answer_generator_called,
    model: reply.model ?? reply.llm_model ?? technical.llm_model,
    raw_response: reply.raw_response || message.generated_reply || "无"
  };
  const intentEvidence = {
    "识别意图": intent.intent || reply.intent || technical.intent || "未返回",
    "意图状态": intent.status || reply.intent_status || technical.intent_status || "未记录",
    "识别来源": intent.source_label || reply.intent_source_label || intent.source || reply.intent_source || "未记录",
    "独立分类器调用": truthLabel(intent.classifier_called ?? reply.intent_classifier_called ?? technical.intent_classifier_called),
    "LLM 分类器调用": truthLabel(intent.llm_intent_called ?? reply.llm_intent_called ?? technical.llm_intent_called),
    "归一化意图": intent.normalized_intent || reply.normalized_intent || "无",
    "分类器原始意图": intent.classifier_intent || reply.classifier_intent || "无",
    "置信度": intent.classifier_confidence ?? reply.classifier_confidence ?? "未记录",
    "运营解释": intent.observation || technical.intent_observation || "未记录"
  };

  return (
    <div className="observability-two-up">
      <section>
        <h4>意图识别证据</h4>
        <KeyValues data={intentEvidence} />
      </section>
      <section>
        <h4>LLM 调用证据</h4>
        <KeyValues data={evidence} />
      </section>
      <section>
        <h4>生成结果</h4>
        <div className="observability-content">{message.generated_reply || "无"}</div>
      </section>
      <section>
        <h4>回复生成字段</h4>
        <KeyValues data={reply} />
      </section>
      <section>
        <h4>模型原始响应</h4>
        <div className="observability-content">{String(reply.raw_response || message.generated_reply || "无")}</div>
      </section>
    </div>
  );
}

function SendTab({ message }: { message: ConversationMessage }) {
  return (
    <div className="observability-two-up">
      <section>
        <h4>PDD 发送与 outbox</h4>
        <KeyValues data={asRecord(message.send_retry)} />
      </section>
      <section>
        <h4>运营解释</h4>
        <div className="observability-content">
          <p><strong>当前状态：</strong>{message.final_status_label || message.final_status || "无"}</p>
          <p><strong>原因：</strong>{message.status_explanation || "无"}</p>
          <p><strong>建议：</strong>{message.recommended_action || "无"}</p>
          <p><strong>PDD 实际发送内容：</strong>{message.send_text || "未发送或未进入发送阶段"}</p>
        </div>
      </section>
    </div>
  );
}

function MessageTabs({
  message,
  activeTab,
  onTabChange
}: {
  message: ConversationMessage;
  activeTab: DetailTab;
  onTabChange: (tab: DetailTab) => void;
}) {
  return (
    <div className="observability-message-detail">
      <div className="observability-tab-row">
        {DETAIL_TABS.map((tab) => (
          <button
            className={activeTab === tab.key ? "tab-button active" : "tab-button"}
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "nodes" ? <NodeList nodes={message.nodes || []} /> : null}
      {activeTab === "context" ? <ContextTab message={message} /> : null}
      {activeTab === "rag" ? (
        <div className="observability-tab-pane">
          <dl className="observability-kv compact">
            <div><dt>RAG 查询</dt><dd>{message.rag_query || "无"}</dd></div>
            <div><dt>命中数量</dt><dd>{message.rag_hit_count}</dd></div>
          </dl>
          <ChunkList chunks={message.rag_chunks || []} />
        </div>
      ) : null}
      {activeTab === "reply" ? <ReplyTab message={message} /> : null}
      {activeTab === "send" ? <SendTab message={message} /> : null}
      {activeTab === "tech" ? (
        <div className="observability-two-up">
          <section>
            <h4>技术字段</h4>
            <KeyValues data={asRecord(message.technical)} />
          </section>
          <section>
            <h4>耗时拆分</h4>
            <KeyValues data={asRecord(message.timing)} />
          </section>
        </div>
      ) : null}
    </div>
  );
}

function MessageDetails({
  message,
  activeTab,
  defaultOpen,
  onTabChange
}: {
  message: ConversationMessage;
  activeTab: DetailTab;
  defaultOpen: boolean;
  onTabChange: (tab: DetailTab) => void;
}) {
  const intent = intentFrom(message);
  return (
    <details className="observability-message-details" open={defaultOpen}>
      <summary>
        <div className="observability-message-summary-row">
          <div className="observability-message-main">
            <strong>{formatTime(message.created_at_iso || message.updated_at_iso)}</strong>
            <span>user_id {message.buyer_id || message.user_id || "unknown"}</span>
            <span>{message.message_type || "unknown"}</span>
            <span>trace_id {message.trace_id || "无"}</span>
          </div>
          <div className="header-badges">
            {intent ? <StatusBadge tone="info">{intent}</StatusBadge> : null}
            <StatusBadge tone={statusTone(message.final_status)}>{message.final_status_label || message.final_status || "unknown"}</StatusBadge>
            <StatusBadge tone={message.rag_hit_count > 0 ? "success" : "warning"}>{`RAG ${message.rag_hit_count ?? 0}`}</StatusBadge>
          </div>
        </div>
        <div className="observability-message-preview">
          <span>买家：{shortText(message.buyer_message, 140)}</span>
          <span>回复：{shortText(message.generated_reply || message.send_text, 140)}</span>
        </div>
      </summary>

      <div className="observability-message-expanded">
        <div className="observability-message-summary">
          <section>
            <span>买家消息</span>
            <p>{message.buyer_message || "无"}</p>
          </section>
          <section>
            <span>生成回复</span>
            <p>{message.generated_reply || "无"}</p>
          </section>
          <section>
            <span>PDD 实际发送内容</span>
            <p>{message.send_text || "未发送或未进入发送阶段"}</p>
          </section>
        </div>
        <MessageTabs message={message} activeTab={activeTab} onTabChange={onTabChange} />
      </div>
    </details>
  );
}

function BuyerCard({
  conversation,
  selected,
  onSelect
}: {
  conversation: ConversationSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button className={selected ? "observability-buyer-card active" : "observability-buyer-card"} onClick={onSelect} type="button">
      <div className="observability-buyer-head">
        <strong>user_id {conversation.buyer_id || "unknown"}</strong>
        <StatusBadge tone={statusTone(conversation.last_status)}>{conversation.last_status_label || conversation.last_status || "unknown"}</StatusBadge>
      </div>
      <div className="observability-buyer-meta">
        <span>shop {conversation.shop_id || "unknown"}</span>
        <span>{conversation.message_count} 条消息</span>
        <span>{formatTime(conversation.last_active_at)}</span>
      </div>
      <div className="observability-buyer-last">
        <span>买家：{shortText(conversation.last_message, 68)}</span>
        <span>回复：{shortText(conversation.last_send_text, 68)}</span>
      </div>
    </button>
  );
}

export function TraceLogs() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [query, setQuery] = useState("");
  const [shopFilter, setShopFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState("");
  const [activeTabs, setActiveTabs] = useState<Record<string, DetailTab>>({});

  const sortedConversations = useMemo(() => {
    return [...conversations].sort((a, b) => timestamp(b.last_active_at) - timestamp(a.last_active_at));
  }, [conversations]);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return sortedConversations.filter((item) => {
      const status = String(item.last_status || "").toLowerCase();
      if (statusFilter === "attention" && item.failed_count <= 0 && !status.includes("fail") && !status.includes("blocked")) return false;
      if (statusFilter !== "all" && statusFilter !== "attention" && status !== statusFilter) return false;
      if (!keyword) return true;
      return [item.shop_id, item.buyer_id, item.session_id, item.last_message, item.last_send_text, item.last_trace_id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    });
  }, [sortedConversations, query, statusFilter]);

  const selected = useMemo(() => {
    return sortedConversations.find((item) => conversationKey(item) === selectedKey) || filtered[0] || null;
  }, [filtered, selectedKey, sortedConversations]);

  const sortedMessages = useMemo(() => {
    return [...messages].sort((a, b) => {
      const bTime = timestamp(b.created_at_iso || b.updated_at_iso);
      const aTime = timestamp(a.created_at_iso || a.updated_at_iso);
      return bTime - aTime;
    });
  }, [messages]);

  const metrics = useMemo(() => {
    const totalMessages = conversations.reduce((sum, item) => sum + Number(item.message_count || 0), 0);
    const failedCount = conversations.reduce((sum, item) => sum + Number(item.failed_count || 0), 0);
    const selectedRagHits = sortedMessages.filter((item) => Number(item.rag_hit_count || 0) > 0).length;
    const selectedSent = sortedMessages.filter((item) => statusTone(item.final_status) === "success").length;
    return {
      conversationCount: conversations.length,
      totalMessages,
      failedCount,
      selectedCount: sortedMessages.length,
      selectedRagHits,
      selectedSent
    };
  }, [conversations, sortedMessages]);

  const loadConversations = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const data = await getConversations({ shopId: shopFilter.trim() || undefined, limit: 200 });
      const items = data.items || [];
      setConversations(items);
      setLastUpdatedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
      setSelectedKey((current) => {
        if (current && items.some((item) => conversationKey(item) === current)) return current;
        const newest = [...items].sort((a, b) => timestamp(b.last_active_at) - timestamp(a.last_active_at))[0];
        return newest ? conversationKey(newest) : "";
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "链路观测加载失败");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [shopFilter]);

  const loadMessages = useCallback(async (conversation: ConversationSummary | null, showLoading = false) => {
    if (!conversation) {
      setMessages([]);
      return;
    }
    if (showLoading) setMessagesLoading(true);
    setError(null);
    try {
      const data = await getConversationMessages(conversation.buyer_id, { shopId: conversation.shop_id, limit: 100 });
      setMessages(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "买家会话详情加载失败");
    } finally {
      if (showLoading) setMessagesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadConversations(true);
  }, [loadConversations]);

  useEffect(() => {
    void loadMessages(selected, true);
  }, [loadMessages, selected]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      void loadConversations(false);
      void loadMessages(selected, false);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, loadConversations, loadMessages, selected]);

  function setMessageTab(traceId: string, tab: DetailTab) {
    setActiveTabs((current) => ({ ...current, [traceId || "missing"]: tab }));
  }

  return (
    <div className="observability-page observability-v2">
      <section className="panel observability-hero">
        <div className="panel-header">
          <div>
            <h2>链路观测</h2>
            <p className="muted">按买家 user_id 聚合真实入站消息、历史上下文、商品/SOP RAG、LLM 生成、PDD 发送和 outbox 重试。最新会话和最新消息默认排在最上面。</p>
          </div>
          <div className="header-badges">
            <StatusBadge tone={autoRefresh ? "success" : "neutral"}>{autoRefresh ? "实时刷新" : "手动刷新"}</StatusBadge>
            <StatusBadge tone="info">{`会话 ${conversations.length}`}</StatusBadge>
          </div>
        </div>

        <div className="observability-metrics">
          <MetricCard label="买家会话" value={metrics.conversationCount} note="当前筛选范围" />
          <MetricCard label="消息总量" value={metrics.totalMessages} note="会话摘要统计" />
          <MetricCard label="异常/待处理" value={metrics.failedCount} note="发送失败、阻断或需人工" />
          <MetricCard label="当前会话消息" value={metrics.selectedCount} note={selected ? `user_id ${selected.buyer_id}` : "未选择买家"} />
          <MetricCard label="当前会话 RAG" value={metrics.selectedRagHits} note="命中正式知识的消息数" />
          <MetricCard label="当前会话已发送" value={metrics.selectedSent} note="PDD 确认或处理成功" />
        </div>

        <div className="observability-toolbar">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 shop_id / user_id / trace_id / 买家消息 / 回复内容" />
          <input value={shopFilter} onChange={(event) => setShopFilter(event.target.value)} placeholder="shop_id，可留空" />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">全部状态</option>
            <option value="attention">只看需处理</option>
            <option value="sent">发送成功 sent</option>
            <option value="reply_sent">reply_sent</option>
            <option value="reply_send_failed">回复发送失败</option>
            <option value="blocked_by_platform_policy">平台策略阻断</option>
            <option value="suppressed_duplicate">重复压制</option>
          </select>
          <label className="trace-checkbox">
            <input checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} type="checkbox" />
            5 秒刷新
          </label>
          <button type="button" onClick={() => void loadConversations(true)} disabled={loading}>
            {loading ? "刷新中..." : "立即刷新"}
          </button>
        </div>

        <div className="observability-selected-strip">
          <span>最近刷新：{lastUpdatedAt || "尚未刷新"}</span>
          {selected ? (
            <>
              <span>当前买家：user_id {selected.buyer_id}</span>
              <span>shop_id {selected.shop_id}</span>
              <span>消息 {selected.message_count} 条</span>
              <span>异常 {selected.failed_count} 条</span>
              <span>最后活跃：{formatTime(selected.last_active_at)}</span>
            </>
          ) : (
            <span>未选择会话</span>
          )}
        </div>

        {error ? <div className="warning-banner error-state">{error}</div> : null}
      </section>

      <section className="observability-workbench">
        <aside className="panel observability-buyers">
          <div className="observability-section-head">
            <div>
              <h3>买家会话</h3>
              <p className="muted">点击买家后，右侧查看该买家的倒序消息链路。</p>
            </div>
            <StatusBadge tone="info">{`${filtered.length} 个`}</StatusBadge>
          </div>
          <div className="observability-buyer-list">
            {filtered.length === 0 ? <div className="state-card">暂无符合筛选条件的买家会话。</div> : null}
            {filtered.map((conversation) => (
              <BuyerCard
                conversation={conversation}
                key={conversationKey(conversation)}
                onSelect={() => setSelectedKey(conversationKey(conversation))}
                selected={conversationKey(conversation) === conversationKey(selected || conversation)}
              />
            ))}
          </div>
        </aside>

        <main className="panel observability-detail">
          <div className="observability-selected-head">
            <div>
              <h3>{selected ? `user_id ${selected.buyer_id}` : "买家会话"}</h3>
              <p className="muted">
                {selected
                  ? `shop_id ${selected.shop_id} · session_id ${selected.session_id || "无"} · trace_id ${selected.last_trace_id || "无"}`
                  : "请选择一个买家会话。"}
              </p>
            </div>
            {selected ? <StatusBadge tone={statusTone(selected.last_status)}>{selected.last_status_label || selected.last_status || "unknown"}</StatusBadge> : null}
          </div>

          {messagesLoading && sortedMessages.length === 0 ? <div className="state-card">正在加载买家会话链路...</div> : null}
          {!messagesLoading && sortedMessages.length === 0 ? <div className="state-card">暂无消息日志。</div> : null}

          <div className="observability-message-list">
            {sortedMessages.map((message, index) => (
              <MessageDetails
                activeTab={activeTabs[message.trace_id || "missing"] || "nodes"}
                defaultOpen={index === 0}
                key={message.trace_id || `${message.created_at_iso}-${message.buyer_message}`}
                message={message}
                onTabChange={(tab) => setMessageTab(message.trace_id, tab)}
              />
            ))}
          </div>
        </main>
      </section>
    </div>
  );
}
