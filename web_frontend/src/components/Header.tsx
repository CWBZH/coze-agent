import { StatusBadge } from "./StatusBadge";

export function Header() {
  return (
    <header className="top-header">
      <div>
        <h1>AI 客服运营后台</h1>
        <p>仅使用 InternalEngine · 默认不发送真实 PDD 消息</p>
      </div>
      <div className="header-badges">
        <StatusBadge tone="info">不发送真实消息 no_send</StatusBadge>
        <StatusBadge tone="warning">PDD 真实发送已关闭</StatusBadge>
        <StatusBadge tone="success">密钥不回显</StatusBadge>
      </div>
    </header>
  );
}
