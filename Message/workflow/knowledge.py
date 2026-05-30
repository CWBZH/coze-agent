"""Read-only knowledge retrieval primitives for workflow engines."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol


@dataclass
class KnowledgeHit:
    source: str
    domain: str
    title: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeRetriever(Protocol):
    def search(self, *, shop_id: str, domain: str, query: str, limit: int = 3) -> list[KnowledgeHit]:
        ...


class ProductKnowledgeRetriever:
    """Simple shop-scoped product retriever.

    This retriever uses deterministic keyword scoring over injected records. It
    remains read-only and shop-scoped, so tests can run without DB access and
    production can provide records from a repository without side effects.
    """

    PRODUCT_DOMAINS = {"product_basic", "product_catalog"}
    MANUAL_FIELD_KEYS = (
        "sku_summary",
        "effect",
        "usage_method",
        "ingredients",
        "shelf_life",
        "warnings",
        "manual_notes",
    )
    SEARCH_FIELDS = (
        "goods_name",
        "specifications",
        "sku_summary",
        "effect",
        "usage_method",
        "ingredients",
        "shelf_life",
        "warnings",
        "manual_notes",
        "fastgpt_question",
        "fastgpt_answer",
        "content",
    )

    def __init__(self, records: Iterable[Any] | None = None, *, min_score: float = 3.0):
        self._records = list(records or [])
        self._min_score = min_score

    def search(self, *, shop_id: str, domain: str, query: str, limit: int = 3) -> list[KnowledgeHit]:
        if not shop_id or not query or limit <= 0:
            return []

        hits: list[KnowledgeHit] = []
        for record in self._records:
            fields = self._extract_fields(record)
            if str(fields.get("shop_id") or "") != str(shop_id):
                continue
            if not self._domain_matches(str(fields.get("domain") or "product_catalog"), domain):
                continue

            score = self._score(query, fields)
            if score < self._min_score:
                continue

            hits.append(
                KnowledgeHit(
                    source=str(fields.get("source") or "product_knowledge"),
                    domain=str(fields.get("domain") or "product_catalog"),
                    title=str(fields.get("goods_name") or "product"),
                    content=self._render_content(fields),
                    score=score,
                    metadata={
                        "goods_id": fields.get("goods_id") or "",
                        "shop_id": fields.get("shop_id") or "",
                        "fields": fields,
                    },
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    @classmethod
    def _domain_matches(cls, record_domain: str, requested_domain: str) -> bool:
        if record_domain == requested_domain:
            return True
        return record_domain in cls.PRODUCT_DOMAINS and requested_domain in cls.PRODUCT_DOMAINS

    def _extract_fields(self, record: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "domain": self._get(record, "domain") or "product_catalog",
            "source": self._get(record, "source") or "product_knowledge",
            "shop_id": self._get(record, "shop_id") or self._get(record, "shop_platform_id"),
            "goods_id": self._get(record, "goods_id"),
            "goods_name": self._get(record, "goods_name"),
            "price": self._get(record, "price"),
            "specifications": self._get(record, "specifications"),
            "fastgpt_question": self._get(record, "fastgpt_question"),
            "fastgpt_answer": self._get(record, "fastgpt_answer"),
            "content": self._get(record, "content") or self._get(record, "rendered_content"),
        }

        manual_attrs = self._manual_attrs(record)
        for key in self.MANUAL_FIELD_KEYS:
            fields[key] = self._get(record, key) or manual_attrs.get(key)
        return fields

    @staticmethod
    def _get(record: Any, key: str) -> Any:
        if isinstance(record, Mapping):
            return record.get(key)
        return getattr(record, key, None)

    def _manual_attrs(self, record: Any) -> dict[str, Any]:
        raw = self._get(record, "raw_detail_json")
        if isinstance(raw, Mapping):
            value = raw
        elif raw:
            try:
                value = json.loads(str(raw))
            except (TypeError, ValueError):
                value = {}
        else:
            value = {}
        attrs = value.get("manual_attributes") if isinstance(value, Mapping) else {}
        return attrs if isinstance(attrs, dict) else {}

    def _score(self, query: str, fields: dict[str, Any]) -> float:
        goods_name = str(fields.get("goods_name") or "")
        if not goods_name or goods_name not in query:
            return 0.0

        score = 8.0
        if self._contains_any(query, ("多少钱", "价格")) and self._has_value(fields, ("price",)):
            score += 4.0
        if self._contains_any(query, ("规格", "多少ml", "多少g")) and self._has_value(
            fields, ("specifications", "sku_summary")
        ):
            score += 4.0
        if self._contains_any(query, ("怎么用", "用法", "使用")) and self._has_value(fields, ("usage_method",)):
            score += 4.0
        if self._contains_any(query, ("成分",)) and self._has_value(fields, ("ingredients",)):
            score += 4.0
        if self._contains_any(query, ("保质期", "多久")) and self._has_value(fields, ("shelf_life",)):
            score += 4.0
        if self._contains_any(query, ("注意", "禁忌")) and self._has_value(fields, ("warnings",)):
            score += 4.0
        if self._contains_any(query, (str(fields.get("fastgpt_question") or ""),)):
            score += 2.0
        return score

    @staticmethod
    def _contains_any(text: str, keywords: Iterable[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)

    @staticmethod
    def _has_value(fields: dict[str, Any], keys: Iterable[str]) -> bool:
        return any(str(fields.get(key) or "").strip() for key in keys)

    def _render_content(self, fields: dict[str, Any]) -> str:
        labels = (
            ("goods_name", "商品名称"),
            ("price", "价格"),
            ("specifications", "规格"),
            ("sku_summary", "规格摘要"),
            ("usage_method", "用法"),
            ("ingredients", "成分"),
            ("shelf_life", "保质期"),
            ("warnings", "注意事项"),
            ("manual_notes", "补充说明"),
            ("fastgpt_answer", "标准回答"),
            ("content", "内容"),
        )
        parts = [f"{label}: {value}" for key, label in labels if (value := str(fields.get(key) or "").strip())]
        return "\n".join(parts)
