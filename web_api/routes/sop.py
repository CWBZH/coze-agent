from fastapi import APIRouter, Depends, HTTPException

from web_api.deps import get_sop_service
from web_api.schemas.sop import SopCreate, SopUpdate
from web_api.services.sop_service import SopService


router = APIRouter(prefix="/sop", tags=["sop"])


@router.get("")
def list_sop(shop_id: str | None = None, domain: str | None = None, status: str | None = None, service: SopService = Depends(get_sop_service)) -> dict:
    records = service.list_records(shop_id, domain, status)
    return {"items": [record.model_dump() for record in records], "total": len(records)}


@router.get("/{record_id}")
def get_sop(record_id: str, service: SopService = Depends(get_sop_service)) -> dict:
    try:
        return service.get_record(record_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SOP not found") from exc


@router.post("")
def create_sop(payload: SopCreate, service: SopService = Depends(get_sop_service)) -> dict:
    return service.create_record(payload).model_dump()


@router.put("/{record_id}")
def update_sop(record_id: str, payload: SopUpdate, service: SopService = Depends(get_sop_service)) -> dict:
    try:
        return service.update_record(record_id, payload).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SOP not found") from exc


@router.post("/{record_id}/publish")
def publish_sop(record_id: str, service: SopService = Depends(get_sop_service)) -> dict:
    try:
        return service.publish(record_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SOP not found") from exc
