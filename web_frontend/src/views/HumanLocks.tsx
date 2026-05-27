import { useCallback, useEffect, useMemo, useState } from "react";

import { bulkUnlockHumanLocks, HumanLockItem, listHumanLocks, unlockHumanLock, unlockHumanLocksBySession } from "../api/humanLocks";
import { getShops, Shop } from "../api/shops";
import { DataTable } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";

const DEFAULT_REASON = "manual_unlock_after_review";

export function HumanLocks() {
  const [shops, setShops] = useState<Shop[]>([]);
  const [selectedShopId, setSelectedShopId] = useState("");
  const [buyerId, setBuyerId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [reason, setReason] = useState(DEFAULT_REASON);
  const [locks, setLocks] = useState<HumanLockItem[]>([]);
  const [total, setTotal] = useState(0);
  const [warning, setWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);

  useEffect(() => {
    getShops()
      .then((data) => {
        setShops(data.items);
        if (data.items[0]) setSelectedShopId(data.items[0].shop_id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "店铺列表加载失败"));
  }, []);

  const selectedShop = useMemo(
    () => shops.find((shop) => shop.shop_id === selectedShopId),
    [shops, selectedShopId]
  );

  const loadLocks = useCallback(async () => {
    if (!selectedShopId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listHumanLocks({
        shop_id: selectedShopId,
        buyer_id: buyerId.trim() || undefined,
        session_id: sessionId.trim() || undefined,
        status: "pending_human",
        limit: 100
      });
      setLocks(data.items);
      setTotal(data.total);
      setWarning(data.warning ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "人工锁加载失败");
    } finally {
      setLoading(false);
    }
  }, [buyerId, selectedShopId, sessionId]);

  useEffect(() => {
    void loadLocks();
  }, [loadLocks]);

  async function handleUnlock(lock: HumanLockItem) {
    if (!selectedShopId) return;
    const ok = window.confirm(
      `解除人工锁后，该会话后续可能重新由 AI 自动回复。此操作不会发送消息给买家。\n\n只会解除当前店铺 shop_id=${selectedShopId} 的这条人工锁，不会影响其他店铺。`
    );
    if (!ok) return;
    try {
      const result = await unlockHumanLock(lock.id, {
        shop_id: selectedShopId,
        operator: "local_admin",
        reason: reason.trim() || DEFAULT_REASON
      });
      setLastResult(result.already_unlocked ? `人工锁 ${result.id} 已经是解除状态。` : `已解除人工锁 ${result.id}。`);
      await loadLocks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "解除人工锁失败");
    }
  }

  async function handleUnlockBySession() {
    if (!selectedShopId || (!buyerId.trim() && !sessionId.trim())) {
      setError("按会话解除时必须填写 buyer_id 或 session_id。");
      return;
    }
    const ok = window.confirm(`只会解除当前店铺 shop_id=${selectedShopId} 中匹配 buyer_id/session_id 的人工锁，不会影响其他店铺。`);
    if (!ok) return;
    try {
      const result = await unlockHumanLocksBySession({
        shop_id: selectedShopId,
        buyer_id: buyerId.trim() || undefined,
        session_id: sessionId.trim() || undefined,
        operator: "local_admin",
        reason: reason.trim() || DEFAULT_REASON
      });
      setLastResult(`匹配 ${result.matched_count} 条，解除 ${result.unlocked_count} 条。`);
      await loadLocks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "按会话解除失败");
    }
  }

  async function handleBulkUnlock() {
    if (!selectedShopId) return;
    const ok = window.confirm(`只会解除当前店铺 shop_id=${selectedShopId} 的人工锁，不会影响其他店铺。`);
    if (!ok) return;
    try {
      const result = await bulkUnlockHumanLocks({
        shop_id: selectedShopId,
        operator: "local_admin",
        reason: reason.trim() || "bulk_unlock_after_deploy",
        limit: 100
      });
      setLastResult(`批量匹配 ${result.matched_count} 条，解除 ${result.unlocked_count} 条。`);
      await loadLocks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量解除失败");
    }
  }

  return (
    <div className="page-stack">
      <section className="panel human-locks-panel">
        <div className="panel-header">
          <div>
            <h2>人工锁管理</h2>
            <p className="muted">
              人工锁表示该会话已转人工，AI 不会自动继续回复。解除人工锁只影响当前店铺，不会发送 PDD 消息。
            </p>
          </div>
          <StatusBadge tone="warning">PDD 真实发送已关闭</StatusBadge>
        </div>
        <div className="warning-banner">
          解除操作只修改本地 pending_human 状态，不调用 LLM/Ollama/pgvector，也不会向买家发送消息。批量解除必须先确认当前店铺。
        </div>
        <div className="human-lock-controls">
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
            buyer_id
            <input value={buyerId} onChange={(event) => setBuyerId(event.target.value)} placeholder="可选：买家ID" />
          </label>
          <label>
            session_id
            <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} placeholder="可选：会话ID" />
          </label>
          <label>
            操作原因 reason
            <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={DEFAULT_REASON} />
          </label>
        </div>
        <div className="button-row">
          <button onClick={() => void loadLocks()} disabled={!selectedShopId || loading}>
            {loading ? "加载中..." : "刷新"}
          </button>
          <button onClick={() => void handleUnlockBySession()} disabled={!selectedShopId || (!buyerId.trim() && !sessionId.trim())}>
            按会话解除
          </button>
          <button onClick={() => void handleBulkUnlock()} disabled={!selectedShopId || locks.length === 0}>
            批量解除当前店铺
          </button>
        </div>
        {selectedShop ? (
          <div className="state-card">
            当前店铺：{selectedShop.shop_name} ({selectedShop.shop_id}) · 人工锁数量：{total}
          </div>
        ) : (
          <div className="state-card">请先选择店铺再查询人工锁。</div>
        )}
        {warning ? <div className="warning-banner">{warning}</div> : null}
        {error ? <div className="warning-banner error-state">{error}</div> : null}
        {lastResult ? <div className="state-card">{lastResult}</div> : null}
      </section>

      <section className="panel human-locks-table-panel">
        <div className="table-scroll">
          <DataTable<HumanLockItem>
            rows={locks}
            emptyMessage={loading ? "正在加载人工锁..." : "当前店铺没有人工接管中的会话"}
            columns={[
              { key: "shop_id", label: "店铺ID" },
              { key: "buyer_id", label: "买家ID" },
              { key: "session_id", label: "会话ID" },
              { key: "status", label: "状态", render: (row) => <StatusBadge tone="warning">{row.status}</StatusBadge> },
              { key: "source", label: "来源" },
              { key: "intent", label: "意图" },
              { key: "reason", label: "原因" },
              { key: "last_message_preview", label: "最近消息预览" },
              { key: "trace_id", label: "trace_id" },
              { key: "locked_at", label: "锁定时间" },
              { key: "updated_at", label: "更新时间" },
              {
                key: "actions",
                label: "操作",
                render: (row) => (
                  <button className="compact-button" disabled={!row.can_unlock} onClick={() => void handleUnlock(row)}>
                    解除
                  </button>
                )
              }
            ]}
          />
        </div>
      </section>
    </div>
  );
}
