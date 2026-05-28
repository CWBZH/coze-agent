from fastapi import APIRouter, Depends, HTTPException

from web_api.errors import ApiError, api_error_response
from web_api.deps import get_shop_onboarding_service
from web_api.schemas.shop_onboarding import (
    AiStatusResponse,
    AuthStatusResponse,
    BindShopIdentityRequest,
    CaptchaSubmitRequest,
    CheckLoginResponse,
    DisableAiRequest,
    EnableAiRequest,
    OnboardingCreateRequest,
    OnboardingChecklistResponse,
    OnboardingSessionResponse,
    SmsCodeSubmitRequest,
    ValidationMarkPassedRequest,
    ValidationRunResponse,
    WorkerStatusResponse,
)
from web_api.services.shop_onboarding_service import ChecklistNotReadyError, ShopOnboardingService


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


@router.post("/shops/onboarding/{session_id}/bind-shop-identity", response_model=OnboardingSessionResponse)
def bind_shop_identity(
    session_id: str,
    payload: BindShopIdentityRequest,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.bind_shop_identity(
            session_id,
            mall_id=payload.mall_id,
            shop_name=payload.shop_name,
            operator=payload.operator,
        )
    except ApiError as exc:
        return api_error_response(exc)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"}) from exc
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


@router.get("/shops/{shop_id}/onboarding-checklist", response_model=OnboardingChecklistResponse)
def get_onboarding_checklist(
    shop_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    return service.get_onboarding_checklist(shop_id)


@router.post("/shops/{shop_id}/onboarding-validation/mark-passed", response_model=ValidationRunResponse)
def mark_onboarding_validation_passed(
    shop_id: str,
    payload: ValidationMarkPassedRequest,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    return service.mark_no_send_validation_passed(shop_id, operator=payload.operator, summary=payload.summary)


@router.post("/shops/{shop_id}/enable-ai", response_model=AiStatusResponse)
def enable_shop_ai(
    shop_id: str,
    payload: EnableAiRequest,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    try:
        return service.enable_ai(
            shop_id,
            operator=payload.operator,
            confirm=payload.confirm,
            override=payload.override,
            override_reason=payload.override_reason,
        )
    except ApiError as exc:
        return api_error_response(exc)
    except ChecklistNotReadyError as exc:
        raise HTTPException(status_code=409, detail={"error": "checklist_not_ready", "blocking_items": exc.blocking_items}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@router.post("/shops/{shop_id}/disable-ai", response_model=AiStatusResponse)
def disable_shop_ai(
    shop_id: str,
    payload: DisableAiRequest,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    return service.disable_ai(shop_id, operator=payload.operator, reason=payload.reason)


@router.get("/shops/{shop_id}/ai-status", response_model=AiStatusResponse)
def get_shop_ai_status(
    shop_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    return service.get_ai_status(shop_id)


@router.get("/shops/{shop_id}/worker-status", response_model=WorkerStatusResponse)
def get_shop_worker_status(
    shop_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
) -> dict:
    return service.get_worker_status(shop_id)
