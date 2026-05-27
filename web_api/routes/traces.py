from fastapi import APIRouter, Depends

from web_api.deps import get_trace_service
from web_api.services.trace_service import TraceService


router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("")
def list_traces(service: TraceService = Depends(get_trace_service)) -> dict:
    traces = service.list_traces()
    return {"items": [trace.model_dump() for trace in traces], "total": len(traces)}


@router.get("/{trace_id}")
def get_trace(trace_id: str, service: TraceService = Depends(get_trace_service)) -> dict:
    return service.get_trace(trace_id)
