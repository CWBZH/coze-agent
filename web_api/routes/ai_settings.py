from fastapi import APIRouter, Depends

from web_api.deps import get_ai_settings_service
from web_api.schemas.ai_settings import AiSettingsUpdate
from web_api.services.ai_settings_service import AiSettingsService


router = APIRouter(prefix="/shops/{shop_id}/ai-settings", tags=["ai-settings"])


@router.get("")
def get_ai_settings(shop_id: str, service: AiSettingsService = Depends(get_ai_settings_service)) -> dict:
    return service.get_settings(shop_id).model_dump()


@router.put("")
def update_ai_settings(shop_id: str, payload: AiSettingsUpdate, service: AiSettingsService = Depends(get_ai_settings_service)) -> dict:
    return service.update_settings(shop_id, payload).model_dump()
