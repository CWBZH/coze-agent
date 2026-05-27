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
