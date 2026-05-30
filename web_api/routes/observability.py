from fastapi import APIRouter, Depends, Query

from web_api.deps import get_observability_service
from web_api.services.observability_service import ObservabilityService


router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/conversations")
def list_conversations(
    shop_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: ObservabilityService = Depends(get_observability_service),
) -> dict:
    return service.list_conversations(shop_id=shop_id, limit=limit)


@router.get("/conversations/{buyer_id}/messages")
def list_messages(
    buyer_id: str,
    shop_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: ObservabilityService = Depends(get_observability_service),
) -> dict:
    return service.list_messages(buyer_id, shop_id=shop_id, limit=limit)


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str,
    service: ObservabilityService = Depends(get_observability_service),
) -> dict:
    return service.get_trace(trace_id)
