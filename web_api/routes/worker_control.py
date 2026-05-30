from fastapi import APIRouter, Depends, Query

from web_api.deps import get_shop_onboarding_service, get_worker_control_service
from web_api.errors import ApiError, api_error_response
from web_api.schemas.shop_onboarding import (
    WorkerCommandListResponse,
    WorkerCommandRequest,
    WorkerCommandResponse,
    WorkerStatusResponse,
)
from web_api.services.shop_onboarding_service import ShopOnboardingService
from web_api.services.worker_control_service import WorkerControlService


router = APIRouter(tags=["worker-control"])


@router.post("/shops/{shop_id}/worker/start", response_model=WorkerCommandResponse)
def request_worker_start(
    shop_id: str,
    payload: WorkerCommandRequest,
    service: WorkerControlService = Depends(get_worker_control_service),
):
    try:
        return service.request_start(shop_id, operator=payload.operator, reason=payload.reason)
    except ApiError as exc:
        return api_error_response(exc)


@router.post("/shops/{shop_id}/worker/stop", response_model=WorkerCommandResponse)
def request_worker_stop(
    shop_id: str,
    payload: WorkerCommandRequest,
    service: WorkerControlService = Depends(get_worker_control_service),
):
    try:
        return service.request_stop(shop_id, operator=payload.operator, reason=payload.reason)
    except ApiError as exc:
        return api_error_response(exc)


@router.post("/shops/{shop_id}/worker/restart", response_model=WorkerCommandResponse)
def request_worker_restart(
    shop_id: str,
    payload: WorkerCommandRequest,
    service: WorkerControlService = Depends(get_worker_control_service),
):
    try:
        return service.request_restart(shop_id, operator=payload.operator, reason=payload.reason)
    except ApiError as exc:
        return api_error_response(exc)


@router.get("/shops/{shop_id}/worker/commands", response_model=WorkerCommandListResponse)
def list_worker_commands(
    shop_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    service: WorkerControlService = Depends(get_worker_control_service),
):
    return service.list_commands(shop_id, limit=limit)


@router.get("/worker/events")
def list_worker_events(
    shop_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    service: WorkerControlService = Depends(get_worker_control_service),
):
    return service.list_events(shop_id=shop_id, limit=limit)


@router.get("/shops/{shop_id}/worker-status", response_model=WorkerStatusResponse)
def get_worker_status(
    shop_id: str,
    service: ShopOnboardingService = Depends(get_shop_onboarding_service),
):
    return service.get_worker_status(shop_id)
