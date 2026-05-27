import { useEffect, useState } from "react";

import { AISettings as SettingsType, getAISettings, updateAISettings } from "../api/aiSettings";
import { StatusBadge } from "../components/StatusBadge";

export function AISettings() {
  const [settings, setSettings] = useState<SettingsType | null>(null);

  useEffect(() => {
    getAISettings("323473738").then(setSettings);
  }, []);

  async function tryEnableSending() {
    const updated = await updateAISettings("323473738", { send_enabled: true });
    setSettings(updated);
  }

  if (!settings) return <div className="panel">正在加载 AI 设置...</div>;

  return (
    <div className="three-column">
      <section className="panel">
        <h2>店铺</h2>
        <p className="muted">用于查看店铺级 InternalEngine、RAG 和安全配置。MVP 不提供真实发送开关。</p>
        <label>店铺选择</label>
        <select><option>323473738 · 美肌萌主驿站</option></select>
        <p>账号状态 account_status: active</p>
        <p>WebSocket 状态 websocket_status: connected</p>
      </section>
      <section className="panel form-grid">
        <h2>InternalEngine 与 RAG 配置</h2>
        {[
          ["InternalEngine 已启用", settings.internal_enabled],
          ["不发送真实消息 no_send", settings.no_send_mode],
          ["影子模式 Shadow", settings.shadow_enabled],
          ["RAG 已启用", settings.rag_enabled],
          ["意图分类器已启用", settings.intent_classifier_enabled],
          ["回答生成器已启用", settings.answer_generator_enabled],
          ["安全拦截 Guardrail 已启用", settings.guardrail_enabled]
        ].map(([label, value]) => (
          <label key={String(label)} className="toggle-row">
            <span>{label}</span>
            <input type="checkbox" checked={Boolean(value)} readOnly />
          </label>
        ))}
        <label>商品版本<input value={settings.product_version} readOnly /></label>
        <label>SOP 版本<input value={settings.sop_version} readOnly /></label>
        <label>RAG Top K<input value={settings.rag_top_k} readOnly /></label>
        <button onClick={tryEnableSending}>测试 InternalEngine 配置（no-send）</button>
        {settings.warning ? <p className="warning-text">{settings.warning}</p> : null}
      </section>
      <section className="panel">
        <h2>风险与密钥状态</h2>
        <p className="muted">只显示 configured/missing/disabled 等状态，不回显真实密钥。</p>
        {Object.entries(settings.secret_status).map(([key, value]) => (
          <div className="list-row" key={key}>
            <span>{key}</span>
            <StatusBadge tone={value === "configured" ? "success" : value === "disabled" ? "warning" : "neutral"}>{value}</StatusBadge>
          </div>
        ))}
        <StatusBadge tone="warning">MVP 不支持真实发送开关</StatusBadge>
      </section>
    </div>
  );
}
