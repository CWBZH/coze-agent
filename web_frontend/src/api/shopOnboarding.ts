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
};

export type CreateOnboardingPayload = {
  platform: "pdd";
  shop_name: string;
  account_name: string;
  password?: string;
  operator?: string;
  runner_mode?: "fake" | "real" | "remote_browser";
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

export function getShopAuthStatus(shopId: string) {
  return apiGet<AuthStatus>(`/api/shops/${encodeURIComponent(shopId)}/auth-status`);
}
