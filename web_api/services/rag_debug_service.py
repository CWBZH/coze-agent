from __future__ import annotations

import os
import re
from typing import Any

from web_api.schemas.products import ProductChunk
from web_api.schemas.rag import RagDebugHit, RagDebugRequest, RagDebugResponse


class RagDebugService:
    """Read-only pgvector debug access for Web Admin.

    This service only issues SELECT statements. It never calls embedding
    providers, LLMs, PDD, or write/delete SQL.
    """

    def __init__(self, *, dsn: str | None = None, psycopg_module: Any | None = None) -> None:
        self._dsn = dsn if dsn is not None else _pgvector_dsn()
        self._psycopg = psycopg_module

    def list_product_chunks(
        self,
        *,
        goods_id: str,
        shop_id: str | None = None,
        version: str | None = None,
        domain: str | None = None,
        source_type: str | None = "product",
        limit: int = 20,
    ) -> tuple[list[ProductChunk], str | None]:
        if not self._dsn:
            return [], "pgvector_not_configured"
        psycopg, warning = self._load_psycopg()
        if warning:
            return [], warning
        clauses = ["(source_id = %s OR metadata_json ->> 'goods_id' = %s)"]
        params: list[Any] = [goods_id, goods_id]
        if shop_id:
            clauses.append("shop_id = %s")
            params.append(shop_id)
        if version:
            clauses.append("version = %s")
            params.append(version)
        if domain:
            clauses.append("domain = %s")
            params.append(domain)
        else:
            clauses.append("domain IN ('product_catalog', 'product_basic')")
        if source_type:
            clauses.append("source_type = %s")
            params.append(source_type)
        params.append(max(1, min(int(limit or 20), 100)))
        try:
            with psycopg.connect(self._dsn) as conn:
                rows = conn.execute(
                    f"""
                    SELECT chunk_id, shop_id, domain, source_type, source_id, version,
                           content, content_hash, metadata_json, created_at
                    FROM knowledge_chunks
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT %s
                    """,
                    params,
                ).fetchall()
        except Exception as exc:  # pragma: no cover - exact exception depends on deployment.
            return [], _warning("pgvector_query_failed", exc)
        return [_row_to_chunk(row) for row in rows], None

    def retrieve_debug(self, request: RagDebugRequest) -> RagDebugResponse:
        if not self._dsn:
            return RagDebugResponse(
                query=request.query,
                shop_id=request.shop_id,
                domain=request.domain,
                version=request.version,
                hits=[],
                warning="pgvector_not_configured",
            )
        psycopg, warning = self._load_psycopg()
        if warning:
            return RagDebugResponse(
                query=request.query,
                shop_id=request.shop_id,
                domain=request.domain,
                version=request.version,
                hits=[],
                warning=warning,
            )
        clauses = ["shop_id = %s", "domain = %s"]
        params: list[Any] = [request.shop_id, request.domain]
        if request.version:
            clauses.append("version = %s")
            params.append(request.version)
        if request.goods_id:
            clauses.append("(source_id = %s OR metadata_json ->> 'goods_id' = %s)")
            params.extend([request.goods_id, request.goods_id])
        terms = _query_terms(request.query)
        if terms:
            term_clauses = []
            for term in terms:
                term_clauses.append("(source_id ILIKE %s OR title ILIKE %s OR content ILIKE %s OR metadata_json::text ILIKE %s)")
                like = f"%{term}%"
                params.extend([like, like, like, like])
            clauses.append("(" + " OR ".join(term_clauses) + ")")
        params.append(max(1, min(int(request.top_k or 5), 20)))
        try:
            with psycopg.connect(self._dsn) as conn:
                rows = conn.execute(
                    f"""
                    SELECT chunk_id, content, 1.0 AS score, domain, source_type,
                           source_id, version, metadata_json
                    FROM knowledge_chunks
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT %s
                    """,
                    params,
                ).fetchall()
        except Exception as exc:  # pragma: no cover - exact exception depends on deployment.
            return RagDebugResponse(
                query=request.query,
                shop_id=request.shop_id,
                domain=request.domain,
                version=request.version,
                hits=[],
                connects_pgvector=False,
                warning=_warning("pgvector_query_failed", exc),
            )
        return RagDebugResponse(
            query=request.query,
            shop_id=request.shop_id,
            domain=request.domain,
            version=request.version,
            hits=[_row_to_hit(row) for row in rows],
            connects_pgvector=True,
            calls_ollama=False,
        )

    def _load_psycopg(self) -> tuple[Any | None, str | None]:
        if self._psycopg is not None:
            return self._psycopg, None
        try:
            import psycopg  # type: ignore
        except ImportError:
            return None, "pgvector_driver_missing"
        return psycopg, None


def _pgvector_dsn() -> str:
    return os.getenv("WEB_API_PGVECTOR_DSN") or os.getenv("AI_WORKFLOW_PGVECTOR_DSN") or ""


def _warning(prefix: str, exc: Exception) -> str:
    return f"{prefix}:{type(exc).__name__}"


def _metadata(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _row_to_chunk(row: Any) -> ProductChunk:
    return ProductChunk(
        chunk_id=str(row[0] or ""),
        shop_id=str(row[1] or ""),
        domain=str(row[2] or ""),
        source_type=str(row[3] or ""),
        source_id=str(row[4] or ""),
        version=str(row[5] or ""),
        content=str(row[6] or ""),
        content_hash=str(row[7] or ""),
        metadata=_metadata(row[8]),
        created_at=str(row[9] or ""),
    )


def _row_to_hit(row: Any) -> RagDebugHit:
    return RagDebugHit(
        chunk_id=str(row[0] or ""),
        content=str(row[1] or ""),
        score=float(row[2] or 0.0),
        domain=str(row[3] or ""),
        source_type=str(row[4] or ""),
        source_id=str(row[5] or ""),
        version=str(row[6] or ""),
        metadata=_metadata(row[7]),
    )


def _query_terms(query: str) -> list[str]:
    terms = [item for item in re.split(r"\s+|[,，。！？?；;]+", str(query or "").strip()) if len(item) >= 2]
    result: list[str] = []
    for term in terms[:8]:
        if term not in result:
            result.append(term)
    return result
