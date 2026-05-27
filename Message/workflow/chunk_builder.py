"""Build sanitized RAG chunks from product records and SOP records."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .rag_types import KnowledgeChunk, stable_content_hash
from .sop_loader import SopRecord


PRICE_BOUNDARY = "价格仅供参考，最终以商品页面/结算页为准。"


def build_product_chunks(
    records: Iterable[Any],
    *,
    version: str = "product-v1",
    domain: str = "product_catalog",
    index_run_id: str = "",
    namespace: str = "acceptance",
    is_test_data: bool = False,
    created_by: str = "internal_rag_index",
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for record in records:
        fields = _extract_record(record)
        shop_id = fields.get("shop_id") or fields.get("shop_platform_id") or ""
        if not shop_id:
            continue
        source_id = fields.get("goods_id") or stable_content_hash(str(fields))[:16]
        title = fields.get("goods_name") or "product"
        price_text = _price_text(fields)
        field_flags = _field_flags(fields, price_text=price_text)
        content_lines = [
            f"Product: {title}",
            _line("Goods ID", source_id),
            _line("Specifications", fields.get("specifications")),
            _line("Usage", fields.get("usage_method")),
            _line("Ingredients", fields.get("ingredients")),
            _line("Shelf life", fields.get("shelf_life")),
            _line("Warnings", fields.get("warnings")),
            _line("Manual notes", fields.get("manual_notes")),
            _line("Standard answer", fields.get("fastgpt_answer")),
            _line("Price reference", price_text),
            PRICE_BOUNDARY,
        ]
        content = "\n".join(line for line in content_lines if line).strip()
        if not content:
            continue
        chunk_domain = str(domain or "product_catalog")
        chunk_id = f"product:{shop_id}:{chunk_domain}:{source_id}:{stable_content_hash(content)[:12]}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                shop_id=str(shop_id),
                domain=chunk_domain,
                source_type="product",
                source_id=str(source_id),
                title=str(title),
                content=content[:4000],
                version=version,
                metadata={
                    "goods_id": str(source_id),
                    "domain": chunk_domain,
                    "source_table": fields.get("source_table") or "product_knowledge",
                    "knowledge_status": fields.get("knowledge_status") or "",
                    "version": version,
                    "field_flags": field_flags,
                    **_lifecycle_metadata(
                        index_run_id=index_run_id,
                        namespace=namespace,
                        is_test_data=is_test_data,
                        created_by=created_by,
                    ),
                },
            )
        )
    return chunks


def build_sop_chunks(
    records: Iterable[SopRecord],
    *,
    index_run_id: str = "",
    namespace: str = "acceptance",
    is_test_data: bool = False,
    created_by: str = "internal_rag_index",
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for record in records:
        if not record.shop_id or not record.domain:
            continue
        content = "\n".join(
            [
                f"Title: {record.title}",
                "Intent examples: " + "; ".join(record.intent_examples),
                "Approved answer: " + record.approved_answer,
                "Forbidden phrases: " + "; ".join(record.forbidden_phrases),
                f"Transfer human: {record.should_transfer_human}",
                f"Risk level: {record.risk_level}",
            ]
        )
        chunk_id = f"sop:{record.shop_id}:{record.domain}:{record.kb_item_id}:{record.content_hash[:12]}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                shop_id=record.shop_id,
                domain=record.domain,
                source_type="sop",
                source_id=record.kb_item_id,
                title=record.title,
                content=content[:4000],
                version=record.version,
                metadata={
                    "kb_item_id": record.kb_item_id,
                    "risk_level": record.risk_level,
                    "should_transfer_human": record.should_transfer_human,
                    **_lifecycle_metadata(
                        index_run_id=index_run_id,
                        namespace=namespace,
                        is_test_data=is_test_data,
                        created_by=created_by,
                    ),
                },
            )
        )
    return chunks


def _lifecycle_metadata(*, index_run_id: str, namespace: str, is_test_data: bool, created_by: str) -> dict[str, Any]:
    return {
        "index_run_id": str(index_run_id or ""),
        "namespace": str(namespace or "acceptance"),
        "is_test_data": bool(is_test_data),
        "created_by": str(created_by or "internal_rag_index"),
    }


def _extract_record(record: Any) -> dict[str, str]:
    if isinstance(record, Mapping):
        return {str(key): str(value or "") for key, value in record.items()}
    keys = (
        "shop_id",
        "shop_platform_id",
        "goods_id",
        "goods_name",
        "price",
        "price_min",
        "price_max",
        "specifications",
        "usage_method",
        "ingredients",
        "shelf_life",
        "warnings",
        "manual_notes",
        "fastgpt_answer",
        "knowledge_status",
        "source_table",
    )
    return {key: str(getattr(record, key, "") or "") for key in keys}


def _line(label: str, value: object) -> str:
    text = str(value or "").strip()
    return f"{label}: {text}" if text else ""


def _price_text(fields: Mapping[str, str]) -> str:
    price = str(fields.get("price") or "").strip()
    if price:
        return price
    price_min = str(fields.get("price_min") or "").strip()
    price_max = str(fields.get("price_max") or "").strip()
    if price_min and price_max and price_min != price_max:
        return f"{price_min}-{price_max}"
    return price_min or price_max


def _field_flags(fields: Mapping[str, str], *, price_text: str) -> dict[str, bool]:
    return {
        "has_goods_name": bool(str(fields.get("goods_name") or "").strip()),
        "has_goods_id": bool(str(fields.get("goods_id") or "").strip()),
        "has_specifications": bool(str(fields.get("specifications") or "").strip()),
        "has_price_boundary": True,
        "has_usage": bool(str(fields.get("usage_method") or "").strip()),
        "has_ingredients": bool(str(fields.get("ingredients") or "").strip()),
        "has_shelf_life": bool(str(fields.get("shelf_life") or "").strip()),
        "has_warnings": bool(str(fields.get("warnings") or "").strip()),
        "has_manual_notes": bool(str(fields.get("manual_notes") or "").strip()),
        "has_price": bool(str(price_text or "").strip()),
    }
