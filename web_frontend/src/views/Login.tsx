import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { loginAdmin } from "../api/auth";

export function Login() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = useMemo(() => searchParams.get("next") || "/dashboard", [searchParams]);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!username.trim() || !password) {
      setError("请输入管理员账号和登录密码。");
      return;
    }
    setLoading(true);
    try {
      await loginAdmin({ username: username.trim(), password, remember });
      navigate(next.startsWith("/") ? next : "/dashboard", { replace: true });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "登录失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-brand-panel">
        <div className="login-brand">
          <div className="login-brand-mark">IE</div>
          <div>
            <h1>InternalEngine</h1>
            <p>AI 客服运营后台</p>
          </div>
        </div>
        <div className="login-intro">
          <h2>登录后进入真实运营工作台</h2>
          <p>
            用后台鉴权保护店铺接入、知识库、链路观测和 Worker 控制。生产发送由环境开关和店铺状态共同控制。
          </p>
          <div className="login-signal-grid">
            <div>
              <strong>会话鉴权</strong>
              <span>登录成功后写入 HttpOnly Cookie。</span>
            </div>
            <div>
              <strong>单管理员</strong>
              <span>第一期只做后台管理员鉴权。</span>
            </div>
            <div>
              <strong>接口保护</strong>
              <span>未登录访问 `/api/*` 会返回 401。</span>
            </div>
            <div>
              <strong>退出闭环</strong>
              <span>退出后清除会话并回到登录页。</span>
            </div>
          </div>
        </div>
      </section>

      <section className="login-form-panel">
        <form className="login-card" onSubmit={handleSubmit}>
          <header>
            <div>
              <h2>后台登录</h2>
              <p>请输入运营后台管理员账号。</p>
            </div>
            <span className="status-badge status-success">会话保护</span>
          </header>

          {error ? <div className="alert-box danger">{error}</div> : null}

          <label>
            <span>管理员账号</span>
            <input value={username} autoComplete="username" onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label>
            <span>登录密码</span>
            <input
              value={password}
              type="password"
              autoComplete="current-password"
              placeholder="输入后台登录密码"
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <div className="login-row">
            <label className="checkbox-label">
              <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
              保持本机登录 7 天
            </label>
          </div>
          <button type="submit" disabled={loading}>
            {loading ? "登录中..." : "登录运营后台"}
          </button>
          <p className="muted login-help">若忘记密码，请在服务器 `.env.web` 中更新 `WEB_ADMIN_PASSWORD` 后重启 Web API。</p>
        </form>
      </section>
    </main>
  );
}
