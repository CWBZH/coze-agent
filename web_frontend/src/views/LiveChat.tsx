import { useEffect, useMemo, useState } from "react";

import { createLiveChatSession, LiveChatResponse, sendLiveChatMessage } from "../api/liveChat";
import { getProviderStatus, ProviderStatus } from "../api/providerStatus";
import { getShops, Shop } from "../api/shops";
import { StatusBadge } from "../components/StatusBadge";
import { TracePanel } from "../components/TracePanel";

type ChatMessage = { role: "buyer" | "ai"; text: string; result?: LiveChatResponse };

type LiveChatConfig = {
  smokeProfile: string;
  useRag: boolean;
  useIntentClassifier: boolean;
  useAnswerGenerator: boolean;
  useRealEngine: boolean;
  useRealLlm: boolean;
  useRealOllama: boolean;
  useRealPgvector: boolean;
  useRealIntentClassifier: boolean;
  useRealAnswerGenerator: boolean;
  showTrace: boolean;
  ragTopK: number;
  productVersion: string;
  sopVersion: string;
};

const defaultConfig: LiveChatConfig = {
  smokeProfile: "facade",
  useRag: true,
  useIntentClassifier: false,
  useAnswerGenerator: false,
  useRealEngine: false,
  useRealLlm: false,
  useRealOllama: false,
  useRealPgvector: false,
  useRealIntentClassifier: false,
  useRealAnswerGenerator: false,
  showTrace: true,
  ragTopK: 3,
  productVersion: "real-product-v1",
  sopVersion: "sop-test-v1"
};

export function LiveChat() {
  const [shops, setShops] = useState<Shop[]>([]);
  const [selectedShopId, setSelectedShopId] = useState("");
  const [buyerId, setBuyerId] = useState("web-buyer-demo");
  const [sessionId, setSessionId] = useState("");
  const [message, setMessage] = useState("这个多少钱");
  const [goodsId, setGoodsId] = useState("");
  const [goodsName, setGoodsName] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trace, setTrace] = useState<Record<string, unknown> | null>(null);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [config, setConfig] = useState<LiveChatConfig>(defaultConfig);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedShop = useMemo(
    () => shops.find((shop) => shop.shop_id === selectedShopId) ?? shops[0],
    [shops, selectedShopId]
  );

  useEffect(() => {
    let cancelled = false;
    getShops()
      .then((payload) => {
        if (cancelled) return;
        setShops(payload.items);
        setSelectedShopId((current) => current || payload.items[0]?.shop_id || "");
      })
      .catch((err: Error) => setError(err.message));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void refreshProviderStatus();
  }, []);

  async function refreshProviderStatus() {
    try {
      setProviderStatus(await getProviderStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : "服务状态加载失败");
    }
  }

  useEffect(() => {
    if (!selectedShopId) return;
    let cancelled = false;
    createLiveChatSession(selectedShopId, buyerId)
      .then((session) => {
        if (cancelled) return;
        setSessionId(session.session_id);
        setMessages([]);
        setTrace(null);
      })
      .catch((err: Error) => setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [selectedShopId, buyerId]);

  async function send() {
    if (!sessionId || !selectedShopId || !message.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const effective = profileConfig(config.smokeProfile, config);
      const result = await sendLiveChatMessage(sessionId, {
        shop_id: selectedShopId,
        buyer_id: buyerId,
        message,
        metadata: {
          goods_id: goodsId || null,
          goods_name: goodsName || null
        },
        use_rag: effective.useRag,
        use_llm_intent_classifier: effective.useIntentClassifier,
        use_llm_answer_generator: effective.useAnswerGenerator,
        use_real_engine: effective.useRealEngine,
        use_real_llm: effective.useRealLlm,
        use_real_ollama: effective.useRealOllama,
        use_real_pgvector: effective.useRealPgvector,
        use_real_intent_classifier: effective.useRealIntentClassifier,
        use_real_answer_generator: effective.useRealAnswerGenerator,
        product_version: effective.productVersion,
        sop_version: effective.sopVersion,
        rag_top_k: effective.ragTopK,
        smoke_profile: effective.smokeProfile,
        no_send: true
      });
      setMessages((items) => [...items, { role: "buyer", text: message }, { role: "ai", text: result.reply, result }]);
      setTrace(result.trace);
      setMessage("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送测试消息失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="live-chat-layout">
      <section className="panel config-panel">
        <div className="panel-header">
          <div>
            <h2>调试配置</h2>
            <p className="muted">用于 no-send 测试 AI 回复，默认不会发送 PDD 消息。</p>
          </div>
          <StatusBadge tone="info">不发送真实消息 no_send</StatusBadge>
        </div>
        {error ? <div className="warning-banner error-state">{error}</div> : null}
        <label>
          调试模式
          <select value={config.smokeProfile} onChange={(event) => setConfig(profileConfig(event.target.value, config))}>
            <option value="facade">facade</option>
            <option value="real_engine_only">real_engine_only</option>
            <option value="real_rag">real_rag</option>
            <option value="real_intent">real_intent</option>
            <option value="real_answer">real_answer</option>
            <option value="real_full">real_full</option>
          </select>
        </label>
        <label>
          店铺
          <select value={selectedShopId} onChange={(event) => setSelectedShopId(event.target.value)}>
            {shops.map((shop) => (
              <option key={shop.shop_id} value={shop.shop_id}>
                {shop.shop_name} ({shop.shop_id})
              </option>
            ))}
          </select>
        </label>
        <label>
          买家 ID
          <input value={buyerId} onChange={(event) => setBuyerId(event.target.value)} />
        </label>
        <div className="state-card">
          <strong>{selectedShop?.shop_name ?? "未选择店铺"}</strong>
          <p>{config.useRealEngine ? "真实 InternalEngine no-send 模式" : "Facade 安全模拟模式"} · PDD 真实发送已关闭</p>
        </div>
        {config.smokeProfile === "real_full" && hasMissingProvider(providerStatus) ? (
          <div className="warning-banner">
            Web API 进程缺少真实服务配置，本次请求会安全返回，不会发送 PDD。
          </div>
        ) : null}
        {config.smokeProfile === "real_full" ? (
          <div className="warning-banner">
            real_full 会调用真实 LLM、Embedding 和 pgvector，但仍为 no-send，不会发送 PDD。
          </div>
        ) : null}
        <label>
          goods_id
          <input value={goodsId} onChange={(event) => setGoodsId(event.target.value)} placeholder="可选：商品卡片 goods_id" />
        </label>
        <label>
          goods_name
          <input value={goodsName} onChange={(event) => setGoodsName(event.target.value)} placeholder="可选：商品卡片 goods_name" />
        </label>
        <div className="button-row">
          <button type="button" onClick={() => { setGoodsId(""); setGoodsName(""); }}>清空商品卡片</button>
        </div>
        <label>
          商品版本
          <input value={config.productVersion} onChange={(event) => setConfig({ ...config, productVersion: event.target.value })} />
        </label>
        <label>
          SOP 版本
          <input value={config.sopVersion} onChange={(event) => setConfig({ ...config, sopVersion: event.target.value })} />
        </label>
        <label>
          RAG Top K
          <input
            type="number"
            min={1}
            max={20}
            value={config.ragTopK}
            onChange={(event) => setConfig({ ...config, ragTopK: Number(event.target.value) })}
          />
        </label>
        <Toggle label="RAG" checked={config.useRag} onChange={(value) => setConfig({ ...config, useRag: value })} />
        <Toggle label="意图分类器" checked={config.useIntentClassifier} onChange={(value) => setConfig({ ...config, useIntentClassifier: value })} />
        <Toggle label="回答生成器" checked={config.useAnswerGenerator} onChange={(value) => setConfig({ ...config, useAnswerGenerator: value })} />
        <Toggle label="显示 Trace" checked={config.showTrace} onChange={(value) => setConfig({ ...config, showTrace: value })} />
        <Toggle label="使用真实 InternalEngine" checked={config.useRealEngine} onChange={(value) => setConfig({ ...config, useRealEngine: value })} />
        <Toggle label="使用真实 LLM" checked={config.useRealLlm} onChange={(value) => setConfig({ ...config, useRealLlm: value })} />
        <Toggle label="使用真实 Embedding 服务" checked={config.useRealOllama} onChange={(value) => setConfig({ ...config, useRealOllama: value })} />
        <Toggle label="使用真实 pgvector" checked={config.useRealPgvector} onChange={(value) => setConfig({ ...config, useRealPgvector: value })} />
        <Toggle label="使用真实意图分类器" checked={config.useRealIntentClassifier} onChange={(value) => setConfig({ ...config, useRealIntentClassifier: value })} />
        <Toggle label="使用真实回答生成器" checked={config.useRealAnswerGenerator} onChange={(value) => setConfig({ ...config, useRealAnswerGenerator: value })} />
        <div className="panel-header compact-header">
          <h3>服务状态</h3>
          <button type="button" onClick={() => void refreshProviderStatus()}>刷新</button>
        </div>
        <div className="status-list">
          <StatusBadge tone="success">InternalEngine 就绪</StatusBadge>
          <StatusBadge tone={statusTone(providerStatus?.providers.pgvector?.status)}>{`PgVector ${providerStatus?.providers.pgvector?.status ?? "unknown"}`}</StatusBadge>
          <StatusBadge tone={statusTone(providerStatus?.providers.embedding?.status)}>{`Embedding ${providerStatus?.providers.embedding?.status ?? "unknown"}`}</StatusBadge>
          <StatusBadge tone={statusTone(providerStatus?.providers.llm?.status)}>{`LLM ${providerStatus?.providers.llm?.status ?? "unknown"}`}</StatusBadge>
          <StatusBadge tone="info">no-send 已启用</StatusBadge>
          <StatusBadge tone="warning">PDD 真实发送已关闭</StatusBadge>
        </div>
      </section>

      <section className="panel chat-panel">
        <div className="panel-header">
          <div>
            <h2>试聊窗口</h2>
            <p className="muted">会话：{sessionId || "创建中..."}</p>
          </div>
          <StatusBadge tone="success">InternalEngine</StatusBadge>
        </div>
        <div className="chat-stream">
          {messages.length === 0 ? <div className="state-card">暂无消息。发送一条买家问题后，可在右侧查看 no-send 链路。</div> : null}
          {messages.map((item, index) => (
            <div className={`chat-bubble ${item.role}`} key={`${item.role}-${index}`}>
              <p>{item.text}</p>
              {item.result ? (
                <div className="bubble-badges">
                  <StatusBadge tone="info">{item.result.intent}</StatusBadge>
                  <StatusBadge tone={item.result.action === "reply" ? "success" : "warning"}>{item.result.action}</StatusBadge>
                  <StatusBadge tone="neutral">{item.result.domain ?? "none"}</StatusBadge>
                  <StatusBadge tone="info">{`RAG ${String(item.result.trace.rag_hit_count ?? 0)}`}</StatusBadge>
                  <StatusBadge tone="success">{String(item.result.trace.guardrail_status ?? "safe")}</StatusBadge>
                  <StatusBadge tone="neutral">{String(item.result.trace.answer_generation_status ?? "unknown")}</StatusBadge>
                  <StatusBadge tone="info">{String(item.result.trace.engine_mode ?? "facade")}</StatusBadge>
                  <StatusBadge tone="neutral">{providerSummary(item.result.trace)}</StatusBadge>
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <div className="chat-input">
          <input
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="输入买家消息。仅 no-send 测试，不会发送到 PDD。"
            onKeyDown={(event) => {
              if (event.key === "Enter") void send();
            }}
          />
          <button onClick={send} disabled={loading || !message.trim()}>{loading ? "发送中..." : "发送测试消息"}</button>
        </div>
      </section>

      {config.showTrace ? <TracePanel trace={trace} /> : null}
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle-row">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

function profileConfig(profile: string, current: LiveChatConfig): LiveChatConfig {
  const base = { ...current, smokeProfile: profile };
  if (profile === "facade") {
    return {
      ...base,
      useRealEngine: false,
      useRealPgvector: false,
      useRealOllama: false,
      useRealLlm: false,
      useRealIntentClassifier: false,
      useRealAnswerGenerator: false
    };
  }
  if (profile === "real_engine_only") {
    return {
      ...base,
      useRealEngine: true,
      useRealPgvector: false,
      useRealOllama: false,
      useRealLlm: false,
      useRealIntentClassifier: false,
      useRealAnswerGenerator: false
    };
  }
  if (profile === "real_rag") {
    return {
      ...base,
      useRealEngine: true,
      useRealPgvector: true,
      useRealOllama: false,
      useRealLlm: false,
      useRealIntentClassifier: false,
      useRealAnswerGenerator: false
    };
  }
  if (profile === "real_intent") {
    return {
      ...base,
      useRealEngine: true,
      useRealPgvector: false,
      useRealOllama: false,
      useRealLlm: true,
      useRealIntentClassifier: true,
      useRealAnswerGenerator: false
    };
  }
  if (profile === "real_answer") {
    return {
      ...base,
      useRealEngine: true,
      useRealPgvector: false,
      useRealOllama: false,
      useRealLlm: true,
      useRealIntentClassifier: false,
      useRealAnswerGenerator: true
    };
  }
  return {
    ...base,
    useRealEngine: true,
    useRealPgvector: true,
    useRealOllama: false,
    useRealLlm: true,
    useRealIntentClassifier: true,
    useRealAnswerGenerator: true
  };
}

function providerSummary(trace: Record<string, unknown>) {
  const status = trace.provider_status as Record<string, string> | undefined;
  if (!status) return "服务状态未知";
  return `LLM ${status.llm ?? "unknown"} · 回答 ${status.answer_generator ?? "unknown"} · RAG ${status.pgvector ?? "unknown"}/${status.embedding ?? status.embedding_provider ?? status.ollama ?? "unknown"}`;
}

function statusTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "configured") return "success";
  if (status === "config_missing") return "warning";
  if (status === "invalid_config") return "danger";
  if (status === "disabled") return "info";
  return "neutral";
}

function hasMissingProvider(status: ProviderStatus | null) {
  if (!status) return true;
  return ["pgvector", "embedding", "llm"].some((name) => status.providers[name]?.status !== "configured");
}
