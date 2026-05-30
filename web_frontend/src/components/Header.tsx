import { useEffect, useState } from "react";
import { getProviderStatus, ProviderStatus } from "../api/providerStatus";
import { StatusBadge } from "./StatusBadge";

export function Header() {
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);

  useEffect(() => {
    getProviderStatus()
      .then(setProviderStatus)
      .catch(() => setProviderStatus(null));
  }, []);

  const pddStatus = providerStatus?.providers?.pdd_sending?.status;
  const pddSendingEnabled = pddStatus === "enabled";
  const llmEnabled = providerStatus?.providers?.llm?.status === "configured";
  const ragEnabled =
    providerStatus?.providers?.pgvector?.status === "configured" &&
    providerStatus?.providers?.embedding?.status === "configured";

  return (
    <header className="top-header">
      <div>
        <h1>AI 客服运营后台</h1>
        <p>仅使用 InternalEngine，PDD 真实发送由生产开关控制。</p>
      </div>
      <div className="header-badges">
        <StatusBadge tone={pddSendingEnabled ? "warning" : "info"}>
          {pddSendingEnabled ? "PDD 真实发送已开启" : "不发送真实消息 no_send"}
        </StatusBadge>
        <StatusBadge tone={ragEnabled ? "success" : "warning"}>{`RAG ${ragEnabled ? "可用" : "未配置"}`}</StatusBadge>
        <StatusBadge tone={llmEnabled ? "success" : "warning"}>{`LLM ${llmEnabled ? "可用" : "未配置"}`}</StatusBadge>
        <StatusBadge tone="success">密钥不回显</StatusBadge>
      </div>
    </header>
  );
}
