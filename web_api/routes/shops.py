from fastapi import APIRouter, Depends

from web_api.deps import get_shop_service
from web_api.services.shop_service import ShopService


router = APIRouter(prefix="/shops", tags=["shops"])


@router.get("")
def list_shops(service: ShopService = Depends(get_shop_service)) -> dict:
    items, warning = service.list_shops()
    payload = {"items": [item.model_dump() for item in items], "total": len(items)}
    if warning:
        payload["warning"] = warning
    return payload


@router.get("/{shop_id}")
def get_shop(shop_id: str, service: ShopService = Depends(get_shop_service)) -> dict:
    return service.get_shop(shop_id).model_dump()
