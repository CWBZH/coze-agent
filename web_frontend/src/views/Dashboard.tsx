import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";

const alerts = [
  { time: "20:42", level: "warning", message: "店铺 565617 WebSocket 曾断开，需要关注重连状态" },
  { time: "20:30", level: "info", message: "商品知识索引任务已完成一次 dry-run 检查" },
  { time: "20:18", level: "success", message: "InternalEngine 回复已启用安全拦截规则" }
];

export function Dashboard() {
  return (
    <div className="page-stack">
      <section className="panel intro-panel">
        <h2>数据总览</h2>
        <p>
          这里是后台整体运行状态入口，用于查看店铺、消息、AI 回复链路、知识库和安全状态。
          当前后台面向内部运营，默认不发送真实 PDD 消息。
        </p>
      </section>

      <section className="metrics-grid">
        <MetricCard label="店铺总数" value="2" caption="已接入的 PDD 店铺" />
        <MetricCard label="启用 InternalEngine" value="2" caption="仅使用自研引擎" />
        <MetricCard label="不发送模式" value="已启用" caption="PDD 真实发送关闭" />
        <MetricCard label="RAG 索引健康度" value="正常" caption="商品与 SOP 知识状态" />
        <MetricCard label="24 小时消息量" value="126" caption="本地诊断数据" />
        <MetricCard label="RAG 命中率" value="92%" caption="近期 InternalEngine trace" />
        <MetricCard label="LLM 错误数" value="0" caption="当前面板统计" />
        <MetricCard label="安全拦截数" value="3" caption="红线问题保护" />
      </section>
      <section className="two-column">
        <div className="panel">
          <h2>最近提醒</h2>
          {alerts.map((alert) => (
            <div className="list-row" key={alert.time}>
              <span>{alert.time}</span>
              <StatusBadge tone={alert.level === "success" ? "success" : alert.level === "warning" ? "warning" : "info"}>
                {alert.level === "success" ? "正常" : alert.level === "warning" ? "注意" : "信息"}
              </StatusBadge>
              <span>{alert.message}</span>
            </div>
          ))}
        </div>
        <div className="panel">
          <h2>系统安全状态</h2>
          <div className="status-list">
            <StatusBadge tone="info">不发送真实消息 no_send</StatusBadge>
            <StatusBadge tone="warning">PDD 真实发送已关闭</StatusBadge>
            <StatusBadge tone="success">密钥不回显</StatusBadge>
            <StatusBadge tone="success">InternalEngine 已启用</StatusBadge>
          </div>
        </div>
      </section>
    </div>
  );
}
