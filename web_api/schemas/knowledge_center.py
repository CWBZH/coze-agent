from typing import Any

from pydantic import BaseModel


class SopCreate(BaseModel):
    shop_id: str
    domain: str
    title: str
    content: str


class SopUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    expected_content_hash: str | None = None


class ProductOverrideUpdate(BaseModel):
    goods_name: str | None = None
    usage_override: str | None = None
    ingredients_override: str | None = None
    warnings_override: str | None = None
    shelf_life_override: str | None = None
    manual_notes: str | None = None
    specs_override: str | None = None
    price_note_override: str | None = None
    expected_content_hash: str | None = None


class KnowledgeListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class SopPublishResponse(BaseModel):
    sop: dict[str, Any]
    version: dict[str, Any]
    index_job: dict[str, Any]


class IndexRunResponse(BaseModel):
    version: dict[str, Any]
    index_job: dict[str, Any]
    index_mode: str = "fake"
    error_type: str = ""


class IndexRunRequest(BaseModel):
    mode: str = "fake"
    embedding_provider: str = "fake"
    vector_store: str = "none"


class ProductPublishResponse(BaseModel):
    effective: dict[str, Any]
    version: dict[str, Any]
    index_job: dict[str, Any]


class VersionChunk(BaseModel):
    chunk_id: str
    version_id: int | None = None
    shop_id: str = ""
    domain: str = ""
    source_type: str = ""
    source_id: str = ""
    version: str = ""
    content: str = ""
    content_hash: str = ""
    chunk_hash: str = ""
    index_run_id: str = ""
    metadata: dict[str, Any] = {}
    created_at: str = ""


class VersionChunksResponse(BaseModel):
    version_id: int
    source_type: str = ""
    source_id: str = ""
    domain: str = ""
    version: str = ""
    chunks: list[VersionChunk]
    warning: str | None = None
