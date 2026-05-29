import { useEffect, useState } from "react";

import { getProviderStatus, ProviderStatus } from "../api/providerStatus";
import { StatusBadge } from "../components/StatusBadge";

export function Settings() {
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    try {
      setError(null);
      setProviderStatus(await getProviderStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : "服务状态加载失败");
    }
  }

  return (
    <div className="two-column">
      <section className="panel">
        <h2>系统设置</h2>
        <p>用于查看本地 InternalEngine 运营后台配置状态。这里只显示安全摘要，不展示真实密钥。</p>
        <div className="status-list">
          <StatusBadge tone="success">InternalEngine 版本：mvp</StatusBadge>
          <StatusBadge tone="info">no-send 状态：已启用</StatusBadge>
          <StatusBadge tone="warning">PDD 真实发送已关闭</StatusBadge>
        </div>
      </section>
      <section className="panel">
        <div className="panel-header compact-header">
          <div>
            <h2>环境 / 服务状态</h2>
            <p>密钥、token、cookie、DSN 密码不会回显，只展示 configured / missing / invalid 等状态。</p>
          </div>
          <button type="button" onClick={() => void refresh()}>刷新</button>
        </div>
        {error ? <div className="warning-banner error-state">{error}</div> : null}
        <div className="status-list">
          <StatusBadge tone="success">InternalEngine 就绪</StatusBadge>
          <StatusBadge tone={statusTone(providerStatus?.providers.pgvector?.status)}>{`PgVector ${providerStatus?.providers.pgvector?.status ?? "unknown"}`}</StatusBadge>
          <StatusBadge tone={statusTone(providerStatus?.providers.embedding?.status)}>{`Embedding ${providerStatus?.providers.embedding?.status ?? "unknown"}`}</StatusBadge>
          <StatusBadge tone={statusTone(providerStatus?.providers.llm?.status)}>{`LLM ${providerStatus?.providers.llm?.status ?? "unknown"}`}</StatusBadge>
          <StatusBadge tone="info">no-send 已启用</StatusBadge>
          <StatusBadge tone="warning">PDD 真实发送已关闭</StatusBadge>
        </div>
        <div className="detail-grid">
          <ProviderDetail title="PgVector" data={providerStatus?.providers.pgvector?.safe_display} />
          <ProviderDetail title="Embedding" data={providerStatus?.providers.embedding?.safe_display} />
          <ProviderDetail title="LLM" data={providerStatus?.providers.llm?.safe_display} />
        </div>
      </section>
    </div>
  );
}

function ProviderDetail({ title, data }: { title: string; data?: Record<string, string> }) {
  return (
    <div className="state-card">
      <strong>{title}</strong>
      {data && Object.keys(data).length > 0 ? (
        Object.entries(data).map(([key, value]) => (
          <p key={key}>
            {key}: {value || "configured"}
          </p>
        ))
      ) : (
        <p>暂无可安全展示的配置详情。</p>
      )}
    </div>
  );
}

function statusTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "configured") return "success";
  if (status === "config_missing") return "warning";
  if (status === "invalid_config") return "danger";
  if (status === "disabled") return "info";
  return "neutral";
}
