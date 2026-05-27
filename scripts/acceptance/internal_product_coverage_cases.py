"""Product RAG coverage case generation.

Cases may contain retrieval queries, but serialized output is metadata-only.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


DEFAULT_SHOP_ID = "synthetic-shop-1"
DEFAULT_PRODUCT_VERSION = "real-product-v1"
DEFAULT_PRODUCT_DOMAIN = "product_catalog"


@dataclass(frozen=True)
class ProductCoverageCase:
    case_id: str
    shop_id: str
    goods_id_hash: str
    title_masked: str
    query: str
    expected_domain: str
    expected_version: str
    expected_source_type: str
    expected_field: str
    expected_min_hits: int = 1
    priority: str = "P1"
    notes: str = ""


def fake_product_records(shop_id: str = DEFAULT_SHOP_ID) -> list[dict[str, str]]:
    return [
        {
            "shop_id": shop_id,
            "goods_id": "synthetic-product-1",
            "goods_name": "Synthetic Product",
            "price": "99",
            "specifications": "100ml",
            "usage_method": "Use a small amount after cleaning.",
            "ingredients": "Synthetic ingredient list.",
            "shelf_life": "24 months.",
            "warnings": "Check the product page and consult support for sensitive groups.",
            "manual_notes": "Synthetic record for no-send product coverage.",
            "source_table": "product_knowledge",
        }
    ]


def build_cases_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    shop_id: str = DEFAULT_SHOP_ID,
    version: str = DEFAULT_PRODUCT_VERSION,
    domain: str = DEFAULT_PRODUCT_DOMAIN,
    limit: int = 50,
) -> list[ProductCoverageCase]:
    cases: list[ProductCoverageCase] = []
    max_cases = max(0, int(limit or 0))
    for index, raw in enumerate(records, start=1):
        record = {str(key): str(value or "") for key, value in dict(raw).items() if str(key) != "raw_detail_json"}
        goods_id = record.get("goods_id") or f"record-{index}"
        title = record.get("goods_name") or "product"
        definitions = _case_definitions(record, goods_id=goods_id, title=title)
        for kind, query, field in definitions:
            if len(cases) >= max_cases:
                return cases
            if not query:
                continue
            cases.append(
                ProductCoverageCase(
                    case_id=f"product-coverage-{index:03d}-{kind}",
                    shop_id=shop_id,
                    goods_id_hash=_hash(goods_id),
                    title_masked=_mask_title(title),
                    query=query,
                    expected_domain=domain,
                    expected_version=version,
                    expected_source_type="product",
                    expected_field=field,
                    expected_min_hits=1,
                    priority="P1",
                )
            )
    return cases


def _case_definitions(record: Mapping[str, str], *, goods_id: str, title: str) -> list[tuple[str, str, str]]:
    base = goods_id or title
    definitions = [
        ("by_goods_id", f"{base} 商品信息", "has_goods_id"),
        ("by_goods_name", f"{title} 商品信息", "has_goods_name"),
        ("price_query", f"{base} 多少钱", "has_price_boundary"),
        ("generic_product_query", f"{base} 商品咨询", "has_price_boundary"),
    ]
    optional_fields = [
        ("specifications", "spec_query", f"{base} 有哪些规格", "has_specifications"),
        ("usage_method", "usage_query", f"{base} 怎么用", "has_usage"),
        ("ingredients", "ingredient_query", f"{base} 有什么成分", "has_ingredients"),
        ("shelf_life", "shelf_life_query", f"{base} 保质期多久", "has_shelf_life"),
        ("warnings", "warning_query", f"{base} 有什么注意事项", "has_warnings"),
        ("warnings", "audience_query", f"{base} 适用人群和注意事项", "has_warnings"),
    ]
    for field, kind, query, expected_flag in optional_fields:
        if str(record.get(field) or "").strip():
            definitions.append((kind, query, expected_flag))
    return definitions


def _hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16] if value else ""


def _mask_title(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if len(text) <= 4:
        return text[0] + "***"
    return text[:2] + "***" + text[-1:]
