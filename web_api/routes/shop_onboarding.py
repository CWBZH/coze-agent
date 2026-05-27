from fastapi import APIRouter, Depends, HTTPException

from web_api.deps import get_shop_onboarding_service
from web_api.schemas.shop_onboarding import (
    AuthStatusResponse,
    CaptchaSubmitRequest,
    CheckLoginResponse,
    OnboardingCreateRequest,
    OnboardingSessionResponse,
    SmsCodeSubmitRequest,
)
from web_api.services.shop_onboarding_service import ShopOnboardingService


router = APIRouter(tags=["shop-onboarding"])


@router.post("/shops/onboarding", response_model=OnboardingSessionResponse)
def create_onboarding_session(
    payload: OnboardingCreateRequest,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.create_session(
            payload.platform,
            payload.account_name,
            payload.shop_name,
            payload.password,
            payload.operator,
            payload.runner_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@router.get("/shops/onboarding/{session_id}", response_model=OnboardingSessionResponse)
def get_onboarding_session(
    session_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"}) from exc


@router.post("/shops/onboarding/{session_id}/submit-sms-code", response_model=OnboardingSessionResponse)
def submit_sms_code(
    session_id: str,
    payload: SmsCodeSubmitRequest,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.submit_sms_code(session_id, payload.sms_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"}) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=400, detail={"error": "session_expired"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@router.post("/shops/onboarding/{session_id}/submit-captcha", response_model=OnboardingSessionResponse)
def submit_captcha(
    session_id: str,
    payload: CaptchaSubmitRequest,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.submit_captcha(session_id, payload.captcha_code)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail={"error": "unsupported_captcha_flow"}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"}) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=400, detail={"error": "session_expired"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@router.post("/shops/onboarding/{session_id}/cancel", response_model=OnboardingSessionResponse)
def cancel_onboarding_session(
    session_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.cancel_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"}) from exc


@router.post("/shops/onboarding/{session_id}/check-login", response_model=CheckLoginResponse)
def check_remote_browser_login(
    session_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.check_remote_browser_login(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"}) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=400, detail={"error": "session_expired"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@router.get("/shops/{shop_id}/auth-status", response_model=AuthStatusResponse)
def get_shop_auth_status(
    shop_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.get_auth_status(shop_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "auth_not_found"}) from exc
