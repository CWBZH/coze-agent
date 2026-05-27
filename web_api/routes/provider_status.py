from fastapi import APIRouter, Depends

from web_api.deps import get_provider_status_service
from web_api.schemas.provider_status import ProviderStatusResponse
from web_api.services.provider_status_service import ProviderStatusService


router = APIRouter(tags=["provider-status"])


@router.get("/provider-status", response_model=ProviderStatusResponse)
def provider_status(service: ProviderStatusService = Depends(get_provider_status_service)) -> ProviderStatusResponse:
    return service.get_status()
