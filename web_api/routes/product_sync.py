from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from web_api.errors import ApiError, api_error_response
from web_api.errors import standard_error_payload
from web_api.deps import get_product_sync_service
from web_api.schemas.product_sync import (
    ProductSyncCoverageResponse,
    ProductSyncCreateRequest,
    ProductSyncJobDetailResponse,
    ProductSyncJobResponse,
)
from web_api.services.product_sync_service import ProductSyncService


router = APIRouter(prefix="/shops/{shop_id}/product-sync", tags=["product-sync"])


@router.post("/jobs", response_model=ProductSyncJobDetailResponse)
def create_product_sync_job(
    shop_id: str,
    payload: ProductSyncCreateRequest,
    service: ProductSyncService = Depends(get_product_sync_service),
) -> dict:
    try:
        return service.create_job(shop_id, mode=payload.mode, operator=payload.operator, limit=payload.limit)
    except ApiError as exc:
        return api_error_response(exc)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"}) from exc
    except ValueError as exc:
        if str(exc) == "auth_required":
            return JSONResponse(
                status_code=409,
                content=standard_error_payload(
                    "AUTH_REQUIRED",
                    "当前店铺没有可用授权，无法同步商品。",
                    retryable=False,
                    next_action="请先完成店铺登录授权。",
                ),
            )
        raise HTTPException(status_code=400, detail={"error": "product_sync_failed"}) from exc


@router.get("/jobs", response_model=list[ProductSyncJobResponse])
def list_product_sync_jobs(
    shop_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    service: ProductSyncService = Depends(get_product_sync_service),
) -> list[dict]:
    return service.list_jobs(shop_id, limit=limit)


@router.get("/jobs/{job_id}", response_model=ProductSyncJobDetailResponse)
def get_product_sync_job(
    shop_id: str,
    job_id: str,
    service: ProductSyncService = Depends(get_product_sync_service),
) -> dict:
    try:
        return service.get_job(shop_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"}) from exc


@router.post("/jobs/{job_id}/retry", response_model=ProductSyncJobDetailResponse)
def retry_product_sync_job(
    shop_id: str,
    job_id: str,
    service: ProductSyncService = Depends(get_product_sync_service),
) -> dict:
    try:
        return service.retry_failed_items(shop_id, job_id)
    except ApiError as exc:
        return api_error_response(exc)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"}) from exc


@router.get("/coverage", response_model=ProductSyncCoverageResponse)
def get_product_sync_coverage(
    shop_id: str,
    service: ProductSyncService = Depends(get_product_sync_service),
) -> dict:
    return service.coverage(shop_id)
