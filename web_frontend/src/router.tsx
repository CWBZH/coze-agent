import { createBrowserRouter, Navigate } from "react-router-dom";

import { App } from "./App";
import { AISettings } from "./views/AISettings";
import { Dashboard } from "./views/Dashboard";
import { HumanLocks } from "./views/HumanLocks";
import { KnowledgeCenter } from "./views/KnowledgeCenter";
import { LiveChat } from "./views/LiveChat";
import { Products } from "./views/Products";
import { Settings } from "./views/Settings";
import { ShopOnboarding } from "./views/ShopOnboarding";
import { Shops } from "./views/Shops";
import { SOP } from "./views/SOP";
import { TraceLogs } from "./views/TraceLogs";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <Dashboard /> },
      { path: "shop-onboarding", element: <ShopOnboarding /> },
      { path: "shops", element: <Shops /> },
      { path: "ai-settings", element: <AISettings /> },
      { path: "products", element: <Products /> },
      { path: "sop", element: <SOP /> },
      { path: "knowledge-center", element: <KnowledgeCenter /> },
      { path: "human-locks", element: <HumanLocks /> },
      { path: "live-chat", element: <LiveChat /> },
      { path: "trace-logs", element: <TraceLogs /> },
      { path: "settings", element: <Settings /> }
    ]
  }
]);
