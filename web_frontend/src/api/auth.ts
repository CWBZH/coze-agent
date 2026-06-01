import { apiGet, apiPost } from "./client";

export type AdminSession = {
  authenticated: boolean;
  username?: string;
  configured?: boolean;
  insecure_default_secret?: boolean;
};

export type LoginPayload = {
  username: string;
  password: string;
  remember: boolean;
};

export function getAdminSession() {
  return apiGet<AdminSession>("/api/auth/session");
}

export function loginAdmin(payload: LoginPayload) {
  return apiPost<AdminSession>("/api/auth/login", payload);
}

export function logoutAdmin() {
  return apiPost<{ authenticated: boolean }>("/api/auth/logout", {});
}
