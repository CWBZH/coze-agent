from pydantic import BaseModel, Field


class OnboardingCreateRequest(BaseModel):
    platform: str = "pdd"
    shop_name: str
    account_name: str
    password: str | None = Field(default=None, repr=False)
    operator: str = "local_admin"
    runner_mode: str = "fake"


class OnboardingSessionResponse(BaseModel):
    session_id: str
    platform: str
    shop_id: str | None = None
    shop_name: str | None = None
    safe_display: str = ""
    runner_mode: str = "fake"
    status: str
    step: str
    needs_sms_code: bool = False
    needs_captcha: bool = False
    captcha_image_ref: str | None = None
    error_summary: str | None = None
    created_at: str
    updated_at: str
    expires_at: str
    completed_at: str | None = None
    cancelled_at: str | None = None
    remote_browser_available: bool = False
    remote_browser_status: str | None = None
    vnc_url_ready: bool = False
    vnc_url: str | None = None
    real_shop_id_pending: bool = False


class SmsCodeSubmitRequest(BaseModel):
    sms_code: str = Field(min_length=1, max_length=12, repr=False)


class CaptchaSubmitRequest(BaseModel):
    captcha_code: str = Field(min_length=1, max_length=32, repr=False)


class CheckLoginResponse(OnboardingSessionResponse):
    pass


class AuthStatusResponse(BaseModel):
    shop_id: str
    platform: str
    account_name: str | None = None
    auth_status: str
    safe_display: str = ""
    last_login_at: str | None = None
    expires_at: str | None = None
    insecure_auth_storage: bool = False


class ChecklistItem(BaseModel):
    key: str
    label: str
    status: str
    required: bool
    summary: str


class OnboardingChecklistResponse(BaseModel):
    shop_id: str
    ready_for_ai: bool
    blocking_items: list[str]
    items: list[ChecklistItem]


class ValidationMarkPassedRequest(BaseModel):
    operator: str = "local_admin"
    summary: str = ""


class ValidationRunResponse(BaseModel):
    id: str
    shop_id: str
    status: str
    mode: str = "no_send"
    passed_count: int = 0
    failed_count: int = 0
    tested_at: str
    created_by: str
    summary: str = ""


class EnableAiRequest(BaseModel):
    operator: str = "local_admin"
    confirm: bool = False
    override: bool = False
    override_reason: str | None = None


class DisableAiRequest(BaseModel):
    operator: str = "local_admin"
    reason: str = "manual_disable"


class AiStatusResponse(BaseModel):
    shop_id: str
    ai_enabled: bool
    enabled_at: str | None = None
    enabled_by: str | None = None
    disabled_at: str | None = None
    disabled_by: str | None = None
    last_change_reason: str | None = None
    override_enabled: bool = False
    override_reason: str | None = None


class WorkerStatusResponse(BaseModel):
    shop_id: str
    status: str
    process_id: int | None = None
    last_seen_at: str | None = None
    websocket_status: str
    summary: str
    ai_enabled: bool = False
    consistency_status: str = "unknown"
    attention_required: bool = False
    recommended_action: str | None = None
