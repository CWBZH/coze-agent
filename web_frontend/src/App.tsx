import { Outlet } from "react-router-dom";

import { AdminLayout } from "./layouts/AdminLayout";

export function App() {
  return (
    <AdminLayout>
      <Outlet />
    </AdminLayout>
  );
}
