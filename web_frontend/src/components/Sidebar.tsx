import { NavLink } from "react-router-dom";

const navItems = [
  ["数据总览", "/dashboard"],
  ["店铺接入", "/shop-onboarding"],
  ["店铺管理", "/shops"],
  ["商品知识", "/products"],
  ["知识中心", "/knowledge-center"],
  ["人工锁管理", "/human-locks"],
  ["试聊调试", "/live-chat"],
  ["链路观测", "/trace-logs"],
  ["系统设置", "/settings"]
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">IE</span>
        <div>
          <strong>InternalEngine</strong>
          <small>AI 运营控制台</small>
        </div>
      </div>
      <nav>
        {navItems.map(([label, path]) => (
          <NavLink key={path} to={path} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
