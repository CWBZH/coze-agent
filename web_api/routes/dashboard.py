from fastapi import APIRouter, Depends

from web_api.deps import get_dashboard_service
from web_api.services.dashboard_service import DashboardService


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary(service: DashboardService = Depends(get_dashboard_service)) -> dict:
    return service.summary().model_dump()
