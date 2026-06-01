import { useEffect, useState } from "react";
import { createBrowserRouter, Navigate, Outlet, useLocation } from "react-router-dom";

import { App } from "./App";
import { getAdminSession } from "./api/auth";
import { Dashboard } from "./views/Dashboard";
import { HumanLocks } from "./views/HumanLocks";
import { KnowledgeCenter } from "./views/KnowledgeCenter";
import { LiveChat } from "./views/LiveChat";
import { Login } from "./views/Login";
import { Products } from "./views/Products";
import { Settings } from "./views/Settings";
import { ShopOnboarding } from "./views/ShopOnboarding";
import { Shops } from "./views/Shops";
import { TraceLogs } from "./views/TraceLogs";

function RequireAdminSession() {
  const location = useLocation();
  const [status, setStatus] = useState<"checking" | "ok" | "denied">("checking");

  useEffect(() => {
    let cancelled = false;
    setStatus("checking");
    getAdminSession()
      .then(() => {
        if (!cancelled) {
          setStatus("ok");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("denied");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

  if (status === "checking") {
    return <div className="auth-checking">正在校验后台登录状态...</div>;
  }

  if (status === "denied") {
    const next = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }

  return <Outlet />;
}

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <Login />
  },
  {
    path: "/",
    element: <RequireAdminSession />,
    children: [
      {
        element: <App />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          { path: "dashboard", element: <Dashboard /> },
          { path: "shop-onboarding", element: <ShopOnboarding /> },
          { path: "shops", element: <Shops /> },
          { path: "products", element: <Products /> },
          { path: "sop", element: <Navigate to="/knowledge-center" replace /> },
          { path: "knowledge-center", element: <KnowledgeCenter /> },
          { path: "human-locks", element: <HumanLocks /> },
          { path: "live-chat", element: <LiveChat /> },
          { path: "trace-logs", element: <TraceLogs /> },
          { path: "settings", element: <Settings /> }
        ]
      }
    ]
  }
]);
