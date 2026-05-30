import { useEffect, useMemo, useState } from "react";

import {
  getShop,
  getShops,
  getWorkerCommands,
  requestWorkerRestart,
  requestWorkerStart,
  requestWorkerStop,
  Shop,
  ShopDetail,
  WorkerCommand
} from "../api/shops";
import { DataTable } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";

type LoadState = "idle" | "loading" | "loaded" | "error";
type WorkerAction = "start" | "stop" | "restart";

const COMMAND_LABELS: Record<WorkerAction, string> = {
  start: "启动",
  stop: "停止",
  restart: "重启"
};

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
  const [workerCommands, setWorkerCommands] = useState<WorkerCommand[]>([]);
  const [warning, setWarning] = useState<string | null>(null);
  const [listState, setListState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [workerCommandState, setWorkerCommandState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [workerCommandError, setWorkerCommandError] = useState<string | null>(null);
  const [workerCommandMessage, setWorkerCommandMessage] = useState<string | null>(null);
  const [workerAction, setWorkerAction] = useState<WorkerAction | null>(null);
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

  function loadWorkerCommands(shopId: string) {
    setWorkerCommandState("loading");
    setWorkerCommandError(null);
    getWorkerCommands(shopId)
      .then((data) => {
        setWorkerCommands(data.items);
        setWorkerCommandState("loaded");
      })
      .catch((err: Error) => {
        setWorkerCommands([]);
        setWorkerCommandError(err.message);
        setWorkerCommandState("error");
      });
  }

  function loadShopDetail(shopId: string) {
    setDetailState("loading");
    setDetailError(null);
    getShop(shopId)
      .then((data) => {
        setSelected(data);
        setDetailState("loaded");
        loadWorkerCommands(shopId);
      })
      .catch((err: Error) => {
        setSelected(null);
        setWorkerCommands([]);
        setDetailError(err.message);
        setDetailState("error");
      });
  }

  function submitWorkerAction(action: WorkerAction) {
    if (!selected) return;
    setWorkerAction(action);
    setWorkerCommandError(null);
    setWorkerCommandMessage(null);
    const payload = {
      operator: "local_admin",
      reason: `web_admin_${action}`
    };
    const request =
      action === "start"
        ? requestWorkerStart
        : action === "stop"
          ? requestWorkerStop
          : requestWorkerRestart;

    request(selected.shop_id, payload)
      .then((command) => {
        setWorkerCommandMessage(
          `已记录 ${COMMAND_LABELS[action]} Worker 指令，command_id=${command.id}。Worker Manager 会读取并执行，Web API 不直接启动子进程。`
        );
        loadWorkerCommands(selected.shop_id);
      })
      .catch((err: Error) => {
        setWorkerCommandError(err.message);
      })
      .finally(() => {
        setWorkerAction(null);
      });
  }

  const filteredShops = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return shops.filter((shop) => {
      const matchesSearch =
        !needle ||
        shop.shop_id.toLowerCase().includes(needle) ||
        shop.shop_name.toLowerCase().includes(needle);
      const matchesAccount = !accountStatus || shop.account_status === accountStatus;
      const matchesWebsocket = !websocketStatus || shop.websocket_status === websocketStatus;
      const matchesInternal = !internalEnabled || String(shop.internal_enabled) === internalEnabled;
      return matchesSearch && matchesAccount && matchesWebsocket && matchesInternal;
    });
  }, [accountStatus, internalEnabled, search, shops, websocketStatus]);

  const accountOptions = Array.from(new Set(shops.map((shop) => shop.account_status))).filter(Boolean);
  const websocketOptions = Array.from(new Set(shops.map((shop) => shop.websocket_status))).filter(Boolean);
  const workerButtonsDisabled = !selected || workerAction !== null;

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>店铺管理</h2>
            <p className="muted">
              查看已接入店铺、AI 配置、商品知识数量和运行状态。Worker 启停在这里下发控制指令，由服务器上的 Worker Manager 执行。
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
              { key: "shop_id", label: "店铺 ID" },
              { key: "shop_name", label: "店铺名称" },
              { key: "channel", label: "渠道" },
              { key: "internal_enabled", label: "InternalEngine", render: (row) => <StatusBadge tone={row.internal_enabled ? "success" : "neutral"}>{row.internal_enabled}</StatusBadge> },
              { key: "rag_enabled", label: "RAG", render: (row) => <StatusBadge tone={row.rag_enabled ? "success" : "neutral"}>{row.rag_enabled}</StatusBadge> },
              { key: "llm_enabled", label: "LLM", render: (row) => <StatusBadge tone={row.llm_enabled ? "success" : "neutral"}>{row.llm_enabled}</StatusBadge> },
              { key: "account_status", label: "账号状态", render: (row) => <StatusBadge tone={row.account_status === "active" ? "success" : "neutral"}>{row.account_status}</StatusBadge> },
              { key: "websocket_status", label: "WebSocket" },
              { key: "no_send", label: "no-send", render: (row) => <StatusBadge tone="info">{row.no_send}</StatusBadge> },
              { key: "last_activity", label: "最近活动" }
            ]}
          />
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>店铺详情</h3>
            <p className="muted">选择店铺后查看配置、Worker 控制指令、知识覆盖和调试摘要。</p>
          </div>
        </div>
        {detailState === "loading" ? <div className="state-card">正在加载店铺详情...</div> : null}
        {detailState === "error" ? <div className="state-card error-state">加载店铺详情失败：{detailError}</div> : null}
        {selected && detailState !== "loading" ? (
          <div className="detail-stack">
            {selected.warning ? <div className="warning-banner">详情提醒：{selected.warning}</div> : null}
            <div className="shop-detail-summary">
              <div>
                <span className="muted">店铺名称</span>
                <strong>{selected.shop_name}</strong>
              </div>
              <div>
                <span className="muted">shop_id</span>
                <strong>{selected.shop_id}</strong>
              </div>
              <div>
                <span className="muted">渠道</span>
                <strong>{selected.channel}</strong>
              </div>
              <div>
                <span className="muted">商品知识数量</span>
                <strong>{selected.product_knowledge_count}</strong>
              </div>
            </div>

            <section className="worker-control-panel">
              <h4>Worker 控制</h4>
              <p className="muted">
                这里仅写入启动、停止或重启指令；Worker Manager 读取指令后执行。未绑定真实店铺或授权无效时，后端会阻断启动。
              </p>
              {workerCommandMessage ? <div className="state-card">{workerCommandMessage}</div> : null}
              {workerCommandError ? <div className="warning-banner error-state">{workerCommandError}</div> : null}
              <div className="button-row">
                <button disabled={workerButtonsDisabled} onClick={() => submitWorkerAction("start")}>
                  {workerAction === "start" ? "正在记录..." : "请求启动 Worker"}
                </button>
                <button disabled={workerButtonsDisabled} onClick={() => submitWorkerAction("stop")}>
                  {workerAction === "stop" ? "正在记录..." : "请求停止 Worker"}
                </button>
                <button disabled={workerButtonsDisabled} onClick={() => submitWorkerAction("restart")}>
                  {workerAction === "restart" ? "正在记录..." : "请求重启 Worker"}
                </button>
                <button disabled={!selected || workerCommandState === "loading"} onClick={() => loadWorkerCommands(selected.shop_id)}>
                  刷新命令
                </button>
              </div>
              {workerCommandState === "loading" ? <div className="state-card">正在加载 Worker 指令...</div> : null}
              {workerCommands.length === 0 && workerCommandState !== "loading" ? (
                <div className="state-card">暂无 Worker 控制指令。</div>
              ) : null}
              {workerCommands.length > 0 ? (
                <div className="worker-command-list">
                  {workerCommands.map((command) => (
                    <article className="worker-command-card" key={command.id}>
                      <div className="worker-command-card-main">
                        <strong>{COMMAND_LABELS[command.command] ?? command.command} Worker</strong>
                        <StatusBadge tone={command.status === "succeeded" ? "success" : command.status === "failed" ? "danger" : "warning"}>{command.status}</StatusBadge>
                      </div>
                      <dl>
                        <div>
                          <dt>操作人</dt>
                          <dd>{command.requested_by || "-"}</dd>
                        </div>
                        <div>
                          <dt>请求时间</dt>
                          <dd>{command.requested_at}</dd>
                        </div>
                        <div>
                          <dt>trace_id</dt>
                          <dd>{command.trace_id}</dd>
                        </div>
                        {command.error_summary ? (
                          <div>
                            <dt>错误摘要</dt>
                            <dd>{command.error_summary}</dd>
                          </div>
                        ) : null}
                      </dl>
                    </article>
                  ))}
                </div>
              ) : null}
            </section>

            <div className="shop-detail-grid">
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
          </div>
        ) : null}
        {!selected && detailState === "idle" ? <div className="state-card">请选择一个店铺查看详情。</div> : null}
      </section>
    </div>
  );
}
