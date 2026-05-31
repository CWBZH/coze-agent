import { useEffect, useMemo, useState } from "react";

import { getProviderStatus, ProviderState, ProviderStatus } from "../api/providerStatus";
import { StatusBadge } from "../components/StatusBadge";

const PROVIDER_LABELS: Record<string, string> = {
  pgvector: "PgVector",
  embedding: "Embedding",
  llm: "LLM",
  ollama: "Ollama",
  pdd_sending: "PDD 真实发送"
};

export function Settings() {
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState("");

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    try {
      setError(null);
      const status = await getProviderStatus();
      setProviderStatus(status);
      setLastUpdatedAt(new Date().toLocaleString("zh-CN", { hour12: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "服务状态加载失败");
    }
  }

  const providerEntries = useMemo(() => {
    return Object.entries(providerStatus?.providers || {}).sort(([left], [right]) => {
      const order = ["pgvector", "embedding", "llm", "ollama", "pdd_sending"];
      const leftIndex = order.indexOf(left);
      const rightIndex = order.indexOf(right);
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex);
    });
  }, [providerStatus]);

  const configuredCount = providerEntries.filter(([, provider]) => provider.status === "configured").length;
  const warningCount = providerStatus?.warnings?.length || 0;

  return (
    <div className="settings-page">
      <section className="panel">
        <div className="panel-header compact-header">
          <div>
            <h2>系统设置</h2>
            <p className="muted">这里只展示真实运行配置状态，所有状态来自 /api/provider-status。密钥、token、cookie、DSN 密码不会回显。</p>
          </div>
          <button type="button" onClick={() => void refresh()}>刷新</button>
        </div>

        {error ? <div className="warning-banner error-state">{error}</div> : null}

        <div className="settings-summary-grid">
          <SummaryCard label="引擎" value={providerStatus?.engine || "unknown"} tone="info" />
          <SummaryCard label="no-send" value={providerStatus ? (providerStatus.no_send ? "开启" : "关闭") : "unknown"} tone={providerStatus?.no_send ? "info" : "warning"} />
          <SummaryCard label="已配置服务" value={`${configuredCount}/${providerEntries.length || 0}`} tone={warningCount ? "warning" : "success"} />
          <SummaryCard label="配置警告" value={warningCount} tone={warningCount ? "warning" : "success"} />
        </div>

        <div className="settings-meta">
          <span>最近刷新：{lastUpdatedAt || "尚未刷新"}</span>
          {providerStatus?.warnings?.length ? <span>警告项：{providerStatus.warnings.join(", ")}</span> : <span>当前无 provider warning</span>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header compact-header">
          <div>
            <h2>服务状态</h2>
            <p className="muted">运营只需要看 status 是否 configured。safe_display 只显示安全摘要，不显示真实凭据。</p>
          </div>
        </div>

        {providerEntries.length === 0 ? <div className="state-card">暂无 provider-status 数据。</div> : null}

        <div className="settings-provider-grid">
          {providerEntries.map(([key, provider]) => (
            <ProviderCard key={key} name={PROVIDER_LABELS[key] || key} providerKey={key} provider={provider} />
          ))}
        </div>
      </section>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone
}: {
  label: string;
  value: string | number;
  tone: "success" | "warning" | "danger" | "info" | "neutral";
}) {
  return (
    <div className="settings-summary-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <StatusBadge tone={tone}>{String(value)}</StatusBadge>
    </div>
  );
}

function ProviderCard({ name, providerKey, provider }: { name: string; providerKey: string; provider: ProviderState }) {
  return (
    <article className="settings-provider-card">
      <header>
        <div>
          <h3>{name}</h3>
          <p className="muted">{providerKey}</p>
        </div>
        <StatusBadge tone={statusTone(provider.status)}>{provider.status}</StatusBadge>
      </header>

      <dl className="settings-provider-kv">
        <div>
          <dt>configured</dt>
          <dd>{provider.configured ? "true" : "false"}</dd>
        </div>
        <div>
          <dt>env_keys_present</dt>
          <dd>{provider.env_keys_present.length ? provider.env_keys_present.join(", ") : "无"}</dd>
        </div>
        <div>
          <dt>error_type</dt>
          <dd>{provider.error_type || "无"}</dd>
        </div>
      </dl>

      <div className="settings-safe-display">
        <strong>safe_display</strong>
        {Object.keys(provider.safe_display || {}).length ? (
          <dl className="settings-provider-kv compact">
            {Object.entries(provider.safe_display).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{value || "configured"}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="muted">暂无可安全展示的配置详情。</p>
        )}
      </div>
    </article>
  );
}

function statusTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "configured") return "success";
  if (status === "config_missing") return "warning";
  if (status === "invalid_config") return "danger";
  if (status === "disabled") return "info";
  return "neutral";
}
