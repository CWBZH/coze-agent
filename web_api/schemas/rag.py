from pydantic import BaseModel
from typing import Any


class RagJob(BaseModel):
    job_id: str
    shop_id: str
    source_type: str
    domain: str
    version: str
    status: str
    chunk_count: int
    embedded_count: int
    indexed_count: int
    error_summary: str | None = None
    created_at: str
    finished_at: str | None = None
    dry_run: bool = True
    calls_ollama: bool = False
    connects_pgvector: bool = False


class RagJobCreate(BaseModel):
    shop_id: str
    source_type: str
    domain: str
    version: str = "draft"
    dry_run: bool = True


class RagDebugRequest(BaseModel):
    shop_id: str
    query: str
    domain: str = "product_catalog"
    version: str = "real-product-v1"
    top_k: int = 5
    goods_id: str | None = None


class RagDebugHit(BaseModel):
    chunk_id: str
    content: str
    score: float
    domain: str
    source_type: str
    source_id: str
    version: str
    metadata: dict[str, Any]


class RagDebugResponse(BaseModel):
    query: str
    shop_id: str
    domain: str
    version: str
    hits: list[RagDebugHit]
    connects_pgvector: bool = False
    calls_ollama: bool = False
    warning: str | None = None
