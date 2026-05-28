from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProductSyncCreateRequest(BaseModel):
    mode: str = "full"
    operator: str = "local_admin"
    limit: int | None = Field(default=None, ge=1, le=500)


class ProductSyncJobItemResponse(BaseModel):
    id: str
    job_id: str
    shop_id: str
    goods_id: str | None = None
    goods_name: str | None = None
    status: str
    error_summary: str | None = None
    created_at: str
    updated_at: str


class ProductSyncJobResponse(BaseModel):
    id: str
    shop_id: str
    internal_shop_id: int | None = None
    status: str
    mode: str
    total_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    coverage_json: dict[str, Any] | None = None
    error_summary: str | None = None
    created_by: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str


class ProductSyncJobDetailResponse(ProductSyncJobResponse):
    items: list[ProductSyncJobItemResponse] = Field(default_factory=list)


class ProductSyncCoverageResponse(BaseModel):
    shop_id: str
    total: int = 0
    has_price: int = 0
    has_specs: int = 0
    has_usage: int = 0
    has_ingredients: int = 0
    has_shelf_life: int = 0
    has_warnings: int = 0
    has_manual_notes: int = 0
    last_sync_at: str | None = None
    warning: str | None = None
