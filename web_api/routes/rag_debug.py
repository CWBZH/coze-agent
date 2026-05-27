from fastapi import APIRouter, Depends

from web_api.deps import get_rag_debug_service
from web_api.schemas.rag import RagDebugRequest
from web_api.services.rag_debug_service import RagDebugService


router = APIRouter(prefix="/rag", tags=["rag-debug"])


@router.post("/retrieve-debug")
def retrieve_debug(payload: RagDebugRequest, service: RagDebugService = Depends(get_rag_debug_service)) -> dict:
    return service.retrieve_debug(payload).model_dump()
