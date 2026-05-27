from fastapi import APIRouter, Depends, HTTPException, Query

from web_api.deps import get_human_lock_service
from web_api.schemas.human_locks import (
    HumanLockBatchUnlockResponse,
    HumanLockBulkUnlockRequest,
    HumanLockListResponse,
    HumanLockUnlockBySessionRequest,
    HumanLockUnlockRequest,
    HumanLockUnlockResponse,
)
from web_api.services.human_lock_service import HumanLockService


router = APIRouter(prefix="/human-locks", tags=["human-locks"])


@router.get("", response_model=HumanLockListResponse)
def list_human_locks(
    shop_id: str | None = None,
    buyer_id: str | None = None,
    session_id: str | None = None,
    status: str = "pending_human",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: HumanLockService = Depends(get_human_lock_service),
) -> dict:
    try:
        result = service.list_locks(
            shop_id=shop_id,
            buyer_id=buyer_id,
            session_id=session_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"items": result.items, "total": result.total, "shop_id": shop_id or "", "warning": result.warning}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@router.post("/{lock_id}/unlock", response_model=HumanLockUnlockResponse)
def unlock_human_lock(
    lock_id: str,
    payload: HumanLockUnlockRequest,
    service: HumanLockService = Depends(get_human_lock_service),
) -> dict:
    try:
        return service.unlock_lock(
            lock_id,
            shop_id=payload.shop_id,
            operator=payload.operator,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "not_found"}) from exc
    except (FileNotFoundError, LookupError) as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc


@router.post("/unlock-by-session", response_model=HumanLockBatchUnlockResponse)
def unlock_human_locks_by_session(
    payload: HumanLockUnlockBySessionRequest,
    service: HumanLockService = Depends(get_human_lock_service),
) -> dict:
    try:
        return service.unlock_by_session(
            shop_id=payload.shop_id,
            buyer_id=payload.buyer_id,
            session_id=payload.session_id,
            operator=payload.operator,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except (FileNotFoundError, LookupError) as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc


@router.post("/bulk-unlock", response_model=HumanLockBatchUnlockResponse)
def bulk_unlock_human_locks(
    payload: HumanLockBulkUnlockRequest,
    service: HumanLockService = Depends(get_human_lock_service),
) -> dict:
    try:
        return service.bulk_unlock(
            shop_id=payload.shop_id,
            operator=payload.operator,
            reason=payload.reason,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except (FileNotFoundError, LookupError) as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
