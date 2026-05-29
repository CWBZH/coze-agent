import { useEffect, useState } from "react";
import { getDashboardSummary, type DashboardSummary } from "../api/dashboard";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";

function toneOf(level: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (level === "success") return "success";
  if (level === "warning") return "warning";
  if (level === "danger" || level === "failed") return "danger";
  if (level === "info") return "info";
  return "neutral";
}

function levelLabel(level: string) {
  if (level === "success") return "正常";
  if (level === "warning") return "注意";
  if (level === "danger" || level === "failed") return "失败";
  if (level === "info") return "信息";
  return "状态";
}

export function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDashboardSummary()
      .then((payload) => {
        if (!cancelled) {
          setSummary(payload);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="page-stack">
      <section className="panel intro-panel">
        <h2>数据总览</h2>
        <p>
          这里展示真实运行数据：店铺、商品知识、索引任务、试聊链路和安全状态。后台默认不发送真实 PDD 消息。
        </p>
      </section>

      {error ? <section className="alert alert-danger">数据总览加载失败：{error}</section> : null}
      {summary?.warning ? <section className="alert alert-warning">数据源提示：{summary.warning}</section> : null}

      <section className="metrics-grid">
        {(summary?.metrics ?? []).map((metric) => (
          <MetricCard key={metric.key} label={metric.label} value={metric.value} caption={metric.caption ?? undefined} />
        ))}
        {!summary && !error ? <MetricCard label="加载中" value="..." caption="正在读取真实后台数据" /> : null}
      </section>

      <section className="two-column">
        <div className="panel">
          <h2>最近提醒</h2>
          {(summary?.alerts ?? []).map((alert, index) => (
            <div className="list-row" key={`${alert.time ?? "no-time"}-${index}`}>
              <span>{alert.time ?? "-"}</span>
              <StatusBadge tone={toneOf(alert.level)}>{levelLabel(alert.level)}</StatusBadge>
              <span>{alert.message}</span>
            </div>
          ))}
          {summary && summary.alerts.length === 0 ? <p className="muted">暂无真实运行提醒。</p> : null}
        </div>
        <div className="panel">
          <h2>系统安全状态</h2>
          <div className="status-list">
            {(summary?.system_status ?? []).map((item, index) => (
              <StatusBadge key={`${item.message}-${index}`} tone={toneOf(item.level)}>
                {item.message}
              </StatusBadge>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
