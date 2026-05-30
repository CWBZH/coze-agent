import { useEffect, useState } from "react";

import { AISettings as SettingsType, getAISettings, updateAISettings } from "../api/aiSettings";
import { StatusBadge } from "../components/StatusBadge";

const DEFAULT_SHOP_ID = "323473738";

export function AISettings() {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    getAISettings(DEFAULT_SHOP_ID).then(setSettings);
  }, []);

  async function tryEnableSending() {
    const updated = await updateAISettings(DEFAULT_SHOP_ID, { send_enabled: true });
    setSettings(updated);
    setMessage(updated.send_enabled ? "真实发送已按服务器配置开启。" : "服务器未开启 PDD_SENDING_ENABLED，当前仍保持 no-send。");
  }

  if (!settings) return <div className="panel">正在加载 AI 设置...</div>;

  return (
    <div className="three-column">
      <section className="panel">
        <h2>店铺</h2>
        <p className="muted">
          查看店铺级 InternalEngine、RAG、LLM 和安全配置。PDD 真实发送只由服务器环境变量控制，后台页面不能绕过安全开关。
        </p>
        <label>店铺 ID</label>
        <input value={settings.shop_id} readOnly />
        <p>账号状态：active</p>
        <p>WebSocket 状态：只读展示，当前页面不启动 worker。</p>
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
        <button onClick={tryEnableSending}>检查真实发送开关</button>
        {settings.warning ? <p className="warning-text">{settings.warning}</p> : null}
        {message ? <p className="muted">{message}</p> : null}
      </section>

      <section className="panel">
        <h2>风险与密钥状态</h2>
        <p className="muted">只显示 configured/missing/disabled 状态，不回显真实密钥、token、cookie 或密码。</p>
        {Object.entries(settings.secret_status).map(([key, value]) => (
          <div className="list-row" key={key}>
            <span>{key}</span>
            <StatusBadge tone={value === "configured" ? "success" : value === "disabled" ? "warning" : "neutral"}>{value}</StatusBadge>
          </div>
        ))}
        <StatusBadge tone={settings.send_enabled ? "warning" : "info"}>
          {settings.send_enabled ? "PDD 真实发送已开启" : "PDD 真实发送关闭"}
        </StatusBadge>
      </section>
    </div>
  );
}
