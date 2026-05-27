import { ReactNode } from "react";

import { Header } from "../components/Header";
import { Sidebar } from "../components/Sidebar";

type AdminLayoutProps = {
  children: ReactNode;
};

export function AdminLayout({ children }: AdminLayoutProps) {
  return (
    <div className="admin-shell">
      <Sidebar />
      <main className="main-area">
        <Header />
        <div className="page-content">{children}</div>
      </main>
    </div>
  );
}
