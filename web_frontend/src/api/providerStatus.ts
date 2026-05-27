import { apiGet } from "./client";

export type ProviderState = {
  configured: boolean;
  env_keys_present: string[];
  status: "configured" | "config_missing" | "invalid_config" | "disabled" | string;
  safe_display: Record<string, string>;
  error_type?: string | null;
};

export type ProviderStatus = {
  engine: "internal";
  no_send: boolean;
  providers: Record<string, ProviderState>;
  warnings: string[];
};

export function getProviderStatus() {
  return apiGet<ProviderStatus>("/api/provider-status");
}
