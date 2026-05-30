type StatusBadgeProps = {
  children: string | boolean | number | null | undefined;
  tone?: "success" | "warning" | "danger" | "info" | "neutral";
};

const STATUS_LABELS: Record<string, string> = {
  active: "当前生效 active",
  draft: "草稿 draft",
  pending: "待处理 pending",
  pending_index: "待索引 pending_index",
  running: "执行中 running",
  succeeded: "成功 succeeded",
  failed: "失败 failed",
  retired: "已退役 retired",
  archived: "已归档 archived",
  retrying: "重试中 retrying",
  pending_human: "人工接管中 pending_human",
  unlocked: "已解除 unlocked",
  config_missing: "配置缺失 config_missing",
  configured: "已配置 configured",
  invalid_config: "配置异常 invalid_config",
  no_send: "不发送真实消息 no_send",
  safe: "安全 safe",
  blocked: "已拦截 blocked",
  true: "是 true",
  false: "否 false",
};

export function StatusBadge({ children, tone = "neutral" }: StatusBadgeProps) {
  const raw = String(children);
  return <span className={`status-badge status-${tone}`}>{STATUS_LABELS[raw] ?? raw}</span>;
}
