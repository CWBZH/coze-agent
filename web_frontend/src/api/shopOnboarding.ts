import { apiGet, apiPost } from "./client";

export type OnboardingSession = {
  session_id: string;
  platform: string;
  shop_id?: string | null;
  shop_name?: string | null;
  safe_display: string;
  runner_mode: "fake" | "real" | "remote_browser";
  status: string;
  step: string;
  needs_sms_code: boolean;
  needs_captcha: boolean;
  captcha_image_ref?: string | null;
  error_summary?: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string;
  completed_at?: string | null;
  cancelled_at?: string | null;
  remote_browser_available?: boolean;
  remote_browser_status?: string | null;
  vnc_url_ready?: boolean;
  vnc_url?: string | null;
  real_shop_id_pending?: boolean;
  shop_identity_status?: string | null;
  auth_status?: string | null;
};

export type CreateOnboardingPayload = {
  platform: "pdd";
  shop_name: string;
  account_name: string;
  password?: string;
  operator?: string;
  runner_mode?: "fake" | "real" | "remote_browser";
};

export type BindShopIdentityPayload = {
  mall_id: string;
  shop_name?: string;
  operator?: string;
};

export type AuthStatus = {
  shop_id: string;
  platform: string;
  account_name?: string | null;
  auth_status: string;
  safe_display: string;
  last_login_at?: string | null;
  expires_at?: string | null;
  insecure_auth_storage: boolean;
};

export type ChecklistItem = {
  key: string;
  label: string;
  status: "passed" | "failed" | "warning" | "skipped" | string;
  required: boolean;
  summary: string;
};

export type OnboardingChecklist = {
  shop_id: string;
  ready_for_ai: boolean;
  blocking_items: string[];
  items: ChecklistItem[];
};

export type ValidationRun = {
  id: string;
  shop_id: string;
  status: string;
  mode: string;
  passed_count: number;
  failed_count: number;
  tested_at: string;
  created_by: string;
  summary: string;
};

export type AiStatus = {
  shop_id: string;
  ai_enabled: boolean;
  enabled_at?: string | null;
  enabled_by?: string | null;
  disabled_at?: string | null;
  disabled_by?: string | null;
  last_change_reason?: string | null;
  override_enabled: boolean;
  override_reason?: string | null;
};

export type WorkerStatus = {
  shop_id: string;
  status: string;
  process_id?: number | null;
  last_seen_at?: string | null;
  websocket_status: string;
  summary: string;
  ai_enabled: boolean;
  consistency_status: string;
  attention_required: boolean;
  recommended_action?: string | null;
};

export function createOnboardingSession(payload: CreateOnboardingPayload) {
  return apiPost<OnboardingSession>("/api/shops/onboarding", payload);
}

export function getOnboardingSession(sessionId: string) {
  return apiGet<OnboardingSession>(`/api/shops/onboarding/${encodeURIComponent(sessionId)}`);
}

export function submitSmsCode(sessionId: string, smsCode: string) {
  return apiPost<OnboardingSession>(`/api/shops/onboarding/${encodeURIComponent(sessionId)}/submit-sms-code`, {
    sms_code: smsCode
  });
}

export function submitCaptcha(sessionId: string, captchaCode: string) {
  return apiPost<OnboardingSession>(`/api/shops/onboarding/${encodeURIComponent(sessionId)}/submit-captcha`, {
    captcha_code: captchaCode
  });
}

export function cancelOnboardingSession(sessionId: string) {
  return apiPost<OnboardingSession>(`/api/shops/onboarding/${encodeURIComponent(sessionId)}/cancel`, {});
}

export function checkRemoteBrowserLogin(sessionId: string) {
  return apiPost<OnboardingSession>(`/api/shops/onboarding/${encodeURIComponent(sessionId)}/check-login`, {});
}

export function bindShopIdentity(sessionId: string, payload: BindShopIdentityPayload) {
  return apiPost<OnboardingSession>(`/api/shops/onboarding/${encodeURIComponent(sessionId)}/bind-shop-identity`, payload);
}

export function getShopAuthStatus(shopId: string) {
  return apiGet<AuthStatus>(`/api/shops/${encodeURIComponent(shopId)}/auth-status`);
}

export function getOnboardingChecklist(shopId: string) {
  return apiGet<OnboardingChecklist>(`/api/shops/${encodeURIComponent(shopId)}/onboarding-checklist`);
}

export function markNoSendValidationPassed(shopId: string, summary: string, operator = "local_admin") {
  return apiPost<ValidationRun>(`/api/shops/${encodeURIComponent(shopId)}/onboarding-validation/mark-passed`, {
    operator,
    summary
  });
}

export function getAiStatus(shopId: string) {
  return apiGet<AiStatus>(`/api/shops/${encodeURIComponent(shopId)}/ai-status`);
}

export function enableAi(shopId: string, payload: { operator?: string; confirm: boolean; override?: boolean; override_reason?: string | null }) {
  return apiPost<AiStatus>(`/api/shops/${encodeURIComponent(shopId)}/enable-ai`, payload);
}

export function disableAi(shopId: string, reason: string, operator = "local_admin") {
  return apiPost<AiStatus>(`/api/shops/${encodeURIComponent(shopId)}/disable-ai`, { operator, reason });
}

export function getWorkerStatus(shopId: string) {
  return apiGet<WorkerStatus>(`/api/shops/${encodeURIComponent(shopId)}/worker-status`);
}
