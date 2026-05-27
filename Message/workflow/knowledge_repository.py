"""Read-only product knowledge repository for internal workflow retrieval."""
from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any


logger = logging.getLogger(__name__)


class ProductKnowledgeRepository:
    """Load shop-scoped product knowledge records for ProductKnowledgeRetriever.

    The repository is intentionally read-only. Callers may inject a plain records
    source for tests, a close-only SQLAlchemy session provider, or a db_manager
    exposing get_session().
    """

    MANUAL_FIELD_KEYS = (
        "sku_summary",
        "effect",
        "usage_method",
        "ingredients",
        "shelf_life",
        "warnings",
        "manual_notes",
    )
    DEFAULT_CACHE_TTL_SECONDS = 300.0
    CACHE_TTL_ENV_VAR = "AI_WORKFLOW_PRODUCT_CACHE_TTL_SECONDS"

    def __init__(
        self,
        *,
        records_source: Iterable[Any] | Callable[[str], Iterable[Any]] | None = None,
        session_provider: Callable[[], Any] | None = None,
        db_manager: Any | None = None,
        ttl_seconds: float | None = None,
        time_provider: Callable[[], float] | None = None,
        enable_cache: bool = True,
    ):
        if sum(value is not None for value in (records_source, session_provider, db_manager)) > 1:
            raise ValueError("Inject only one of records_source, session_provider, or db_manager")
        self._records_source = records_source
        self._session_provider = session_provider
        self._db_manager = db_manager
        self._ttl_seconds = self._resolve_cache_ttl_seconds(ttl_seconds)
        self._time_provider = time_provider or time.monotonic
        self._enable_cache = enable_cache
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._last_stats: dict[str, Any] | None = None

    def load_records(self, *, shop_id: str) -> list[dict[str, Any]]:
        return self.load_shop_products(shop_id)

    def load_shop_products(self, shop_id: str | None) -> list[dict[str, Any]]:
        normalized_shop_id = str(shop_id or "").strip()
        if not normalized_shop_id:
            return []

        cached = self._get_cached(normalized_shop_id)
        if cached is not None:
            self._record_stats(
                event="internal.product_repository.cache_hit",
                shop_id=normalized_shop_id,
                record_count=len(cached),
                cache_hit=True,
                source="cache",
            )
            return self._clone_records(cached)

        load_error_type = ""
        try:
            if self._records_source is not None:
                records = self._load_from_records_source(normalized_shop_id)
            else:
                records = self._load_from_session(normalized_shop_id)
        except Exception as exc:
            records = []
            load_error_type = type(exc).__name__
            self._record_stats(
                event="internal.product_repository.cache_miss",
                shop_id=normalized_shop_id,
                record_count=0,
                cache_hit=False,
                source=self._source_name(),
                load_error_type=load_error_type,
            )

        if not load_error_type:
            self._record_stats(
                event="internal.product_repository.cache_miss",
                shop_id=normalized_shop_id,
                record_count=len(records),
                cache_hit=False,
                source=self._source_name(records),
            )
        self._set_cached(normalized_shop_id, records)
        return self._clone_records(records)

    def clear_cache(self, shop_id: str | None = None) -> None:
        if shop_id is None:
            self._cache.clear()
            self._last_stats = {
                "event": "internal.product_repository.cache_clear",
                "shop_hash": "",
                "record_count": 0,
                "cache_hit": None,
                "ttl_seconds": self._ttl_seconds,
                "source": "empty",
            }
            logger.debug(
                "event=internal.product_repository.cache_clear shop_hash= record_count=0 ttl_seconds=%s source=empty",
                self._ttl_seconds,
            )
            return
        normalized_shop_id = str(shop_id or "").strip()
        if normalized_shop_id:
            self._cache.pop(normalized_shop_id, None)
            self._last_stats = {
                "event": "internal.product_repository.cache_clear",
                "shop_hash": self._shop_hash(normalized_shop_id),
                "record_count": 0,
                "cache_hit": None,
                "ttl_seconds": self._ttl_seconds,
                "source": "empty",
            }
            logger.debug(
                "event=internal.product_repository.cache_clear shop_hash=%s record_count=0 ttl_seconds=%s source=empty",
                self._shop_hash(normalized_shop_id),
                self._ttl_seconds,
            )

    def _get_cached(self, shop_id: str) -> list[dict[str, Any]] | None:
        if not self._cache_enabled():
            return None
        cached = self._cache.get(shop_id)
        if cached is None:
            return None
        loaded_at, records = cached
        if self._time_provider() - loaded_at <= self._ttl_seconds:
            return records
        self._cache.pop(shop_id, None)
        return None

    def _set_cached(self, shop_id: str, records: list[dict[str, Any]]) -> None:
        if self._cache_enabled():
            self._cache[shop_id] = (self._time_provider(), self._clone_records(records))

    def _cache_enabled(self) -> bool:
        return self._enable_cache and self._ttl_seconds > 0

    @classmethod
    def _resolve_cache_ttl_seconds(cls, ttl_seconds: float | None) -> float:
        if ttl_seconds is not None:
            return max(0.0, float(ttl_seconds))

        raw_ttl = os.getenv(cls.CACHE_TTL_ENV_VAR)
        if raw_ttl is None or not raw_ttl.strip():
            return cls.DEFAULT_CACHE_TTL_SECONDS
        try:
            parsed_ttl = float(raw_ttl)
        except (TypeError, ValueError):
            return cls.DEFAULT_CACHE_TTL_SECONDS
        if parsed_ttl < 0:
            return cls.DEFAULT_CACHE_TTL_SECONDS
        return parsed_ttl

    @staticmethod
    def _clone_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(record) for record in records]

    def get_last_stats(self) -> dict[str, Any] | None:
        if self._last_stats is None:
            return None
        return dict(self._last_stats)

    def _record_stats(
        self,
        *,
        event: str,
        shop_id: str,
        record_count: int,
        cache_hit: bool | None,
        source: str,
        load_error_type: str = "",
    ) -> None:
        shop_hash = self._shop_hash(shop_id)
        self._last_stats = {
            "event": event,
            "shop_hash": shop_hash,
            "record_count": int(record_count),
            "cache_hit": cache_hit,
            "ttl_seconds": self._ttl_seconds,
            "source": source,
            "load_error_type": load_error_type,
        }
        logger.debug(
            "event=%s shop_hash=%s record_count=%s ttl_seconds=%s source=%s cache_hit=%s load_error_type=%s",
            event,
            shop_hash,
            record_count,
            self._ttl_seconds,
            source,
            cache_hit,
            load_error_type,
        )

    @staticmethod
    def _shop_hash(shop_id: str) -> str:
        return hashlib.sha256(shop_id.encode("utf-8")).hexdigest()[:12]

    def _source_name(self, records: list[dict[str, Any]] | None = None) -> str:
        if records is not None and not records:
            return "empty"
        if self._records_source is not None:
            return "fake"
        return "sqlite"

    def _load_from_records_source(self, shop_id: str) -> list[dict[str, Any]]:
        source = self._records_source
        records = source(shop_id) if callable(source) else source
        return [
            mapped
            for record in records or []
            if (mapped := self._record_to_retriever_record(record, requested_shop_id=shop_id)) is not None
        ]

    def _load_from_session(self, shop_id: str) -> list[dict[str, Any]]:
        session = self._open_session()
        try:
            rows = self._query_rows(session, shop_id)
            return [
                mapped
                for row in rows
                if (mapped := self._row_to_retriever_record(row, requested_shop_id=shop_id)) is not None
            ]
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def _open_session(self) -> Any:
        if self._session_provider is not None:
            return self._session_provider()
        if self._db_manager is not None and hasattr(self._db_manager, "get_session"):
            return self._db_manager.get_session()
        from database.db_manager import get_db_manager

        return get_db_manager().get_session()

    @staticmethod
    def _query_rows(session: Any, shop_id: str) -> list[Any]:
        from database.models import ProductKnowledge, Shop

        return (
            session.query(ProductKnowledge, Shop)
            .join(Shop, ProductKnowledge.shop_id == Shop.id)
            .filter(Shop.shop_id == shop_id)
            .order_by(ProductKnowledge.id.asc())
            .all()
        )

    def _row_to_retriever_record(self, row: Any, *, requested_shop_id: str) -> dict[str, Any] | None:
        if isinstance(row, tuple) and len(row) >= 2:
            product, shop = row[0], row[1]
            return self._product_to_record(product, shop, requested_shop_id=requested_shop_id)
        mapping = getattr(row, "_mapping", None)
        if mapping is not None:
            values = list(mapping.values())
            if len(values) >= 2:
                return self._product_to_record(values[0], values[1], requested_shop_id=requested_shop_id)
        return self._record_to_retriever_record(row, requested_shop_id=requested_shop_id)

    def _record_to_retriever_record(self, record: Any, *, requested_shop_id: str) -> dict[str, Any] | None:
        platform_shop_id = self._value(record, "shop_platform_id") or self._value(record, "shop_id")
        if str(platform_shop_id or "") != requested_shop_id:
            return None
        manual_attrs = self._manual_attrs(self._value(record, "raw_detail_json"))
        mapped = {
            "source": self._value(record, "source") or "product_knowledge",
            "domain": self._value(record, "domain") or "product_catalog",
            "shop_id": str(platform_shop_id),
            "shop_platform_id": str(platform_shop_id),
            "shop_db_id": self._value(record, "shop_db_id"),
            "goods_id": self._value(record, "goods_id"),
            "goods_name": self._value(record, "goods_name"),
            "price": self._value(record, "price"),
            "specifications": self._value(record, "specifications"),
            "raw_detail_json": self._value(record, "raw_detail_json"),
            "fastgpt_question": self._value(record, "fastgpt_question"),
            "fastgpt_answer": self._value(record, "fastgpt_answer"),
            "content": self._value(record, "content"),
        }
        self._merge_manual_attrs(mapped, record, manual_attrs)
        return mapped

    def _product_to_record(self, product: Any, shop: Any, *, requested_shop_id: str) -> dict[str, Any] | None:
        platform_shop_id = str(self._value(shop, "shop_id") or "")
        if platform_shop_id != requested_shop_id:
            return None
        raw_detail_json = self._value(product, "raw_detail_json")
        manual_attrs = self._manual_attrs(raw_detail_json)
        mapped = {
            "source": "product_knowledge",
            "domain": "product_catalog",
            "shop_id": platform_shop_id,
            "shop_platform_id": platform_shop_id,
            "shop_db_id": self._value(shop, "id") or self._value(product, "shop_id"),
            "shop_name": self._value(shop, "shop_name"),
            "goods_id": self._value(product, "goods_id"),
            "goods_name": self._value(product, "goods_name"),
            "price": self._value(product, "price"),
            "specifications": self._value(product, "specifications"),
            "raw_detail_json": raw_detail_json,
            "fastgpt_question": self._default_question(product, manual_attrs),
            "fastgpt_answer": self._render_content(product, manual_attrs),
            "content": self._render_content(product, manual_attrs),
        }
        self._merge_manual_attrs(mapped, product, manual_attrs)
        return mapped

    def _merge_manual_attrs(self, mapped: dict[str, Any], record: Any, manual_attrs: Mapping[str, Any]) -> None:
        for key in self.MANUAL_FIELD_KEYS:
            mapped[key] = self._value(record, key) or manual_attrs.get(key)

    @staticmethod
    def _value(record: Any, key: str) -> Any:
        if isinstance(record, Mapping):
            return record.get(key)
        return getattr(record, key, None)

    @staticmethod
    def _manual_attrs(raw_detail_json: Any) -> dict[str, Any]:
        if isinstance(raw_detail_json, Mapping):
            raw = raw_detail_json
        elif raw_detail_json:
            try:
                value = json.loads(str(raw_detail_json))
                raw = value if isinstance(value, Mapping) else {}
            except (TypeError, ValueError):
                raw = {}
        else:
            raw = {}
        attrs = raw.get("manual_attributes") if isinstance(raw, Mapping) else {}
        return attrs if isinstance(attrs, dict) else {}

    @staticmethod
    def _default_question(product: Any, manual_attrs: Mapping[str, Any]) -> str:
        category = str(manual_attrs.get("category") or "").strip()
        goods_name = str(getattr(product, "goods_name", "") or "").strip()
        if category:
            return f"{category} {goods_name} 怎么选？"
        return f"{goods_name} 的规格、用法、适用人群和注意事项是什么？"

    @staticmethod
    def _render_content(product: Any, manual_attrs: Mapping[str, Any]) -> str:
        labels = (
            ("goods_name", "商品名称", getattr(product, "goods_name", "")),
            ("goods_id", "商品ID", getattr(product, "goods_id", "")),
            ("price", "价格", getattr(product, "price", "")),
            ("specifications", "平台规格", getattr(product, "specifications", "")),
            ("sku_summary", "规格摘要", manual_attrs.get("sku_summary")),
            ("effect", "功效卖点", manual_attrs.get("effect")),
            ("usage_method", "使用方法", manual_attrs.get("usage_method")),
            ("ingredients", "成分/材质", manual_attrs.get("ingredients")),
            ("shelf_life", "保质期", manual_attrs.get("shelf_life")),
            ("warnings", "注意事项", manual_attrs.get("warnings")),
            ("manual_notes", "人工补充说明", manual_attrs.get("manual_notes")),
        )
        return "\n".join(
            f"{label}: {ProductKnowledgeRepository._cell(value)}"
            for _key, label, value in labels
            if ProductKnowledgeRepository._cell(value)
        )

    @staticmethod
    def _cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "\n".join(str(item) for item in value if str(item).strip())
        return str(value).strip()
