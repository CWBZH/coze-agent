"""Vector store abstractions for internal RAG."""
from __future__ import annotations

import math
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .rag_types import KnowledgeChunk, RetrievalHit, RetrievalQuery, chunk_index_run_id, chunk_is_test_data, chunk_namespace


@dataclass(frozen=True)
class LegacyAuditResult:
    status: str = "ok"
    connects_pgvector: bool = False
    legacy_candidate_count: int = 0
    legacy_source_types: list[str] | None = None
    legacy_versions: list[str] | None = None
    legacy_domains: list[str] | None = None
    legacy_shop_ids_hash: list[str] | None = None
    has_non_pollution_candidates: bool = False
    error_type: str = ""


@dataclass(frozen=True)
class DeleteResult:
    scanned_count: int = 0
    matched_count: int = 0
    deleted_count: int = 0
    dry_run: bool = True
    filters: dict[str, Any] | None = None
    status: str = "ok"
    error_type: str = ""


class VectorStore(Protocol):
    def upsert(self, chunk: KnowledgeChunk, vector: list[float], *, embedding_model: str = "bge-m3") -> None:
        ...

    def search(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        ...

    def search_hybrid(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        ...

    def search_product_hybrid(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        ...

    def delete_chunks(
        self,
        *,
        shop_id: str | None = None,
        domain: str | None = None,
        version: str | None = None,
        source_type_prefix: str | None = None,
        index_run_id: str | None = None,
        namespace: str | None = None,
        is_test_data: bool | None = None,
        dry_run: bool = False,
    ) -> DeleteResult:
        ...

    def audit_legacy_pollution(
        self,
        *,
        source_type_prefix: str = "pollution_",
        legacy_version: str = "old-version",
        legacy_shop_id: str = "synthetic-shop-1",
        legacy_wrong_shop_id: str = "synthetic-shop-2",
        legacy_domain: str = "",
    ) -> LegacyAuditResult:
        ...

    def delete_legacy_pollution(
        self,
        *,
        source_type_prefix: str = "pollution_",
        version: str | None = None,
        shop_id: str | None = None,
        domain: str | None = None,
        index_run_id: str | None = None,
        dry_run: bool = True,
    ) -> DeleteResult:
        ...


@dataclass
class _StoredVector:
    chunk: KnowledgeChunk
    vector: list[float]
    embedding_model: str


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: dict[str, _StoredVector] = {}
        self._last_hybrid_stats: dict[str, int] = {}

    def upsert(self, chunk: KnowledgeChunk, vector: list[float], *, embedding_model: str = "bge-m3") -> None:
        errors = chunk.validate()
        if errors:
            raise ValueError("; ".join(errors))
        self._items[chunk.chunk_id] = _StoredVector(chunk=chunk, vector=list(vector), embedding_model=embedding_model)

    def search(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        errors = query.validate()
        if errors:
            raise ValueError("; ".join(errors))
        candidates: list[RetrievalHit] = []
        for item in self._items.values():
            chunk = item.chunk
            if chunk.shop_id != query.shop_id or chunk.domain != query.domain:
                continue
            if query.version and chunk.version != query.version:
                continue
            if not _chunk_matches_query_filters(chunk, query.filters):
                continue
            candidates.append(RetrievalHit.from_chunk(chunk, score=_cosine_similarity(vector, item.vector)))
        candidates.sort(key=lambda hit: hit.score, reverse=True)
        return candidates[: query.top_k]

    def search_product_hybrid(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        return self.search_hybrid(query, vector)

    def search_hybrid(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        errors = query.validate()
        if errors:
            raise ValueError("; ".join(errors))
        fulltext_hits: list[RetrievalHit] = []
        for item in self._items.values():
            chunk = item.chunk
            if chunk.shop_id != query.shop_id or chunk.domain != query.domain:
                continue
            if query.version and chunk.version != query.version:
                continue
            if not _chunk_matches_query_filters(chunk, query.filters):
                continue
            if _keyword_overlap(query.query, " ".join([chunk.title, chunk.content])):
                fulltext_hits.append(_with_match(RetrievalHit.from_chunk(chunk, score=1.0), "fulltext"))
        semantic_hits = [_with_match(hit, "semantic") for hit in self.search(replace(query, top_k=max(query.top_k * 3, query.top_k)), vector)]
        merged = _rrf_merge(semantic_hits, fulltext_hits, top_k=query.top_k)
        self._last_hybrid_stats = {
            "exact_hit_count": 0,
            "name_hit_count": 0,
            "keyword_hit_count": len(fulltext_hits),
            "fulltext_hit_count": len(fulltext_hits),
            "semantic_hit_count": len(semantic_hits),
        }
        return merged

    def get_last_hybrid_stats(self) -> dict[str, int]:
        return dict(self._last_hybrid_stats)

    def delete_chunks(
        self,
        *,
        shop_id: str | None = None,
        domain: str | None = None,
        version: str | None = None,
        source_type_prefix: str | None = None,
        index_run_id: str | None = None,
        namespace: str | None = None,
        is_test_data: bool | None = None,
        dry_run: bool = False,
    ) -> DeleteResult:
        filters = _filters(
            shop_id=shop_id,
            domain=domain,
            version=version,
            source_type_prefix=source_type_prefix,
            index_run_id=index_run_id,
            namespace=namespace,
            is_test_data=is_test_data,
        )
        safe_error = _delete_safety_error(filters)
        if safe_error:
            return DeleteResult(
                scanned_count=len(self._items),
                matched_count=0,
                deleted_count=0,
                dry_run=dry_run,
                filters=filters,
                status="rejected",
                error_type=safe_error,
            )
        matched = [
            chunk_id
            for chunk_id, item in self._items.items()
            if _chunk_matches_delete_filters(item.chunk, filters)
        ]
        if not dry_run:
            for chunk_id in matched:
                del self._items[chunk_id]
        return DeleteResult(
            scanned_count=len(self._items) + (0 if dry_run else len(matched)),
            matched_count=len(matched),
            deleted_count=0 if dry_run else len(matched),
            dry_run=dry_run,
            filters=filters,
        )

    def audit_legacy_pollution(
        self,
        *,
        source_type_prefix: str = "pollution_",
        legacy_version: str = "old-version",
        legacy_shop_id: str = "synthetic-shop-1",
        legacy_wrong_shop_id: str = "synthetic-shop-2",
        legacy_domain: str = "",
    ) -> LegacyAuditResult:
        candidates = [
            item.chunk
            for item in self._items.values()
            if _is_legacy_pollution_candidate(
                item.chunk,
                source_type_prefix=source_type_prefix,
                legacy_version=legacy_version,
                legacy_shop_id=legacy_shop_id,
                legacy_wrong_shop_id=legacy_wrong_shop_id,
                legacy_domain=legacy_domain,
            )
        ]
        non_pollution = any(not chunk.source_type.startswith(source_type_prefix) for chunk in candidates)
        return LegacyAuditResult(
            legacy_candidate_count=len(candidates),
            legacy_source_types=sorted({chunk.source_type for chunk in candidates}),
            legacy_versions=sorted({chunk.version for chunk in candidates}),
            legacy_domains=sorted({chunk.domain for chunk in candidates}),
            legacy_shop_ids_hash=sorted({_short_hash(chunk.shop_id) for chunk in candidates}),
            has_non_pollution_candidates=non_pollution,
        )

    def delete_legacy_pollution(
        self,
        *,
        source_type_prefix: str = "pollution_",
        version: str | None = None,
        shop_id: str | None = None,
        domain: str | None = None,
        index_run_id: str | None = None,
        dry_run: bool = True,
    ) -> DeleteResult:
        filters = _legacy_filters(
            source_type_prefix=source_type_prefix,
            version=version,
            shop_id=shop_id,
            domain=domain,
            index_run_id=index_run_id,
        )
        safe_error = _legacy_delete_safety_error(filters)
        if safe_error:
            return DeleteResult(
                scanned_count=len(self._items),
                matched_count=0,
                deleted_count=0,
                dry_run=dry_run,
                filters=filters,
                status="rejected",
                error_type=safe_error,
            )
        matched = [
            chunk_id
            for chunk_id, item in self._items.items()
            if _chunk_matches_legacy_delete_filters(item.chunk, filters)
        ]
        if not dry_run:
            for chunk_id in matched:
                del self._items[chunk_id]
        return DeleteResult(
            scanned_count=len(self._items) + (0 if dry_run else len(matched)),
            matched_count=len(matched),
            deleted_count=0 if dry_run else len(matched),
            dry_run=dry_run,
            filters=filters,
        )


class PgVectorStore:
    """PostgreSQL/pgvector adapter.

    This adapter is intentionally lazy. It imports psycopg only when the caller
    explicitly constructs it with a DSN, so tests do not require PostgreSQL.
    """

    def __init__(self, dsn: str):
        if not dsn:
            raise ValueError("pgvector DSN is required")
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on deployment env.
            raise RuntimeError("psycopg is required for PgVectorStore") from exc
        self._psycopg = psycopg
        self._dsn = dsn
        self._last_hybrid_stats: dict[str, int] = {}

    @property
    def masked_dsn(self) -> str:
        return mask_pg_dsn(self._dsn)

    def apply_schema(self, schema_path: str | Path) -> None:
        sql = Path(schema_path).read_text(encoding="utf-8")
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            conn.execute(sql)

    def check_schema(self) -> dict[str, Any]:
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            extension = conn.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')").fetchone()[0]
            table = conn.execute("SELECT to_regclass('public.knowledge_chunks') IS NOT NULL").fetchone()[0]
            columns: set[str] = set()
            if table:
                rows = conn.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'knowledge_chunks'
                    """
                ).fetchall()
                columns = {row[0] for row in rows}
        required = {
            "chunk_id",
            "shop_id",
            "domain",
            "source_type",
            "source_id",
            "title",
            "content",
            "content_hash",
            "version",
            "embedding",
        }
        return {
            "extension_available": bool(extension),
            "table_available": bool(table),
            "columns_ok": required.issubset(columns),
            "missing_columns": sorted(required - columns),
        }

    def upsert(self, chunk: KnowledgeChunk, vector: list[float], *, embedding_model: str = "bge-m3") -> None:
        errors = chunk.validate()
        if errors:
            raise ValueError("; ".join(errors))
        vector_literal = _vector_literal(vector)
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            conn.execute(
                """
                INSERT INTO knowledge_chunks (
                    chunk_id, shop_id, domain, source_type, source_id, title, content,
                    content_hash, version, index_run_id, namespace, is_test_data, created_by, metadata_json, embedding_model,
                    embedding_dimension, embedding
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    content_hash = EXCLUDED.content_hash,
                    version = EXCLUDED.version,
                    index_run_id = EXCLUDED.index_run_id,
                    namespace = EXCLUDED.namespace,
                    is_test_data = EXCLUDED.is_test_data,
                    created_by = EXCLUDED.created_by,
                    metadata_json = EXCLUDED.metadata_json,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_dimension = EXCLUDED.embedding_dimension,
                    embedding = EXCLUDED.embedding,
                    updated_at = now()
                """,
                (
                    chunk.chunk_id,
                    chunk.shop_id,
                    chunk.domain,
                    chunk.source_type,
                    chunk.source_id,
                    chunk.title,
                    chunk.content,
                    chunk.content_hash,
                    chunk.version,
                    chunk_index_run_id(chunk) or None,
                    chunk_namespace(chunk) or None,
                    chunk_is_test_data(chunk),
                    str(chunk.metadata.get("created_by", "") or "") or None,
                    self._psycopg.types.json.Jsonb(chunk.metadata),
                    embedding_model,
                    len(vector),
                    vector_literal,
                ),
            )

    def search(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        errors = query.validate()
        if errors:
            raise ValueError("; ".join(errors))
        vector_literal = _vector_literal(vector)
        where_sql, where_params = _pg_query_where(query)
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            rows = conn.execute(
                f"""
                SELECT chunk_id, shop_id, domain, title, left(content, 1200) AS content_summary,
                       1 - (embedding <=> %s::vector) AS score, source_type, source_id,
                       version, content_hash, metadata_json
                FROM knowledge_chunks
                WHERE {where_sql}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                [vector_literal, *where_params, vector_literal, query.top_k],
            ).fetchall()
        hits: list[RetrievalHit] = []
        for row in rows:
            hits.append(
                RetrievalHit(
                    chunk_id=row[0],
                    shop_id=row[1],
                    domain=row[2],
                    title=row[3],
                    content_summary=row[4],
                    score=float(row[5]),
                    source_type=row[6],
                    source_id=row[7],
                    version=row[8],
                    content_hash=row[9],
                    metadata=dict(row[10] or {}),
                )
            )
        return hits

    def search_product_hybrid(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        return self.search_hybrid(query, vector)

    def search_hybrid(self, query: RetrievalQuery, vector: list[float]) -> list[RetrievalHit]:
        errors = query.validate()
        if errors:
            raise ValueError("; ".join(errors))
        where_sql, where_params = _pg_query_where(query)
        fulltext_rows = []
        terms = _query_keywords(query.query)[:5]
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            if terms:
                clauses = []
                fulltext_params: list[Any] = []
                for term in terms:
                    like_term = f"%{term}%"
                    clauses.append(
                        "(source_id ILIKE %s OR title ILIKE %s OR content ILIKE %s OR metadata_json::text ILIKE %s)"
                    )
                    fulltext_params.extend([like_term, like_term, like_term, like_term])
                fulltext_rows = conn.execute(
                    f"""
                    SELECT chunk_id, shop_id, domain, title, left(content, 1200) AS content_summary,
                           1.0 AS score, source_type, source_id, version, content_hash, metadata_json
                    FROM knowledge_chunks
                    WHERE {where_sql}
                      AND ({' OR '.join(clauses)})
                    LIMIT %s
                    """,
                    [*where_params, *fulltext_params, max(query.top_k * 3, query.top_k)],
                ).fetchall()
        semantic_hits = self.search(replace(query, top_k=max(query.top_k * 3, query.top_k)), vector)
        fulltext_hits = [_with_match(_row_to_hit(row), "fulltext") for row in fulltext_rows]
        semantic_marked = [_with_match(hit, "semantic") for hit in semantic_hits]
        merged = _rrf_merge(semantic_marked, fulltext_hits, top_k=query.top_k)
        self._last_hybrid_stats = {
            "exact_hit_count": 0,
            "name_hit_count": 0,
            "keyword_hit_count": len(fulltext_hits),
            "fulltext_hit_count": len(fulltext_hits),
            "semantic_hit_count": len(semantic_marked),
        }
        return merged

    def get_last_hybrid_stats(self) -> dict[str, int]:
        return dict(self._last_hybrid_stats)

    def delete_chunks(
        self,
        *,
        shop_id: str | None = None,
        domain: str | None = None,
        version: str | None = None,
        source_type_prefix: str | None = None,
        index_run_id: str | None = None,
        namespace: str | None = None,
        is_test_data: bool | None = None,
        dry_run: bool = False,
    ) -> DeleteResult:
        filters = _filters(
            shop_id=shop_id,
            domain=domain,
            version=version,
            source_type_prefix=source_type_prefix,
            index_run_id=index_run_id,
            namespace=namespace,
            is_test_data=is_test_data,
        )
        safe_error = _delete_safety_error(filters)
        if safe_error:
            return DeleteResult(dry_run=dry_run, filters=filters, status="rejected", error_type=safe_error)
        where, params = _delete_where_sql(filters)
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            matched = conn.execute(f"SELECT count(*) FROM knowledge_chunks WHERE {where}", params).fetchone()[0]
            deleted = 0
            if not dry_run:
                deleted = conn.execute(f"DELETE FROM knowledge_chunks WHERE {where}", params).rowcount
        return DeleteResult(
            scanned_count=int(matched),
            matched_count=int(matched),
            deleted_count=int(deleted),
            dry_run=dry_run,
            filters=filters,
        )

    def audit_legacy_pollution(
        self,
        *,
        source_type_prefix: str = "pollution_",
        legacy_version: str = "old-version",
        legacy_shop_id: str = "synthetic-shop-1",
        legacy_wrong_shop_id: str = "synthetic-shop-2",
        legacy_domain: str = "",
    ) -> LegacyAuditResult:
        if not source_type_prefix.startswith("pollution_"):
            return LegacyAuditResult(connects_pgvector=True, status="rejected", error_type="unsafe_legacy_prefix")
        where, params = _legacy_audit_where_sql(
            source_type_prefix=source_type_prefix,
            legacy_version=legacy_version,
            legacy_wrong_shop_id=legacy_wrong_shop_id,
            legacy_domain=legacy_domain,
        )
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            rows = conn.execute(
                f"""
                SELECT source_type, version, domain, shop_id
                FROM knowledge_chunks
                WHERE {where}
                """,
                params,
            ).fetchall()
        return LegacyAuditResult(
            connects_pgvector=True,
            legacy_candidate_count=len(rows),
            legacy_source_types=sorted({str(row[0] or "") for row in rows if row[0]}),
            legacy_versions=sorted({str(row[1] or "") for row in rows if row[1]}),
            legacy_domains=sorted({str(row[2] or "") for row in rows if row[2]}),
            legacy_shop_ids_hash=sorted({_short_hash(row[3]) for row in rows if row[3]}),
            has_non_pollution_candidates=any(not str(row[0] or "").startswith(source_type_prefix) for row in rows),
        )

    def delete_legacy_pollution(
        self,
        *,
        source_type_prefix: str = "pollution_",
        version: str | None = None,
        shop_id: str | None = None,
        domain: str | None = None,
        index_run_id: str | None = None,
        dry_run: bool = True,
    ) -> DeleteResult:
        filters = _legacy_filters(
            source_type_prefix=source_type_prefix,
            version=version,
            shop_id=shop_id,
            domain=domain,
            index_run_id=index_run_id,
        )
        safe_error = _legacy_delete_safety_error(filters)
        if safe_error:
            return DeleteResult(dry_run=dry_run, filters=filters, status="rejected", error_type=safe_error)
        where, params = _legacy_delete_where_sql(filters)
        with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
            matched = conn.execute(f"SELECT count(*) FROM knowledge_chunks WHERE {where}", params).fetchone()[0]
            deleted = 0
            if not dry_run:
                deleted = conn.execute(f"DELETE FROM knowledge_chunks WHERE {where}", params).rowcount
        return DeleteResult(
            scanned_count=int(matched),
            matched_count=int(matched),
            deleted_count=int(deleted),
            dry_run=dry_run,
            filters=filters,
        )


def _filters(
    *,
    shop_id: str | None,
    domain: str | None,
    version: str | None,
    source_type_prefix: str | None,
    index_run_id: str | None,
    namespace: str | None,
    is_test_data: bool | None,
) -> dict[str, Any]:
    return {
        "shop_id": str(shop_id or "").strip(),
        "domain": str(domain or "").strip(),
        "version": str(version or "").strip(),
        "source_type_prefix": str(source_type_prefix or "").strip(),
        "index_run_id": str(index_run_id or "").strip(),
        "namespace": str(namespace or "").strip(),
        "is_test_data": is_test_data,
    }


def _delete_safety_error(filters: dict[str, Any]) -> str:
    if filters["index_run_id"]:
        return ""
    source_prefix = str(filters.get("source_type_prefix") or "")
    namespace = str(filters.get("namespace") or "")
    is_test_data = filters.get("is_test_data")
    if source_prefix == "pollution_" and (namespace or is_test_data is True):
        return ""
    return "unsafe_filters"


def _legacy_filters(
    *,
    source_type_prefix: str | None,
    version: str | None,
    shop_id: str | None,
    domain: str | None,
    index_run_id: str | None,
) -> dict[str, Any]:
    return {
        "source_type_prefix": str(source_type_prefix or "").strip(),
        "version": str(version or "").strip(),
        "shop_id": str(shop_id or "").strip(),
        "domain": str(domain or "").strip(),
        "index_run_id": str(index_run_id or "").strip(),
    }


def _legacy_delete_safety_error(filters: dict[str, Any]) -> str:
    if filters["source_type_prefix"] != "pollution_":
        return "unsafe_legacy_prefix"
    if filters["version"] or filters["shop_id"] or filters["domain"] or filters["index_run_id"]:
        return ""
    return "unsafe_legacy_filters"


def _chunk_matches_delete_filters(chunk: KnowledgeChunk, filters: dict[str, Any]) -> bool:
    if filters["shop_id"] and chunk.shop_id != filters["shop_id"]:
        return False
    if filters["domain"] and chunk.domain != filters["domain"]:
        return False
    if filters["version"] and chunk.version != filters["version"]:
        return False
    if filters["source_type_prefix"] and not chunk.source_type.startswith(filters["source_type_prefix"]):
        return False
    if filters["index_run_id"] and chunk_index_run_id(chunk) != filters["index_run_id"]:
        return False
    if filters["namespace"] and chunk_namespace(chunk) != filters["namespace"]:
        return False
    if filters["is_test_data"] is not None and chunk_is_test_data(chunk) is not filters["is_test_data"]:
        return False
    return True


def _chunk_matches_query_filters(chunk: KnowledgeChunk, filters: dict[str, Any] | None) -> bool:
    filters = dict(filters or {})
    if not filters:
        return True
    metadata = dict(chunk.metadata or {})
    source_type = str(filters.get("source_type") or "").strip()
    if source_type and chunk.source_type != source_type:
        return False
    source_id = str(filters.get("source_id") or filters.get("goods_id") or "").strip()
    if source_id:
        metadata_source_id = str(metadata.get("source_id") or metadata.get("goods_id") or "").strip()
        if chunk.source_id != source_id and metadata_source_id != source_id:
            return False
    version_id = str(filters.get("version_id") or "").strip()
    if version_id and str(metadata.get("version_id") or "").strip() != version_id:
        return False
    version = str(filters.get("version") or "").strip()
    if version and chunk.version != version:
        return False
    namespace = str(filters.get("namespace") or "").strip()
    if namespace and chunk_namespace(chunk) != namespace:
        return False
    return True


def _chunk_matches_legacy_delete_filters(chunk: KnowledgeChunk, filters: dict[str, Any]) -> bool:
    if not chunk.source_type.startswith(filters["source_type_prefix"]):
        return False
    if filters["version"] and chunk.version != filters["version"]:
        return False
    if filters["shop_id"] and chunk.shop_id != filters["shop_id"]:
        return False
    if filters["domain"] and chunk.domain != filters["domain"]:
        return False
    if filters["index_run_id"] and chunk_index_run_id(chunk) != filters["index_run_id"]:
        return False
    return True


def _is_legacy_pollution_candidate(
    chunk: KnowledgeChunk,
    *,
    source_type_prefix: str,
    legacy_version: str,
    legacy_shop_id: str,
    legacy_wrong_shop_id: str,
    legacy_domain: str,
) -> bool:
    if not source_type_prefix.startswith("pollution_"):
        return False
    if not chunk.source_type.startswith(source_type_prefix):
        return False
    missing_lifecycle = not chunk_namespace(chunk) and chunk.metadata.get("is_test_data") is None
    controlled_marker = "pollution" in chunk.chunk_id or "pollution" in chunk.source_id
    return (
        chunk.version == legacy_version
        or chunk.shop_id == legacy_wrong_shop_id
        or bool(legacy_domain and chunk.domain == legacy_domain)
        or controlled_marker
        or missing_lifecycle
        or chunk.source_type
        in {"pollution_old_version", "pollution_wrong_shop", "pollution_wrong_domain"}
    )


def _delete_where_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters["shop_id"]:
        clauses.append("shop_id = %s")
        params.append(filters["shop_id"])
    if filters["domain"]:
        clauses.append("domain = %s")
        params.append(filters["domain"])
    if filters["version"]:
        clauses.append("version = %s")
        params.append(filters["version"])
    if filters["source_type_prefix"]:
        clauses.append("source_type LIKE %s")
        params.append(filters["source_type_prefix"] + "%")
    if filters["index_run_id"]:
        clauses.append("metadata_json ->> 'index_run_id' = %s")
        params.append(filters["index_run_id"])
    if filters["namespace"]:
        clauses.append("metadata_json ->> 'namespace' = %s")
        params.append(filters["namespace"])
    if filters["is_test_data"] is not None:
        clauses.append("(metadata_json ->> 'is_test_data')::boolean = %s")
        params.append(bool(filters["is_test_data"]))
    return " AND ".join(clauses), params


def _pg_query_where(query: RetrievalQuery) -> tuple[str, list[Any]]:
    clauses = ["shop_id = %s", "domain = %s"]
    params: list[Any] = [query.shop_id, query.domain]
    if query.version:
        clauses.append("version = %s")
        params.append(query.version)
    filters = dict(query.filters or {})
    source_type = str(filters.get("source_type") or "").strip()
    if source_type:
        clauses.append("source_type = %s")
        params.append(source_type)
    source_id = str(filters.get("source_id") or filters.get("goods_id") or "").strip()
    if source_id:
        clauses.append("(source_id = %s OR metadata_json ->> 'source_id' = %s OR metadata_json ->> 'goods_id' = %s)")
        params.extend([source_id, source_id, source_id])
    version_id = str(filters.get("version_id") or "").strip()
    if version_id:
        clauses.append("metadata_json ->> 'version_id' = %s")
        params.append(version_id)
    filter_version = str(filters.get("version") or "").strip()
    if filter_version and not query.version:
        clauses.append("version = %s")
        params.append(filter_version)
    namespace = str(filters.get("namespace") or "").strip()
    if namespace:
        clauses.append("(namespace = %s OR metadata_json ->> 'namespace' = %s)")
        params.extend([namespace, namespace])
    return " AND ".join(clauses), params


def _legacy_audit_where_sql(
    *,
    source_type_prefix: str,
    legacy_version: str,
    legacy_wrong_shop_id: str,
    legacy_domain: str,
) -> tuple[str, list[Any]]:
    clauses = ["source_type LIKE %s"]
    params: list[Any] = [source_type_prefix + "%"]
    aux: list[str] = [
        "version = %s",
        "shop_id = %s",
        "chunk_id LIKE %s",
        "source_id LIKE %s",
        "NOT (metadata_json ? 'namespace')",
        "NOT (metadata_json ? 'is_test_data')",
    ]
    params.extend([legacy_version, legacy_wrong_shop_id, "%pollution%", "%pollution%"])
    if legacy_domain:
        aux.append("domain = %s")
        params.append(legacy_domain)
    clauses.append("(" + " OR ".join(aux) + ")")
    return " AND ".join(clauses), params


def _legacy_delete_where_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = ["source_type LIKE %s"]
    params: list[Any] = [filters["source_type_prefix"] + "%"]
    if filters["version"]:
        clauses.append("version = %s")
        params.append(filters["version"])
    if filters["shop_id"]:
        clauses.append("shop_id = %s")
        params.append(filters["shop_id"])
    if filters["domain"]:
        clauses.append("domain = %s")
        params.append(filters["domain"])
    if filters["index_run_id"]:
        clauses.append("(index_run_id = %s OR metadata_json ->> 'index_run_id' = %s)")
        params.extend([filters["index_run_id"], filters["index_run_id"]])
    return " AND ".join(clauses), params


def _row_to_hit(row: Any) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=row[0],
        shop_id=row[1],
        domain=row[2],
        title=row[3],
        content_summary=row[4],
        score=float(row[5]),
        source_type=row[6],
        source_id=row[7],
        version=row[8],
        content_hash=row[9],
        metadata=dict(row[10] or {}),
    )


def _with_match(hit: RetrievalHit, match_type: str) -> RetrievalHit:
    metadata = dict(hit.metadata or {})
    metadata["retrieval_match"] = match_type
    return replace(hit, metadata=metadata)


def _dedupe_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    result: list[RetrievalHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        metadata = dict(hit.metadata or {})
        goods_id = str(metadata.get("goods_id") or hit.source_id or "").strip()
        key = (goods_id, hit.content_hash or hit.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
    return result


def _rrf_merge(
    semantic_hits: list[RetrievalHit],
    fulltext_hits: list[RetrievalHit],
    *,
    top_k: int,
    semantic_weight: float = 0.5,
    fulltext_weight: float = 0.5,
    rrf_k: int = 60,
) -> list[RetrievalHit]:
    scores: dict[tuple[str, str], float] = {}
    selected: dict[tuple[str, str], RetrievalHit] = {}

    def add(hits: list[RetrievalHit], weight: float) -> None:
        for rank, hit in enumerate(hits, start=1):
            metadata = dict(hit.metadata or {})
            key = (str(metadata.get("goods_id") or hit.source_id or "").strip(), hit.content_hash or hit.chunk_id)
            scores[key] = scores.get(key, 0.0) + weight * (1.0 / (rrf_k + rank))
            if key not in selected or hit.score > selected[key].score:
                selected[key] = hit

    add(semantic_hits, semantic_weight)
    add(fulltext_hits, fulltext_weight)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [replace(selected[key], score=score) for key, score in ranked[:top_k]]


def _keyword_overlap(query: str, text: str) -> bool:
    target = str(text or "").lower()
    return any(keyword and keyword.lower() in target for keyword in _query_keywords(query))


def _best_keyword(query: str) -> str:
    keywords = _query_keywords(query)
    return keywords[0] if keywords else ""


def _query_keywords(query: str) -> list[str]:
    import re

    text = str(query or "").strip()
    candidates = [
        "怎么用",
        "用法",
        "多少钱",
        "价格",
        "规格",
        "成分",
        "保质期",
        "适合",
        "usage",
        "price",
        "spec",
        "ingredient",
        "shelf",
    ]
    found = [keyword for keyword in candidates if keyword.lower() in text.lower()]
    parts = [part for part in re.split(r"\s+|[,，。;；:：]+", text) if len(part) >= 2]
    result: list[str] = []
    for keyword in [*found, *parts]:
        if keyword not in result:
            result.append(keyword)
    return result[:8]


def _short_hash(value: object) -> str:
    import hashlib

    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    length = min(len(left), len(right))
    if length == 0:
        return 0.0
    dot = sum(left[index] * right[index] for index in range(length))
    left_norm = math.sqrt(sum(left[index] * left[index] for index in range(length)))
    right_norm = math.sqrt(sum(right[index] * right[index] for index in range(length)))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def mask_pg_dsn(dsn: str) -> str:
    if not dsn:
        return ""
    try:
        parsed = urlsplit(dsn)
    except ValueError:
        return "<invalid-dsn>"
    if not parsed.netloc:
        return dsn
    try:
        user = parsed.username or ""
        host = parsed.hostname or ""
        port_value = parsed.port
    except ValueError:
        return "<invalid-dsn>"
    port = f":{port_value}" if port_value else ""
    auth = f"{user}:***@" if user else ""
    return urlunsplit((parsed.scheme, f"{auth}{host}{port}", parsed.path, "", ""))


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
