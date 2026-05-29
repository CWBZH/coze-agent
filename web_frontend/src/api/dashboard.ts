import { apiGet } from "./client";

export type DashboardMetric = {
  key: string;
  label: string;
  value: string | number;
  caption?: string | null;
};

export type DashboardAlert = {
  time?: string | null;
  level: "success" | "warning" | "danger" | "info" | "neutral" | string;
  message: string;
};

export type DashboardSummary = {
  metrics: DashboardMetric[];
  alerts: DashboardAlert[];
  system_status: DashboardAlert[];
  warning?: string | null;
};

export function getDashboardSummary() {
  return apiGet<DashboardSummary>("/api/dashboard/summary");
}
