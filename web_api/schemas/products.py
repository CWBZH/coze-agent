from typing import Any

from pydantic import BaseModel


class ProductSummary(BaseModel):
    goods_id: str
    goods_name: str
    product_title: str
    shop_id: str
    shop_name: str
    version: str
    knowledge_status: str
    indexed_status: str
    updated_at: str
    price: str
    specs: list[str]
    usage: str
    ingredients: str
    shelf_life: str
    warnings: str


class ProductChunk(BaseModel):
    chunk_id: str
    shop_id: str = ""
    domain: str
    source_type: str
    source_id: str = ""
    version: str = ""
    content: str
    content_hash: str = ""
    metadata: dict[str, Any]
    created_at: str = ""
    score: float | None = None


class ProductDetail(ProductSummary):
    manual_notes: str
    raw_detail_json: dict[str, Any]
    chunks: list[ProductChunk]
    warning: str | None = None


class ProductCoverage(BaseModel):
    total: int
    has_price: int
    has_specs: int
    has_usage: int
    has_ingredients: int
    has_shelf_life: int
    has_warnings: int
    has_manual_notes: int
