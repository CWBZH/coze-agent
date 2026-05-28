from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from web_api.errors import ApiError, api_error_response
from web_api.deps import get_knowledge_center_service
from web_api.schemas.knowledge_center import (
    IndexRunRequest,
    IndexRunResponse,
    KnowledgeListResponse,
    ProductOverrideUpdate,
    ProductPublishResponse,
    SopCreate,
    SopPublishResponse,
    SopUpdate,
    VersionChunksResponse,
)
from web_api.services.knowledge_center_service import KnowledgeCenterService, empty_product_override
from web_api.services.shop_identity import assert_real_shop_id_bound


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/sop", response_model=KnowledgeListResponse)
def list_sop(
    shop_id: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    items = service.list_sop(shop_id=shop_id, domain=domain, status=status)
    return {"items": items, "total": len(items)}


@router.post("/sop")
def create_sop(payload: SopCreate, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    return service.create_sop(payload.shop_id, payload.domain, payload.title, payload.content)


@router.get("/sop/{sop_id}")
def get_sop(sop_id: int, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    try:
        return service.get_sop(sop_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.put("/sop/{sop_id}")
def update_sop(sop_id: int, payload: SopUpdate, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    try:
        current = service.get_sop(sop_id)
        if payload.expected_content_hash and payload.expected_content_hash != current["content_hash"]:
            raise HTTPException(
                status_code=409,
                detail={"status": "conflict", "current_content_hash": current["content_hash"]},
            )
        return service.update_sop(sop_id, title=payload.title, content=payload.content)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.delete("/sop/{sop_id}")
def archive_sop(sop_id: int, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    try:
        return service.archive_sop(sop_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.post("/sop/{sop_id}/publish", response_model=SopPublishResponse)
def publish_sop(sop_id: int, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    try:
        sop = service.get_sop(sop_id)
        assert_real_shop_id_bound(sop["shop_id"])
        result = service.publish_sop(sop["shop_id"], sop_id)
        return {"sop": sop, "version": result["version"], "index_job": result["job"]}
    except ApiError as exc:
        return api_error_response(exc)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.get("/products/{goods_id}/overrides")
def get_product_override(
    goods_id: str,
    shop_id: str,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    override = service.get_override(shop_id, goods_id)
    return override or empty_product_override(shop_id, goods_id)


@router.put("/products/{goods_id}/overrides")
def upsert_product_override(
    goods_id: str,
    shop_id: str,
    payload: ProductOverrideUpdate,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    current = service.get_override(shop_id, goods_id)
    if payload.expected_content_hash and payload.expected_content_hash != (current or {}).get("content_hash", ""):
        raise HTTPException(
            status_code=409,
            detail={"status": "conflict", "current_content_hash": (current or {}).get("content_hash", "")},
        )
    data = payload.model_dump(exclude={"expected_content_hash"})
    return service.upsert_override(shop_id, goods_id, **data)


@router.get("/products/{goods_id}/effective")
def get_effective_product(
    goods_id: str,
    shop_id: str,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    try:
        return service.build_effective_product_knowledge(shop_id, goods_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.post("/products/{goods_id}/publish", response_model=ProductPublishResponse)
def publish_product(
    goods_id: str,
    shop_id: str,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    try:
        assert_real_shop_id_bound(shop_id)
        result = service.publish_product(shop_id, goods_id)
        return {"effective": result["effective"], "version": result["version"], "index_job": result["job"]}
    except ApiError as exc:
        return api_error_response(exc)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.get("/versions", response_model=KnowledgeListResponse)
def list_versions(
    shop_id: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    is_active: bool | None = None,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    items = service.list_versions(
        shop_id=shop_id,
        source_type=source_type,
        source_id=source_id,
        domain=domain,
        status=status,
        is_active=is_active,
    )
    return {"items": items, "total": len(items)}


@router.get("/versions/{version_id}")
def get_version(version_id: int, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    try:
        return service.get_version(version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.get("/versions/{version_id}/chunks", response_model=VersionChunksResponse)
def get_version_chunks(
    version_id: int,
    limit: int = 20,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    try:
        return service.list_version_chunks(version_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.get("/index-jobs", response_model=KnowledgeListResponse)
def list_index_jobs(
    shop_id: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    version_id: int | None = None,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    items = service.list_index_jobs(
        shop_id=shop_id,
        status=status,
        source_type=source_type,
        source_id=source_id,
        version_id=version_id,
    )
    return {"items": items, "total": len(items)}


@router.get("/index-jobs/{job_id}")
def get_index_job(job_id: int, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    try:
        return service.get_index_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.post("/index-jobs/{job_id}/run", response_model=IndexRunResponse)
def run_index_job(
    job_id: int,
    payload: IndexRunRequest | None = None,
    mode: str | None = None,
    embedding_provider: str | None = None,
    vector_store: str | None = None,
    service: KnowledgeCenterService = Depends(get_knowledge_center_service),
) -> dict[str, Any]:
    try:
        options = payload or IndexRunRequest()
        return service.run_index_job(
            job_id,
            mode=mode or options.mode,
            embedding_provider=embedding_provider or options.embedding_provider,
            vector_store_provider=vector_store or options.vector_store,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"status": "not_runnable", "error_type": str(exc).split(":")[0]}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail={"status": "failed", "error_type": str(exc).split(":")[0]}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc


@router.post("/index-jobs/{job_id}/retry")
def retry_index_job(job_id: int, service: KnowledgeCenterService = Depends(get_knowledge_center_service)) -> dict[str, Any]:
    try:
        return service.retry_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"status": "not_retryable", "error_type": str(exc).split(":")[0]}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"status": "not_found"}) from exc
