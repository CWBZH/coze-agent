import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  cancelOnboardingSession,
  checkRemoteBrowserLogin,
  createOnboardingSession,
  getOnboardingSession,
  OnboardingSession,
  submitSmsCode
} from "../api/shopOnboarding";
import { StatusBadge } from "../components/StatusBadge";

const terminalStatuses = new Set(["succeeded", "failed", "expired", "cancelled", "blocked_complex_verification"]);

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    created: "已创建",
    opening_login_page: "正在打开登录页",
    waiting_account: "等待账号信息",
    waiting_sms_code: "等待短信验证码",
    waiting_captcha: "等待图形验证码",
    logging_in: "登录中",
    succeeded: "登录成功",
    failed: "登录失败",
    expired: "已过期",
    cancelled: "已取消",
    blocked_complex_verification: "需要复杂验证",
    waiting_user_verification: "等待远程浏览器验证"
  };
  return labels[status] ?? status;
}

function stepLabel(step: string) {
  const labels: Record<string, string> = {
    created: "创建会话",
    waiting_sms_code: "输入短信验证码",
    waiting_captcha: "输入图形验证码",
    succeeded: "授权成功",
    failed: "失败",
    expired: "过期",
    cancelled: "取消",
    blocked_complex_verification: "复杂验证",
    waiting_user_verification: "远程浏览器验证"
  };
  return labels[step] ?? step;
}

export function ShopOnboarding() {
  const [shopName, setShopName] = useState("");
  const [accountName, setAccountName] = useState("");
  const [password, setPassword] = useState("");
  const [runnerMode, setRunnerMode] = useState<"fake" | "real" | "remote_browser">("fake");
  const [session, setSession] = useState<OnboardingSession | null>(null);
  const [smsCode, setSmsCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentStep = useMemo(() => {
    if (!session) return 1;
    if (session.status === "succeeded") return 3;
    return 2;
  }, [session]);

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

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const created = await createOnboardingSession({
        platform: "pdd",
        shop_name: shopName,
        account_name: accountName,
        password,
        runner_mode: runnerMode,
        operator: "local_admin"
      });
      setPassword("");
      setSession(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建登录会话失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmitSms() {
    if (!session || !smsCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setSession(await submitSmsCode(session.session_id, smsCode.trim()));
      setSmsCode("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交短信验证码失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleCancel() {
    if (!session) return;
    const ok = window.confirm("确定取消当前登录会话吗？取消后会关闭后台登录任务，不会发送 PDD 消息。");
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

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>店铺接入</h2>
            <p className="muted">
              用于在 Web 后台完成 PDD 店铺登录授权。第一版采用后台 Playwright 登录会话和短信验证码弹窗；商品同步、知识初始化和启用 AI 会在后续步骤完成。
            </p>
          </div>
          <StatusBadge tone="success">不会发送 PDD 消息</StatusBadge>
        </div>
        <div className="warning-banner">
          密码只用于当前登录会话，不会保存；授权 cookie/token 会加密存储，页面和 API 不回显。遇到滑块、扫码等复杂验证时，本版本会提示后续使用远程浏览器增强模式。
        </div>
        {runnerMode === "real" && (
          <div className="warning-banner">
            真实 PDD 登录会启动 Playwright 登录流程，需要你手动输入验证码；该流程不会发送 PDD 消息、不会启动 worker、不会启用 AI。
          </div>
        )}
        {runnerMode === "remote_browser" && (
          <div className="warning-banner">
            远程浏览器登录会为当前会话生成带短期 token 的 noVNC 地址，用户在页面中完成短信、滑块、扫码或安全验证。登录成功后只保存加密授权，不会发送 PDD 消息。
          </div>
        )}
      </section>

      <section className="panel onboarding-steps">
        {["填写店铺信息", "登录授权", "同步商品", "初始化知识", "试聊验收", "启用 AI"].map((label, index) => (
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
              登录模式
              <select value={runnerMode} onChange={(event) => setRunnerMode(event.target.value as "fake" | "real" | "remote_browser")}>
                <option value="fake">模拟登录（测试）</option>
                <option value="real">真实 PDD 登录</option>
                <option value="remote_browser">远程浏览器登录（滑块/扫码）</option>
              </select>
            </label>
            <label>
              店铺名称
              <input value={shopName} onChange={(event) => setShopName(event.target.value)} required placeholder="例如：美肌萌主驿站" />
            </label>
            <label>
              PDD 账号
              <input value={accountName} onChange={(event) => setAccountName(event.target.value)} required placeholder="请输入登录账号" />
            </label>
            <label>
              密码
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                placeholder="仅用于当前登录，不保存"
              />
            </label>
            <button disabled={loading}>{loading ? "处理中..." : "创建登录会话"}</button>
          </form>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h3>2. 登录授权状态</h3>
              <p className="muted">前端会轮询当前登录会话状态；如果需要短信验证码，会在这里提交。</p>
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
                <span className="muted">登录模式</span>
                <strong>
                  {session.runner_mode === "remote_browser"
                    ? "远程浏览器登录 remote_browser"
                    : session.runner_mode === "real"
                      ? "真实 PDD 登录 real"
                      : "模拟登录 fake"}
                </strong>
              </div>
              <div>
                <span className="muted">账号</span>
                <strong>{session.safe_display || "-"}</strong>
              </div>
              <div>
                <span className="muted">店铺 ID</span>
                <strong>{session.shop_id || "登录成功后绑定"}</strong>
              </div>
              <div>
                <span className="muted">过期时间</span>
                <strong>{session.expires_at}</strong>
              </div>
            </div>
          )}

          {session?.needs_sms_code && session.status === "waiting_sms_code" && (
            <div className="sms-panel">
              <h4>请输入短信验证码</h4>
              <p className="muted">验证码只提交给当前登录会话，不会写入日志或数据库。</p>
              <div className="inline-form">
                <input value={smsCode} onChange={(event) => setSmsCode(event.target.value)} placeholder="6 位短信验证码" />
                <button type="button" disabled={loading || !smsCode.trim()} onClick={handleSubmitSms}>
                  提交验证码
                </button>
              </div>
            </div>
          )}

          {session?.status === "blocked_complex_verification" && (
            <div className="warning-banner">当前登录需要滑块、扫码或复杂浏览器验证。第一版不绕过验证码，后续将通过远程浏览器模式支持。</div>
          )}

          {session?.runner_mode === "remote_browser" && (
            <div className="remote-browser-panel">
              <div className="panel-header">
                <div>
                  <h4>远程浏览器</h4>
                  <p className="muted">
                    在下方窗口中完成 PDD 登录和平台验证。该窗口地址带有当前会话 token，登录完成后点击“我已完成登录，检查状态”。
                  </p>
                </div>
                <StatusBadge tone={session.vnc_url_ready ? "success" : "warning"}>
                  {session.remote_browser_status || "not_ready"}
                </StatusBadge>
              </div>
              {session.vnc_url_ready && session.vnc_url ? (
                <iframe className="remote-browser-frame" src={session.vnc_url} title="PDD 远程浏览器登录" />
              ) : (
                <div className="warning-banner">
                  远程浏览器暂不可用：{session.error_summary || "noVNC 依赖或地址未配置"}。请确认服务器已配置 noVNC/websockify，并设置 WEB_NOVNC_BASE_URL。
                </div>
              )}
              <div className="inline-form">
                <button type="button" disabled={loading} onClick={handleCheckRemoteLogin}>
                  我已完成登录，检查状态
                </button>
                <button type="button" disabled={loading} onClick={() => session && getOnboardingSession(session.session_id).then(setSession).catch((err) => setError(err instanceof Error ? err.message : "刷新远程浏览器状态失败"))}>
                  刷新远程浏览器状态
                </button>
              </div>
            </div>
          )}

          {session?.status === "succeeded" && (
            <div className="state-card">
              登录授权已完成，shop_id={session.shop_id}。当前尚未同步商品，也未启用 AI 自动回复。
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
        <h3>下一步占位</h3>
        <div className="onboarding-next-grid">
          <div className="state-card">同步商品：后续 T204-C 会创建商品同步任务、进度条和失败重试。</div>
          <div className="state-card">初始化知识：进入知识中心维护 SOP 和商品人工知识。</div>
          <div className="state-card">试聊验收：进入试聊调试验证 no-send 回复效果。</div>
          <div className="state-card">启用 AI：必须在登录有效、商品同步完成、试聊通过后单独确认。</div>
        </div>
      </section>
    </div>
  );
}
