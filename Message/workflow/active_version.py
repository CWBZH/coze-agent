"""Knowledge Center active version resolver for InternalEngine RAG.

The resolver is read-only and intentionally lightweight. It reads the
Knowledge Center SQLite tables to discover active versions, then returns
metadata filters that RAG retrievers can apply to pgvector or in-memory stores.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ActiveVersionResult:
    resolved: bool = False
    version_id: int | None = None
    version: str = ""
    source_type: str = ""
    source_id: str = ""
    domain: str = ""
    filters: dict[str, str] = field(default_factory=dict)
    fallback: bool = False
    missing_reason: str = ""


class ActiveVersionResolver:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or os.getenv("WEB_API_SQLITE_DB_PATH") or "temp/channel_shop.db")

    def get_active_version(
        self,
        shop_id: str,
        *,
        source_type: str,
        domain: str | None = None,
        source_id: str | None = None,
    ) -> ActiveVersionResult:
        shop_id = str(shop_id or "").strip()
        source_type = str(source_type or "").strip()
        domain = str(domain or "").strip()
        source_id = str(source_id or "").strip()
        if not shop_id or not source_type:
            return _missing(source_type=source_type, source_id=source_id, domain=domain, reason="missing_required_scope")
        if not self.db_path.exists():
            return _missing(source_type=source_type, source_id=source_id, domain=domain, reason="db_missing")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                if not _table_exists(conn, "knowledge_versions"):
                    return _missing(source_type=source_type, source_id=source_id, domain=domain, reason="table_missing")
                where = ["shop_id=?", "source_type=?", "is_active=1"]
                params: list[Any] = [shop_id, source_type]
                if domain:
                    where.append("domain=?")
                    params.append(domain)
                if source_id:
                    where.append("source_id=?")
                    params.append(source_id)
                row = conn.execute(
                    f"""
                    SELECT *
                    FROM knowledge_versions
                    WHERE {' AND '.join(where)}
                    ORDER BY activated_at DESC, indexed_at DESC, id DESC
                    LIMIT 1
                    """,
                    tuple(params),
                ).fetchone()
        except sqlite3.Error:
            return _missing(source_type=source_type, source_id=source_id, domain=domain, reason="db_error")
        if not row:
            return _missing(source_type=source_type, source_id=source_id, domain=domain, reason="active_version_not_found")
        data = dict(row)
        filters = {
            "source_type": str(data.get("source_type") or source_type),
            "version_id": str(data.get("id") or ""),
        }
        if data.get("source_id"):
            filters["source_id"] = str(data.get("source_id") or "")
        return ActiveVersionResult(
            resolved=True,
            version_id=int(data["id"]),
            version=str(data.get("version") or ""),
            source_type=str(data.get("source_type") or source_type),
            source_id=str(data.get("source_id") or source_id),
            domain=str(data.get("domain") or domain),
            filters=filters,
            fallback=False,
            missing_reason="",
        )

    def get_active_versions_for_shop(self, shop_id: str) -> list[dict[str, Any]]:
        shop_id = str(shop_id or "").strip()
        if not shop_id or not self.db_path.exists():
            return []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                if not _table_exists(conn, "knowledge_versions"):
                    return []
                rows = conn.execute(
                    """
                    SELECT *
                    FROM knowledge_versions
                    WHERE shop_id=? AND is_active=1
                    ORDER BY source_type, domain, source_id, id DESC
                    """,
                    (shop_id,),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(row) for row in rows]

    def resolve_rag_filters(
        self,
        *,
        shop_id: str,
        intent: str = "",
        domain: str = "",
        source_type: str | None = None,
        goods_id: str | None = None,
    ) -> ActiveVersionResult:
        normalized_domain = str(domain or "").strip()
        normalized_source_type = str(source_type or "").strip()
        normalized_goods_id = str(goods_id or "").strip()
        if not normalized_source_type:
            normalized_source_type = "product" if normalized_domain in {"product_catalog", "product_basic"} else "sop"
        source_id = normalized_goods_id if normalized_source_type == "product" else None
        if normalized_source_type == "product" and not source_id:
            return _missing(source_type="product", source_id="", domain=normalized_domain, reason="missing_product_source_id")
        return self.get_active_version(
            shop_id,
            source_type=normalized_source_type,
            domain="product_catalog" if normalized_source_type == "product" else normalized_domain,
            source_id=source_id,
        )


def _missing(*, source_type: str, source_id: str, domain: str, reason: str) -> ActiveVersionResult:
    return ActiveVersionResult(
        resolved=False,
        source_type=source_type,
        source_id=source_id,
        domain=domain,
        filters={},
        fallback=True,
        missing_reason=reason,
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone() is not None
