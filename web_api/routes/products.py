from fastapi import APIRouter, Depends, Query

from web_api.deps import get_product_service, get_rag_debug_service
from web_api.services.product_service import ProductService
from web_api.services.rag_debug_service import RagDebugService


router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(
    shop_id: str | None = None,
    q: str | None = None,
    version: str | None = None,
    indexed_status: str | None = None,
    include_archived: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: ProductService = Depends(get_product_service),
) -> dict:
    items, total, warning = service.list_products(shop_id, q, version, indexed_status, page, page_size, include_archived)
    payload = {"items": [item.model_dump() for item in items], "total": total, "page": page, "page_size": page_size}
    if warning:
        payload["warning"] = warning
    return payload


@router.get("/coverage")
def product_coverage(shop_id: str | None = None, service: ProductService = Depends(get_product_service)) -> dict:
    coverage, warning = service.coverage(shop_id=shop_id)
    payload = coverage.model_dump()
    if warning:
        payload["warning"] = warning
    return payload


@router.get("/{goods_id}/chunks")
def get_product_chunks(
    goods_id: str,
    shop_id: str | None = None,
    version: str | None = None,
    domain: str | None = None,
    source_type: str | None = "product",
    limit: int = 20,
    service: RagDebugService = Depends(get_rag_debug_service),
) -> dict:
    chunks, warning = service.list_product_chunks(
        goods_id=goods_id,
        shop_id=shop_id,
        version=version,
        domain=domain,
        source_type=source_type,
        limit=limit,
    )
    return {
        "goods_id": goods_id,
        "shop_id": shop_id or "",
        "version": version or "",
        "chunks": [chunk.model_dump() for chunk in chunks],
        "warning": warning,
    }


@router.get("/{goods_id}")
def get_product(
    goods_id: str,
    shop_id: str | None = None,
    include_archived: bool = False,
    service: ProductService = Depends(get_product_service),
) -> dict:
    return service.get_product(goods_id, shop_id=shop_id, include_archived=include_archived).model_dump()
