import { useEffect, useMemo, useState } from "react";

import { getShop, getShops, Shop, ShopDetail } from "../api/shops";
import { DataTable } from "../components/DataTable";
import { DrawerPanel } from "../components/DrawerPanel";
import { StatusBadge } from "../components/StatusBadge";

type LoadState = "idle" | "loading" | "loaded" | "error";

function renderRecord(record: Record<string, boolean | string | number>) {
  const entries = Object.entries(record);
  if (entries.length === 0) return <span className="muted">暂无数据</span>;
  return (
    <dl className="kv-grid">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Shops() {
  const [shops, setShops] = useState<Shop[]>([]);
  const [selected, setSelected] = useState<ShopDetail | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [listState, setListState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [accountStatus, setAccountStatus] = useState("");
  const [websocketStatus, setWebsocketStatus] = useState("");
  const [internalEnabled, setInternalEnabled] = useState("");

  useEffect(() => {
    setListState("loading");
    getShops()
      .then((data) => {
        setShops(data.items);
        setWarning(data.warning ?? null);
        setError(null);
        setListState("loaded");
        if (data.items[0]) {
          void loadShopDetail(data.items[0].shop_id);
        }
      })
      .catch((err: Error) => {
        setError(err.message);
        setListState("error");
      });
  }, []);

  function loadShopDetail(shopId: string) {
    setDetailState("loading");
    setDetailError(null);
    getShop(shopId)
      .then((data) => {
        setSelected(data);
        setDetailState("loaded");
      })
      .catch((err: Error) => {
        setSelected(null);
        setDetailError(err.message);
        setDetailState("error");
      });
  }

  const filteredShops = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return shops.filter((shop) => {
      const matchesSearch = !needle || shop.shop_id.toLowerCase().includes(needle) || shop.shop_name.toLowerCase().includes(needle);
      const matchesAccount = !accountStatus || shop.account_status === accountStatus;
      const matchesWebsocket = !websocketStatus || shop.websocket_status === websocketStatus;
      const matchesInternal = !internalEnabled || String(shop.internal_enabled) === internalEnabled;
      return matchesSearch && matchesAccount && matchesWebsocket && matchesInternal;
    });
  }, [accountStatus, internalEnabled, search, shops, websocketStatus]);

  const accountOptions = Array.from(new Set(shops.map((shop) => shop.account_status))).filter(Boolean);
  const websocketOptions = Array.from(new Set(shops.map((shop) => shop.websocket_status))).filter(Boolean);

  return (
    <div className="content-grid detail-layout">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>店铺管理</h2>
            <p className="muted">
              用于查看已有店铺、AI 配置、商品数量和运行状态。当前不是完整新店接入流程，新增店铺接入流程将在后续版本提供。
            </p>
          </div>
          <div className="filters filter-grid">
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索 shop_id / 店铺名称" />
            <select value={accountStatus} onChange={(event) => setAccountStatus(event.target.value)}>
              <option value="">全部账号状态</option>
              {accountOptions.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <select value={websocketStatus} onChange={(event) => setWebsocketStatus(event.target.value)}>
              <option value="">全部 WebSocket 状态</option>
              {websocketOptions.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <select value={internalEnabled} onChange={(event) => setInternalEnabled(event.target.value)}>
              <option value="">全部 AI 状态</option>
              <option value="true">InternalEngine 已启用</option>
              <option value="false">InternalEngine 未启用</option>
            </select>
          </div>
        </div>

        {warning ? <div className="warning-banner">接口提醒：{warning}</div> : null}
        {listState === "loading" ? <div className="state-card">正在加载店铺...</div> : null}
        {listState === "error" ? <div className="state-card error-state">加载店铺失败：{error}</div> : null}
        {listState !== "loading" && listState !== "error" ? (
          <DataTable<Shop>
            rows={filteredShops}
            emptyMessage="当前筛选条件下没有店铺。"
            onRowClick={(shop) => loadShopDetail(shop.shop_id)}
            columns={[
              { key: "shop_id", label: "店铺ID shop_id" },
              { key: "shop_name", label: "店铺名称" },
              { key: "channel", label: "渠道" },
              { key: "internal_enabled", label: "InternalEngine", render: (row) => <StatusBadge tone={row.internal_enabled ? "success" : "neutral"}>{row.internal_enabled}</StatusBadge> },
              { key: "rag_enabled", label: "RAG", render: (row) => <StatusBadge tone={row.rag_enabled ? "success" : "neutral"}>{row.rag_enabled}</StatusBadge> },
              { key: "llm_enabled", label: "LLM", render: (row) => <StatusBadge tone={row.llm_enabled ? "success" : "neutral"}>{row.llm_enabled}</StatusBadge> },
              { key: "account_status", label: "账号状态", render: (row) => <StatusBadge tone={row.account_status === "active" ? "success" : "neutral"}>{row.account_status}</StatusBadge> },
              { key: "websocket_status", label: "WebSocket 状态" },
              { key: "no_send", label: "不发送模式", render: (row) => <StatusBadge tone="info">{row.no_send}</StatusBadge> },
              { key: "last_activity", label: "最近活动" }
            ]}
          />
        ) : null}
      </section>

      <DrawerPanel title="店铺详情">
        {detailState === "loading" ? <div className="state-card">正在加载店铺详情...</div> : null}
        {detailState === "error" ? <div className="state-card error-state">加载店铺详情失败：{detailError}</div> : null}
        {selected && detailState !== "loading" ? (
          <div className="detail-stack">
            {selected.warning ? <div className="warning-banner">详情提醒：{selected.warning}</div> : null}
            <strong>{selected.shop_name}</strong>
            <span>shop_id: {selected.shop_id}</span>
            <span>渠道：{selected.channel}</span>
            <span>商品知识数量：{selected.product_knowledge_count}</span>
            <section>
              <h4>InternalEngine 摘要</h4>
              {renderRecord(selected.internal_engine_summary)}
            </section>
            <section>
              <h4>SOP 覆盖</h4>
              {renderRecord(selected.sop_coverage)}
            </section>
            <section>
              <h4>RAG 索引状态</h4>
              {renderRecord(selected.rag_index_status)}
            </section>
            <section>
              <h4>近期调试摘要</h4>
              {renderRecord(selected.recent_trace_summary)}
            </section>
          </div>
        ) : null}
        {!selected && detailState === "idle" ? <div className="state-card">请选择一个店铺查看详情。</div> : null}
      </DrawerPanel>
    </div>
  );
}
