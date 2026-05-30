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
  if (["sent", "reply_sent", "done", "passed", "ok", "safe"].includes(text)) return "success";
  if (text.includes("fail") || text.includes("blocked") || text.includes("dead")) return "danger";
  if (text.includes("unknown") || text.includes("retry") || text.includes("suppressed") || text.includes("pending")) return "warning";
  return "neutral";
}

function formatTime(value?: string) {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function shortText(value: string, max = 86) {
  const text = String(value || "").trim();
  if (!text) return "无";
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function valueLabel(value: unknown) {
  if (value === null || value === undefined || value === "") return "无";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="observability-json">{typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)}</pre>;
}

function KeyValues({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data || {});
  if (entries.length === 0) return <div className="state-card">暂无数据。</div>;
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

function NodeList({ nodes }: { nodes: ChainNode[] }) {
  if (!nodes.length) return <div className="state-card">暂无链路节点。</div>;
  return (
    <div className="observability-node-list">
      {nodes.map((node, index) => (
        <div className="observability-node" key={`${node.key}-${index}`}>
          <div>
            <strong>{index + 1}. {node.label}</strong>
            <p>{node.summary}</p>
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
            <StatusBadge tone="info">{chunk.source_type || "unknown"}</StatusBadge>
          </header>
          <dl className="observability-kv compact">
            <div><dt>chunk_id</dt><dd>{chunk.chunk_id || "无"}</dd></div>
            <div><dt>source_id</dt><dd>{chunk.source_id || "无"}</dd></div>
            <div><dt>version</dt><dd>{chunk.version || "无"}</dd></div>
            <div><dt>score</dt><dd>{chunk.score ?? "无"}</dd></div>
            <div><dt>content_hash</dt><dd>{chunk.content_hash || "无"}</dd></div>
          </dl>
          <div className="observability-content">{chunk.content || "无内容"}</div>
          {chunk.metadata ? (
            <details>
              <summary>metadata / 字段来源</summary>
              <JsonBlock value={chunk.metadata} />
            </details>
          ) : null}
        </article>
      ))}
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
      {activeTab === "context" ? (
        <div className="observability-two-up">
          <section>
            <h4>Prompt 上下文</h4>
            <KeyValues data={message.prompt_context || {}} />
          </section>
          <section>
            <h4>完整上下文 JSON</h4>
            <JsonBlock value={message.prompt_context} />
          </section>
        </div>
      ) : null}
      {activeTab === "rag" ? (
        <>
          <dl className="observability-kv compact">
            <div><dt>RAG 查询</dt><dd>{message.rag_query || "无"}</dd></div>
            <div><dt>命中数量</dt><dd>{message.rag_hit_count}</dd></div>
          </dl>
          <ChunkList chunks={message.rag_chunks || []} />
        </>
      ) : null}
      {activeTab === "reply" ? (
        <div className="observability-two-up">
          <section>
            <h4>模型与意图</h4>
            <KeyValues data={message.reply_generation || {}} />
          </section>
          <section>
            <h4>模型原始响应</h4>
            <div className="observability-content">{String(message.reply_generation?.raw_response || message.generated_reply || "无")}</div>
          </section>
        </div>
      ) : null}
      {activeTab === "send" ? (
        <div className="observability-two-up">
          <section>
            <h4>发送状态</h4>
            <KeyValues data={message.send_retry || {}} />
          </section>
          <section>
            <h4>运营解释</h4>
            <div className="observability-content">
              <p><strong>当前状态：</strong>{message.final_status_label}</p>
              <p><strong>原因：</strong>{message.status_explanation}</p>
              <p><strong>建议：</strong>{message.recommended_action}</p>
            </div>
          </section>
        </div>
      ) : null}
      {activeTab === "tech" ? (
        <div className="observability-two-up">
          <section>
            <h4>技术字段</h4>
            <KeyValues data={message.technical || {}} />
          </section>
          <section>
            <h4>耗时拆分</h4>
            <KeyValues data={message.timing || {}} />
          </section>
        </div>
      ) : null}
    </div>
  );
}

function MessageCard({
  message,
  activeTab,
  onTabChange
}: {
  message: ConversationMessage;
  activeTab: DetailTab;
  onTabChange: (tab: DetailTab) => void;
}) {
  return (
    <article className="observability-message-card">
      <header className="observability-message-header">
        <div>
          <strong>{formatTime(message.created_at_iso || message.updated_at_iso)}</strong>
          <p className="muted">trace_id: {message.trace_id || "无"} · message_type: {message.message_type || "unknown"}</p>
        </div>
        <div className="header-badges">
          <StatusBadge tone={statusTone(message.final_status)}>{message.final_status_label || message.final_status}</StatusBadge>
          <StatusBadge tone={message.rag_hit_count > 0 ? "success" : "warning"}>{`RAG ${message.rag_hit_count}`}</StatusBadge>
        </div>
      </header>

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
    </article>
  );
}

export function TraceLogs() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selected, setSelected] = useState<ConversationSummary | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState("");
  const [activeTabs, setActiveTabs] = useState<Record<string, DetailTab>>({});

  const loadConversations = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const data = await getConversations({ limit: 200 });
      setConversations(data.items);
      setLastUpdatedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
      setSelected((current) => {
        if (current && data.items.some((item) => item.buyer_id === current.buyer_id && item.shop_id === current.shop_id)) {
          return current;
        }
        return data.items[0] || null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "链路观测加载失败");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  const loadMessages = useCallback(async (conversation: ConversationSummary | null) => {
    if (!conversation) {
      setMessages([]);
      return;
    }
    setMessagesLoading(true);
    setError(null);
    try {
      const data = await getConversationMessages(conversation.buyer_id, { shopId: conversation.shop_id, limit: 100 });
      setMessages(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "买家会话详情加载失败");
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadConversations(true);
  }, [loadConversations]);

  useEffect(() => {
    void loadMessages(selected);
  }, [loadMessages, selected]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      void loadConversations(false);
      void loadMessages(selected);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, loadConversations, loadMessages, selected]);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return conversations.filter((item) => {
      const status = String(item.last_status || "").toLowerCase();
      if (statusFilter === "attention" && item.failed_count <= 0 && !status.includes("fail") && !status.includes("blocked")) return false;
      if (statusFilter !== "all" && statusFilter !== "attention" && status !== statusFilter) return false;
      if (!keyword) return true;
      return [item.shop_id, item.buyer_id, item.session_id, item.last_message, item.last_send_text, item.last_trace_id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    });
  }, [conversations, query, statusFilter]);

  function setMessageTab(traceId: string, tab: DetailTab) {
    setActiveTabs((current) => ({ ...current, [traceId || "missing"]: tab }));
  }

  return (
    <div className="observability-page">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>链路观测</h2>
            <p className="muted">按买家 user_id 分组查看真实入站消息、AI 链路、RAG 命中、PDD 发送和 outbox 重试状态。</p>
          </div>
          <div className="header-badges">
            <StatusBadge tone={autoRefresh ? "success" : "neutral"}>{autoRefresh ? "实时刷新" : "手动刷新"}</StatusBadge>
            <StatusBadge tone="info">{`会话 ${conversations.length}`}</StatusBadge>
          </div>
        </div>
        <div className="observability-toolbar">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 shop_id / user_id / trace_id / 消息内容" />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">全部状态</option>
            <option value="attention">只看需处理</option>
            <option value="sent">发送成功</option>
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
        <p className="muted">最近刷新：{lastUpdatedAt || "尚未刷新"}</p>
        {error ? <div className="warning-banner error-state">{error}</div> : null}
      </section>

      <div className="observability-layout">
        <aside className="panel observability-conversations">
          <h3>买家会话</h3>
          {filtered.length === 0 ? <div className="state-card">暂无符合条件的会话。</div> : null}
          <div className="observability-conversation-list">
            {filtered.map((conversation) => {
              const selectedKey = selected ? `${selected.shop_id}|${selected.buyer_id}` : "";
              const key = `${conversation.shop_id}|${conversation.buyer_id}`;
              return (
                <button
                  className={selectedKey === key ? "conversation-row selected" : "conversation-row"}
                  key={key}
                  onClick={() => setSelected(conversation)}
                  type="button"
                >
                  <div className="conversation-row-head">
                    <strong>user_id {conversation.buyer_id || "unknown"}</strong>
                    <StatusBadge tone={statusTone(conversation.last_status)}>{conversation.last_status_label || conversation.last_status}</StatusBadge>
                  </div>
                  <p>{shortText(conversation.last_message)}</p>
                  <div className="conversation-row-meta">
                    <span>shop {conversation.shop_id || "unknown"}</span>
                    <span>{conversation.message_count} 条</span>
                    <span>{conversation.failed_count} 异常</span>
                    <span>{formatTime(conversation.last_active_at)}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        <main className="panel observability-detail">
          {selected ? (
            <div className="observability-selected-head">
              <div>
                <h3>user_id {selected.buyer_id}</h3>
                <p className="muted">shop_id {selected.shop_id} · session_id {selected.session_id || "无"} · trace_id {selected.last_trace_id || "无"}</p>
              </div>
              <StatusBadge tone={statusTone(selected.last_status)}>{selected.last_status_label || selected.last_status}</StatusBadge>
            </div>
          ) : (
            <div className="state-card">请选择一个买家会话。</div>
          )}
          {messagesLoading ? <div className="state-card">正在加载买家会话链路...</div> : null}
          <div className="observability-message-list">
            {messages.map((message) => (
              <MessageCard
                activeTab={activeTabs[message.trace_id || "missing"] || "nodes"}
                key={message.trace_id || `${message.created_at_iso}-${message.buyer_message}`}
                message={message}
                onTabChange={(tab) => setMessageTab(message.trace_id, tab)}
              />
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
