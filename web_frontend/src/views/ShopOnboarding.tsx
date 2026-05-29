import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  AiStatus,
  bindShopIdentity,
  cancelOnboardingSession,
  checkRemoteBrowserLogin,
  createOnboardingSession,
  disableAi,
  enableAi,
  getAiStatus,
  getLatestOnboardingSession,
  getOnboardingChecklist,
  getOnboardingSession,
  getWorkerStatus,
  markNoSendValidationPassed,
  OnboardingChecklist,
  OnboardingSession,
  WorkerStatus
} from "../api/shopOnboarding";
import {
  createProductSyncJob,
  getProductSyncCoverage,
  getProductSyncJob,
  listProductSyncJobs,
  ProductSyncCoverage,
  ProductSyncJob,
  retryProductSyncJob
} from "../api/productSync";
import { StatusBadge } from "../components/StatusBadge";

const ONBOARDING_STORAGE_KEY = "web_admin_shop_onboarding_state";

type SavedOnboardingState = {
  sessionId?: string;
  shopId?: string;
  syncJobId?: string;
  shopName?: string;
  accountName?: string;
};

const terminalStatuses = new Set([
  "succeeded",
  "shop_identity_pending",
  "failed",
  "expired",
  "cancelled",
  "blocked_complex_verification"
]);

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    created: "已创建",
    opening_login_page: "正在打开登录页",
    waiting_account: "等待账号信息",
    waiting_sms_code: "等待短信验证码",
    waiting_captcha: "等待图形验证码",
    logging_in: "登录中",
    waiting_user_verification: "等待远程浏览器验证",
    succeeded: "登录成功",
    shop_identity_pending: "授权成功，店铺身份待绑定",
    failed: "登录失败",
    expired: "已过期",
    cancelled: "已取消",
    blocked_complex_verification: "需要复杂验证"
  };
  return labels[status] ?? status;
}

function stepLabel(step: string) {
  const labels: Record<string, string> = {
    created: "创建会话",
    waiting_user_verification: "远程浏览器验证",
    succeeded: "授权成功",
    shop_identity_pending: "店铺身份待绑定",
    failed: "失败",
    expired: "过期",
    cancelled: "取消",
    blocked_complex_verification: "复杂验证"
  };
  return labels[step] ?? step;
}

function checklistTone(status: string) {
  if (status === "passed") return "success";
  if (status === "failed") return "danger";
  if (status === "warning") return "warning";
  return "info";
}

function checklistLabel(status: string) {
  const labels: Record<string, string> = {
    passed: "通过",
    failed: "未通过",
    warning: "警告",
    skipped: "跳过"
  };
  return labels[status] ?? status;
}

function workerConsistencyLabel(status?: string) {
  const labels: Record<string, string> = {
    ai_enabled_worker_running: "AI 已启用，Worker 正在运行",
    ai_enabled_worker_not_running: "AI 已启用，但 Worker 未运行",
    ai_disabled_worker_still_running: "AI 已关闭，但 Worker 仍显示运行",
    ai_disabled_worker_stopped: "AI 已关闭，Worker 未运行",
    worker_status_missing: "Worker 状态文件缺失",
    worker_status_invalid: "Worker 状态文件无效",
    worker_status_stale: "Worker 状态已过期",
    worker_status_unknown: "Worker 状态未知"
  };
  return labels[status || ""] ?? (status || "未知");
}

function workerConsistencyTone(status?: string) {
  if (status === "ai_enabled_worker_running" || status === "ai_disabled_worker_stopped") return "success";
  if (status?.includes("not_running") || status?.includes("still_running") || status?.includes("stale")) return "warning";
  return "info";
}

function productSyncTone(status?: string): "success" | "warning" | "danger" | "info" {
  if (status === "succeeded") return "success";
  if (status === "partial_failed") return "warning";
  if (status === "failed" || status === "cancelled") return "danger";
  return "info";
}

function productSyncLabel(status?: string) {
  const labels: Record<string, string> = {
    pending: "等待中",
    running: "同步中",
    succeeded: "同步成功",
    partial_failed: "部分失败",
    failed: "同步失败",
    cancelled: "已取消"
  };
  return labels[status || ""] ?? (status || "未知");
}

function productSyncNextAction(errorSummary?: string | null) {
  const text = (errorSummary || "").toLowerCase();
  if (!text) return "请刷新同步状态；如果仍失败，保留当前页面错误和后台日志 trace_id。";
  if (text.includes("auth_required") || text.includes("auth_invalid")) {
    return "请重新完成店铺登录授权，再重新同步商品。";
  }
  if (text.includes("anti") || text.includes("403") || text.includes("401")) {
    return "PDD 商品接口拒绝了当前授权请求，请重新登录授权后再试；如果仍失败，需要补充浏览器侧商品同步通道。";
  }
  if (text.includes("product_list_parse_empty")) {
    return "PDD 返回了商品总数，但当前解析器没有识别商品列表字段；请保留该错误，开发需要按返回结构补充解析规则。";
  }
  return "请先点击“刷新同步状态”，仍失败时重新登录授权后再同步。";
}

function loadSavedOnboardingState(): SavedOnboardingState | null {
  try {
    const raw = window.localStorage.getItem(ONBOARDING_STORAGE_KEY);
    return raw ? JSON.parse(raw) as SavedOnboardingState : null;
  } catch {
    return null;
  }
}

function saveOnboardingState(state: SavedOnboardingState) {
  try {
    const hasValue = Object.values(state).some((value) => Boolean(value));
    if (!hasValue) {
      window.localStorage.removeItem(ONBOARDING_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // localStorage is best-effort only; API state remains the source of truth.
  }
}

function clearSavedOnboardingState() {
  try {
    window.localStorage.removeItem(ONBOARDING_STORAGE_KEY);
  } catch {
    // ignore browser storage errors
  }
}

function isBusinessShopId(shopId?: string | null) {
  return Boolean(shopId && !shopId.startsWith("remote-"));
}

export function ShopOnboarding() {
  const [shopName, setShopName] = useState("");
  const [accountName, setAccountName] = useState("");
  const [session, setSession] = useState<OnboardingSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncJob, setSyncJob] = useState<ProductSyncJob | null>(null);
  const [coverage, setCoverage] = useState<ProductSyncCoverage | null>(null);
  const [checklist, setChecklist] = useState<OnboardingChecklist | null>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus | null>(null);
  const [validationSummary, setValidationSummary] = useState("已在试聊调试中测试价格、规格、用法、物流、售后、敏感问题和转人工。");
  const [overrideReason, setOverrideReason] = useState("");
  const [disableReason, setDisableReason] = useState("manual_disable");
  const [mallIdInput, setMallIdInput] = useState("");
  const [stateLoaded, setStateLoaded] = useState(false);

  const currentStep = useMemo(() => {
    if (!session) return 1;
    if (aiStatus?.ai_enabled) return 6;
    if (session.status === "succeeded") return syncJob ? 5 : 3;
    if (session.status === "shop_identity_pending" || session.real_shop_id_pending) return 2;
    return 2;
  }, [aiStatus?.ai_enabled, session, syncJob]);

  const activeShopId = session?.shop_id || "";
  const shopIdentityPending = Boolean(
    session?.status === "shop_identity_pending" ||
      session?.real_shop_id_pending ||
      session?.shop_identity_status === "pending_real_shop_id" ||
      (session?.shop_id || "").startsWith("remote-")
  );
  const businessShopIdReady = Boolean(isBusinessShopId(activeShopId) && !shopIdentityPending);
  const shopIdentityBlockReason =
    "授权已完成，但系统尚未绑定真实 PDD 店铺 ID/mall_id。为避免把 remote-* 临时会话 ID 写入正式数据，商品同步、知识发布、启用 AI 和 worker 启用已被阻断。请先完成真实店铺身份绑定。";

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const saved = loadSavedOnboardingState();
      setShopName(saved?.shopName || "");
      setAccountName(saved?.accountName || "");
      try {
        let restoredSession: OnboardingSession | null = null;
        if (saved?.sessionId) {
          try {
            restoredSession = await getOnboardingSession(saved.sessionId);
          } catch {
            restoredSession = null;
          }
        }
        if (!restoredSession) {
          try {
            restoredSession = await getLatestOnboardingSession();
          } catch {
            restoredSession = null;
          }
        }
        if (restoredSession) {
          if (!cancelled) setSession(restoredSession);
          if (!saved?.shopName && restoredSession.shop_name) setShopName(restoredSession.shop_name);
        }

        const restoredShopId = restoredSession?.shop_id || saved?.shopId || "";
        if (isBusinessShopId(restoredShopId)) {
          const [nextCoverage, jobs, nextChecklist, nextAiStatus, nextWorkerStatus] = await Promise.all([
            getProductSyncCoverage(restoredShopId),
            saved?.syncJobId
              ? getProductSyncJob(restoredShopId, saved.syncJobId).then((job) => [job]).catch(() => listProductSyncJobs(restoredShopId, 1))
              : listProductSyncJobs(restoredShopId, 1),
            getOnboardingChecklist(restoredShopId),
            getAiStatus(restoredShopId),
            getWorkerStatus(restoredShopId)
          ]);
          if (!cancelled) {
            setCoverage(nextCoverage);
            setSyncJob(jobs[0] || null);
            setChecklist(nextChecklist);
            setAiStatus(nextAiStatus);
            setWorkerStatus(nextWorkerStatus);
          }
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "恢复店铺接入流程失败");
      } finally {
        if (!cancelled) setStateLoaded(true);
      }
    }

    restore();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!stateLoaded) return;
    saveOnboardingState({
      sessionId: session?.session_id,
      shopId: isBusinessShopId(session?.shop_id) ? session?.shop_id || undefined : undefined,
      syncJobId: syncJob?.id,
      shopName,
      accountName
    });
  }, [accountName, session?.session_id, session?.shop_id, shopName, stateLoaded, syncJob?.id]);

  useEffect(() => {
    if (!session || terminalStatuses.has(session.status)) {
      setPolling(false);
      return undefined;
    }
    setPolling(true);
    const timer = window.setInterval(async () => {
      try {
        setSession(await getOnboardingSession(session.session_id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "登录状态刷新失败");
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [session]);

  useEffect(() => {
    if (!businessShopIdReady || session?.status !== "succeeded") return;
    refreshReadiness().catch((err) => setError(err instanceof Error ? err.message : "刷新接入验收状态失败"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeShopId, businessShopIdReady, session?.status]);

  async function refreshReadiness() {
    if (!businessShopIdReady) return;
    const [nextChecklist, nextAiStatus, nextWorkerStatus] = await Promise.all([
      getOnboardingChecklist(activeShopId),
      getAiStatus(activeShopId),
      getWorkerStatus(activeShopId)
    ]);
    setChecklist(nextChecklist);
    setAiStatus(nextAiStatus);
    setWorkerStatus(nextWorkerStatus);
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setSyncJob(null);
    setCoverage(null);
    setChecklist(null);
    setAiStatus(null);
    setWorkerStatus(null);
    setMallIdInput("");
    try {
      const created = await createOnboardingSession({
        platform: "pdd",
        shop_name: shopName,
        account_name: accountName,
        runner_mode: "remote_browser",
        operator: "local_admin"
      });
      setSession(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建登录会话失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleCancel() {
    if (!session) return;
    const ok = window.confirm("确定取消当前登录会话吗？取消后会关闭远程浏览器，不会发送 PDD 消息。");
    if (!ok) return;
    setLoading(true);
    try {
      setSession(await cancelOnboardingSession(session.session_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消登录会话失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleClearOnboarding() {
    const ok = window.confirm("确定清空当前店铺接入流程吗？如果远程浏览器登录会话仍在进行，会先取消会话。该操作不会删除店铺授权，也不会发送 PDD 消息。");
    if (!ok) return;
    setLoading(true);
    setError(null);
    try {
      if (session && !terminalStatuses.has(session.status)) {
        await cancelOnboardingSession(session.session_id);
      }
      setSession(null);
      setShopName("");
      setAccountName("");
      setSyncJob(null);
      setCoverage(null);
      setChecklist(null);
      setAiStatus(null);
      setWorkerStatus(null);
      setMallIdInput("");
      setOverrideReason("");
      setDisableReason("manual_disable");
      clearSavedOnboardingState();
    } catch (err) {
      setError(err instanceof Error ? err.message : "清空店铺接入流程失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleCheckRemoteLogin() {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      setSession(await checkRemoteBrowserLogin(session.session_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "检查远程浏览器登录状态失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleBindShopIdentity(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    const mallId = mallIdInput.trim();
    if (!mallId) {
      setError("请输入真实 PDD 店铺 ID / mall_id。");
      return;
    }
    if (!/^\d{4,}$/.test(mallId)) {
      setError("真实 PDD 店铺 ID / mall_id 应为平台提供的数字 ID，不能填写 remote-* 或临时会话 ID。");
      return;
    }
    const ok = window.confirm(
      `确认将当前授权绑定到真实 PDD 店铺 ID / mall_id=${mallId} 吗？绑定后商品同步会写入该店铺数据；本操作不会发送 PDD 消息，不会启用 AI。`
    );
    if (!ok) return;
    setLoading(true);
    setError(null);
    try {
      const bound = await bindShopIdentity(session.session_id, {
        mall_id: mallId,
        shop_name: shopName || session.shop_name || undefined,
        operator: "local_admin"
      });
      setSession(bound);
      setSyncJob(null);
      setCoverage(null);
      setChecklist(null);
      setAiStatus(null);
      setWorkerStatus(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "绑定真实店铺身份失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleStartSync() {
    if (!activeShopId) return;
    setLoading(true);
    setError(null);
    try {
      const job = await createProductSyncJob(activeShopId);
      setSyncJob(job);
      setCoverage(await getProductSyncCoverage(activeShopId));
      await refreshReadiness();
    } catch (err) {
      setError(err instanceof Error ? err.message : "商品同步任务创建失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleRefreshSync() {
    if (!businessShopIdReady || !syncJob) return;
    setLoading(true);
    setError(null);
    try {
      setSyncJob(await getProductSyncJob(activeShopId, syncJob.id));
      setCoverage(await getProductSyncCoverage(activeShopId));
      await refreshReadiness();
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新商品同步状态失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleRetrySync() {
    if (!businessShopIdReady || !syncJob) return;
    setLoading(true);
    setError(null);
    try {
      const job = await retryProductSyncJob(activeShopId, syncJob.id);
      setSyncJob(job);
      setCoverage(await getProductSyncCoverage(activeShopId));
      await refreshReadiness();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重试失败商品失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleMarkValidationPassed() {
    if (!businessShopIdReady) return;
    const ok = window.confirm("确认已经在试聊调试中完成 no-send 验收？此操作只记录验收状态，不会发送 PDD 消息。");
    if (!ok) return;
    setLoading(true);
    setError(null);
    try {
      await markNoSendValidationPassed(activeShopId, validationSummary);
      await refreshReadiness();
    } catch (err) {
      setError(err instanceof Error ? err.message : "标记 no-send 验收失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleEnableAi(override = false) {
    if (!businessShopIdReady) return;
    const message = override
      ? "当前 checklist 未完全通过，确认要强制启用 AI 配置状态吗？此操作不会启动 worker，也不会发送 PDD 消息。"
      : "开启后，系统配置会标记该店铺允许 AI 自动回复。请确认已完成商品同步、知识检查、试聊验证和人工锁管理。此操作不会直接发送 PDD 消息，也不会启动 worker。";
    const ok = window.confirm(message);
    if (!ok) return;
    setLoading(true);
    setError(null);
    try {
      const next = await enableAi(activeShopId, {
        operator: "local_admin",
        confirm: true,
        override,
        override_reason: override ? overrideReason : null
      });
      setAiStatus(next);
      await refreshReadiness();
    } catch (err) {
      setError(err instanceof Error ? err.message : "启用 AI 失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleDisableAi() {
    if (!businessShopIdReady) return;
    const ok = window.confirm("确认关闭该店铺 AI 配置状态？此操作不会停止 worker，只修改后台配置。");
    if (!ok) return;
    setLoading(true);
    setError(null);
    try {
      const next = await disableAi(activeShopId, disableReason || "manual_disable");
      setAiStatus(next);
      await refreshReadiness();
    } catch (err) {
      setError(err instanceof Error ? err.message : "关闭 AI 失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>店铺接入</h2>
            <p className="muted">
              用于在 Web 后台完成 PDD 店铺登录授权。当前统一使用远程浏览器登录，用户在临时浏览器窗口里完成账号密码、短信验证码、滑块、扫码或安全验证。
            </p>
          </div>
          <StatusBadge tone="success">不会发送 PDD 消息</StatusBadge>
        </div>
        <div className="warning-banner">
          系统只保存加密后的授权信息，不保存明文密码，不会启动 worker，也不会启用 AI 自动回复。登录成功后需要继续同步商品、初始化知识并完成 no-send 试聊验收。
        </div>
      </section>

      <section className="panel onboarding-steps">
        {["填写店铺信息", "登录授权", "同步商品", "初始化知识", "接入验收", "启用 AI"].map((label, index) => (
          <div key={label} className={currentStep === index + 1 ? "onboarding-step active" : "onboarding-step"}>
            <span>{index + 1}</span>
            <strong>{label}</strong>
          </div>
        ))}
      </section>

      <div className="content-grid onboarding-grid">
        <section className="panel">
          <h3>1. 填写店铺信息</h3>
          <form className="form-grid" onSubmit={handleCreate}>
            <label>
              平台
              <input value="PDD" disabled />
            </label>
            <label>
              店铺名称
              <input value={shopName} onChange={(event) => setShopName(event.target.value)} required placeholder="例如：美肌萌主驿站" />
            </label>
            <label>
              PDD 账号
              <input value={accountName} onChange={(event) => setAccountName(event.target.value)} required placeholder="用于授权记录脱敏展示" />
            </label>
            <button disabled={loading}>{loading ? "处理中..." : "创建远程浏览器登录会话"}</button>
            <button type="button" className="secondary-button" onClick={handleClearOnboarding} disabled={loading}>
              清空当前接入流程
            </button>
          </form>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h3>2. 登录授权状态</h3>
              <p className="muted">在远程浏览器中完成 PDD 登录后，点击“我已完成登录，检查状态”。</p>
            </div>
            {polling && <StatusBadge tone="info">轮询中</StatusBadge>}
          </div>

          {!session ? (
            <div className="state-card">请先创建登录会话。</div>
          ) : (
            <div className="status-detail-grid">
              <div>
                <span className="muted">会话 ID</span>
                <strong>{session.session_id}</strong>
              </div>
              <div>
                <span className="muted">状态</span>
                <strong>{statusLabel(session.status)} {session.status}</strong>
              </div>
              <div>
                <span className="muted">步骤</span>
                <strong>{stepLabel(session.step)} {session.step}</strong>
              </div>
              <div>
                <span className="muted">登录方式</span>
                <strong>远程浏览器登录 remote_browser</strong>
              </div>
              <div>
                <span className="muted">账号</span>
                <strong>{session.safe_display || "-"}</strong>
              </div>
              <div>
                <span className="muted">店铺 ID</span>
                <strong>
                  {shopIdentityPending
                    ? "待绑定真实 PDD 店铺 ID"
                    : session.shop_id || "登录成功后绑定"}
                </strong>
              </div>
              <div>
                <span className="muted">过期时间</span>
                <strong>{session.expires_at}</strong>
              </div>
            </div>
          )}

          {shopIdentityPending && (
            <>
              <div className="warning-banner error-state">
                <strong>店铺身份待绑定：</strong>
                {shopIdentityBlockReason}
              </div>
              <form className="identity-bind-form" onSubmit={handleBindShopIdentity}>
                <label>
                  真实 PDD 店铺 ID / mall_id
                  <input
                    value={mallIdInput}
                    onChange={(event) => setMallIdInput(event.target.value)}
                    placeholder="请输入 PDD 商家后台中的真实数字店铺 ID"
                    inputMode="numeric"
                  />
                </label>
                <button type="submit" disabled={loading || !mallIdInput.trim()}>
                  绑定真实店铺身份
                </button>
                <p className="muted">
                  绑定只会把当前加密授权关联到真实店铺 ID，不会发送 PDD 消息、不会启动 worker、不会启用 AI。绑定完成后才允许商品同步写入正式数据。
                </p>
              </form>
            </>
          )}

          {session?.runner_mode === "remote_browser" && (
            <div className="remote-browser-panel">
              <div className="panel-header">
                <div>
                  <h4>远程浏览器</h4>
                  <p className="muted">
                    该窗口仅限当前登录会话访问。请在窗口内完成 PDD 登录和平台验证；系统不会记录你的键盘输入。
                  </p>
                </div>
                <StatusBadge tone={session.vnc_url_ready || session.status === "succeeded" || shopIdentityPending ? "success" : "warning"}>
                  {session.remote_browser_status || "not_ready"}
                </StatusBadge>
              </div>
              {session.status === "succeeded" ? (
                <div className="state-card">登录授权已完成，远程浏览器会话已关闭。</div>
              ) : shopIdentityPending ? (
                <div className="state-card">
                  登录授权已完成，远程浏览器会话已关闭；但尚未识别真实 PDD 店铺 ID，正式业务操作已被阻断。
                </div>
              ) : session.vnc_url_ready && session.vnc_url ? (
                <iframe className="remote-browser-frame" src={session.vnc_url} title="PDD 远程浏览器登录" />
              ) : session.status === "expired" ? (
                <div className="warning-banner">登录会话已过期，请重新创建登录会话。</div>
              ) : (
                <div className="warning-banner">
                  远程浏览器暂不可用：{session.error_summary || "noVNC 依赖或地址未配置"}。请确认服务器已配置 noVNC/websockify，并设置 WEB_NOVNC_BASE_URL。
                </div>
              )}
              {session.status !== "succeeded" && !shopIdentityPending && session.status !== "expired" && (
                <div className="inline-form">
                  <button type="button" disabled={loading} onClick={handleCheckRemoteLogin}>
                    我已完成登录，检查状态
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => session && getOnboardingSession(session.session_id).then(setSession).catch((err) => setError(err instanceof Error ? err.message : "刷新远程浏览器状态失败"))}
                  >
                    刷新远程浏览器状态
                  </button>
                </div>
              )}
            </div>
          )}

          {session?.status === "succeeded" && (
            <div className="state-card">
              登录授权已完成。当前尚未同步商品，也未启用 AI 自动回复。
            </div>
          )}

          {session && !terminalStatuses.has(session.status) && (
            <button type="button" onClick={handleCancel} disabled={loading}>
              取消登录
            </button>
          )}
          {error && <div className="warning-banner error-state">{error}</div>}
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>3. 同步商品</h3>
            <p className="muted">登录授权成功后，可用加密授权读取 PDD 商品列表和详情，写入本地 product_knowledge。不会发送 PDD 消息。</p>
          </div>
          {syncJob && <StatusBadge tone={productSyncTone(syncJob.status)}>{`${productSyncLabel(syncJob.status)} ${syncJob.status}`}</StatusBadge>}
        </div>
        {shopIdentityPending ? (
          <div className="warning-banner error-state">
            <strong>暂不能同步商品：</strong>
            {shopIdentityBlockReason}
          </div>
        ) : session?.status !== "succeeded" ? (
          <div className="state-card">请先完成登录授权。</div>
        ) : (
          <>
            <div className="inline-form">
              <button type="button" onClick={handleStartSync} disabled={loading || !businessShopIdReady}>
                开始全量同步商品
              </button>
              {syncJob && (
                <>
                  <button type="button" onClick={handleRefreshSync} disabled={loading}>刷新同步状态</button>
                  <button type="button" onClick={handleRetrySync} disabled={loading || syncJob.failed_count === 0}>重试失败商品</button>
                </>
              )}
            </div>
            {coverage?.warning === "pending_real_shop_id" && (
              <div className="warning-banner">当前仍是临时店铺 ID，后续会通过商品/店铺只读接口继续完善真实 mall_id 识别。</div>
            )}
            {syncJob && (
              <div className="stats-grid">
                <div className="stat-card"><span>总数</span><strong>{syncJob.total_count}</strong></div>
                <div className="stat-card"><span>成功</span><strong>{syncJob.succeeded_count}</strong></div>
                <div className="stat-card"><span>失败</span><strong>{syncJob.failed_count}</strong></div>
                <div className="stat-card"><span>跳过</span><strong>{syncJob.skipped_count}</strong></div>
              </div>
            )}
            {syncJob?.error_summary && syncJob.status !== "succeeded" && (
              <div className="warning-banner error-state">
                <strong>商品同步失败原因：</strong>
                {syncJob.error_summary}
                <p className="muted">建议处理：{productSyncNextAction(syncJob.error_summary)}</p>
              </div>
            )}
            {coverage && (
              <div className="stats-grid">
                <div className="stat-card"><span>商品总数</span><strong>{coverage.total}</strong></div>
                <div className="stat-card"><span>价格覆盖</span><strong>{coverage.has_price}</strong></div>
                <div className="stat-card"><span>规格覆盖</span><strong>{coverage.has_specs}</strong></div>
                <div className="stat-card"><span>用法覆盖</span><strong>{coverage.has_usage}</strong></div>
              </div>
            )}
            {syncJob?.items && syncJob.items.some((item) => item.status === "failed") && (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>商品 ID</th>
                    <th>商品名</th>
                    <th>状态</th>
                    <th>错误</th>
                  </tr>
                </thead>
                <tbody>
                  {syncJob.items.filter((item) => item.status === "failed").map((item) => (
                    <tr key={item.id}>
                      <td>{item.goods_id}</td>
                      <td>{item.goods_name}</td>
                      <td>{item.status}</td>
                      <td>{item.error_summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>4. 初始化知识</h3>
            <p className="muted">商品同步后，可进入知识中心维护 SOP 和商品人工知识。保存草稿不会立即生效，发布并索引成功后才会成为 AI 当前使用的知识。</p>
          </div>
        </div>
        <div className="onboarding-next-grid">
          <a className="state-card" href="/products">去商品知识查看覆盖率</a>
          <a className="state-card" href="/knowledge-center">去知识中心维护 SOP 和人工知识</a>
          <a className="state-card" href="/live-chat">去试聊调试验证 no-send 回复</a>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>5. 接入验收</h3>
            <p className="muted">启用 AI 前必须确认授权、商品同步、试聊验证和人工锁管理状态。验收调试会调用已配置的 LLM、Embedding 和 pgvector，但仍保持 no-send。</p>
          </div>
          <button type="button" onClick={refreshReadiness} disabled={!businessShopIdReady || loading}>刷新验收状态</button>
        </div>
        {shopIdentityPending ? (
          <div className="warning-banner error-state">
            <strong>接入验收已阻断：</strong>
            {shopIdentityBlockReason}
          </div>
        ) : !activeShopId ? (
          <div className="state-card">请先完成登录授权。</div>
        ) : (
          <>
            {checklist && (
              <>
                <div className="panel-header">
                  <StatusBadge tone={checklist.ready_for_ai ? "success" : "warning"}>
                    {checklist.ready_for_ai ? "可以启用 AI" : "暂不可启用 AI"}
                  </StatusBadge>
                  {!checklist.ready_for_ai && <span className="muted">阻塞项：{checklist.blocking_items.join("、") || "-"}</span>}
                </div>
                <div className="checklist-grid">
                  {checklist.items.map((item) => (
                    <div className="state-card checklist-item" key={item.key}>
                      <div className="panel-header">
                        <strong>{item.label}</strong>
                        <StatusBadge tone={checklistTone(item.status)}>{`${checklistLabel(item.status)} ${item.status}`}</StatusBadge>
                      </div>
                      <p className="muted">{item.summary}</p>
                      <small>{item.required ? "必填项" : "非阻塞项"}</small>
                    </div>
                  ))}
                </div>
              </>
            )}
            <div className="validation-box">
              <h4>no-send 试聊验收</h4>
              <p className="muted">推荐测试：这个多少钱、这个什么规格、这个怎么用、多久发货、收到破损怎么办、孕妇能用吗、我要人工。</p>
              <textarea value={validationSummary} onChange={(event) => setValidationSummary(event.target.value)} />
              <div className="inline-form">
                <a className="button-like" href="/live-chat">打开试聊调试</a>
                <button type="button" disabled={loading} onClick={handleMarkValidationPassed}>我已完成试聊并确认通过</button>
              </div>
            </div>
            {workerStatus && (
              <div className="state-card worker-status-card">
                <div className="panel-header">
                  <strong>AI / Worker 联动状态</strong>
                  <StatusBadge tone={workerConsistencyTone(workerStatus.consistency_status)}>
                    {workerConsistencyLabel(workerStatus.consistency_status)}
                  </StatusBadge>
                </div>
                <div className="status-detail-grid">
                  <div>
                    <span className="muted">AI 配置</span>
                    <strong>{workerStatus.ai_enabled ? "已启用" : "已关闭"}</strong>
                  </div>
                  <div>
                    <span className="muted">Worker</span>
                    <strong>{workerStatus.status}</strong>
                  </div>
                  <div>
                    <span className="muted">WebSocket</span>
                    <strong>{workerStatus.websocket_status}</strong>
                  </div>
                  <div>
                    <span className="muted">最后心跳</span>
                    <strong>{workerStatus.last_seen_at || "-"}</strong>
                  </div>
                </div>
                {workerStatus.attention_required && workerStatus.recommended_action && (
                  <div className="warning-banner">{workerStatus.recommended_action}</div>
                )}
              </div>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>6. 启用 AI</h3>
            <p className="muted">启用只修改该店铺 AI 配置状态，不启动 worker，不发送 PDD 消息。真实自动回复接入仍需后续运行侧读取该配置。</p>
          </div>
          {aiStatus && <StatusBadge tone={aiStatus.ai_enabled ? "success" : "warning"}>{aiStatus.ai_enabled ? "已启用" : "未启用"}</StatusBadge>}
        </div>
        {shopIdentityPending ? (
          <div className="warning-banner error-state">
            <strong>暂不能启用 AI：</strong>
            {shopIdentityBlockReason}
          </div>
        ) : !activeShopId ? (
          <div className="state-card">请先完成登录授权。</div>
        ) : (
          <>
            <div className="inline-form">
              <button type="button" disabled={loading || !checklist?.ready_for_ai} onClick={() => handleEnableAi(false)}>
                启用 AI
              </button>
              <input value={disableReason} onChange={(event) => setDisableReason(event.target.value)} placeholder="关闭原因" />
              <button type="button" disabled={loading} onClick={handleDisableAi}>关闭 AI</button>
            </div>
            {!checklist?.ready_for_ai && (
              <div className="warning-banner">
                <strong>强制启用需要理由：</strong>
                <p>仅在运营负责人确认风险后使用。强制启用会写入审计记录，但仍不会启动 worker 或发送 PDD 消息。</p>
                <textarea value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="填写强制启用原因" />
                <button type="button" disabled={loading || !overrideReason.trim()} onClick={() => handleEnableAi(true)}>
                  强制启用 AI 配置
                </button>
              </div>
            )}
            {aiStatus?.enabled_at && <div className="state-card">启用时间：{aiStatus.enabled_at}，操作人：{aiStatus.enabled_by || "-"}</div>}
          </>
        )}
      </section>
    </div>
  );
}
