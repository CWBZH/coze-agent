from fastapi import APIRouter, Depends

from web_api.deps import get_rag_job_service
from web_api.schemas.rag import RagJobCreate
from web_api.services.rag_job_service import RagJobService


router = APIRouter(prefix="/rag/jobs", tags=["rag-jobs"])


@router.get("")
def list_jobs(service: RagJobService = Depends(get_rag_job_service)) -> dict:
    jobs = service.list_jobs()
    return {"items": [job.model_dump() for job in jobs], "total": len(jobs)}


@router.post("")
def create_job(payload: RagJobCreate, service: RagJobService = Depends(get_rag_job_service)) -> dict:
    return service.create_job(payload).model_dump()
