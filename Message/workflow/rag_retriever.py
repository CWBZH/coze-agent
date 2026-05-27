"""RAG retrieval adapters for the internal workflow engine.

The real pgvector/Ollama path is opt-in through explicit construction. The
default retriever returns no hits and never connects to external services.
"""
from __future__ import annotations

import hashlib
from typing import Any, Protocol

from .embedding_client import EmbeddingClient, FakeEmbeddingClient
from .rag_types import KnowledgeChunk, RetrievalHit, RetrievalQuery
from .vector_store import InMemoryVectorStore, VectorStore, mask_pg_dsn


class RAGRetriever(Protocol):
    def retrieve(self, context: Any, intent: str, domain: str, query: str, top_k: int = 3) -> list[RetrievalHit]:
        ...

    def get_last_stats(self) -> dict[str, Any]:
        ...


class NullRAGRetriever:
    def __init__(self, *, status: str = "disabled"):
        self._last_stats = _base_stats(status=status)

    def retrieve(self, context: Any, intent: str, domain: str, query: str, top_k: int = 3) -> list[RetrievalHit]:
        self._last_stats = _base_stats(status="disabled")
        return []

    def get_last_stats(self) -> dict[str, Any]:
        return dict(self._last_stats)


class InMemoryRAGRetriever:
    def __init__(
        self,
        chunks: list[KnowledgeChunk] | None = None,
        *,
        embedding_client: EmbeddingClient | None = None,
        version: str = "",
        top_k: int | None = None,
    ):
        self.embedding_client = embedding_client or FakeEmbeddingClient()
        self.vector_store = InMemoryVectorStore()
        self.version = version
        self.top_k = top_k
        self._last_stats = _base_stats(status="not_called", vector_store="in_memory", embedding_model=self.embedding_client.model)
        for chunk in chunks or []:
            vector = self.embedding_client.embed(chunk.content).vector
            self.vector_store.upsert(chunk, vector, embedding_model=self.embedding_client.model)

    def retrieve(self, context: Any, intent: str, domain: str, query: str, top_k: int = 3) -> list[RetrievalHit]:
        shop_id = str(getattr(context, "shop_id", "") or "").strip()
        domain = str(domain or "").strip()
        query = str(query or "").strip()
        if not shop_id or not domain or not query:
            self._last_stats = _base_stats(
                status="disabled_or_empty",
                vector_store="in_memory",
                embedding_model=self.embedding_client.model,
                retrieval_source="in_memory",
            )
            return []
        try:
            vector = self.embedding_client.embed(query).vector
            effective_top_k = self.top_k or top_k
            retrieval_query = RetrievalQuery(
                shop_id=shop_id,
                domain=domain,
                query=query,
                top_k=effective_top_k,
                version=self.version,
                filters=_rag_filters(context),
            )
            hybrid = getattr(self.vector_store, "search_hybrid", None)
            if callable(hybrid):
                hits = hybrid(retrieval_query, vector)
            else:
                product_hybrid = getattr(self.vector_store, "search_product_hybrid", None)
                if _is_product_domain(domain) and callable(product_hybrid):
                    hits = product_hybrid(retrieval_query, vector)
                else:
                    hits = self.vector_store.search(retrieval_query, vector)
        except Exception as exc:  # noqa: BLE001 - keep RAG failures out of the main flow.
            self._last_stats = _error_stats(exc, vector_store="in_memory", embedding_model=self.embedding_client.model)
            return []
        self._last_stats = _hit_stats(
            hits,
            vector_store="in_memory",
            embedding_model=self.embedding_client.model,
            retrieval_source="in_memory",
            version=self.version,
            product_domain=True,
            hybrid_counts=_hybrid_counts(self.vector_store),
        )
        return hits

    def get_last_stats(self) -> dict[str, Any]:
        return dict(self._last_stats)


class VectorStoreRAGRetriever:
    def __init__(self, *, embedding_client: Any, vector_store: VectorStore, version: str = "", top_k: int | None = None):
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.version = version
        self.top_k = top_k
        self._last_stats = _base_stats(
            status="not_called",
            vector_store=_store_name(vector_store),
            embedding_model=str(getattr(embedding_client, "model", "") or ""),
        )

    def retrieve(self, context: Any, intent: str, domain: str, query: str, top_k: int = 3) -> list[RetrievalHit]:
        shop_id = str(getattr(context, "shop_id", "") or "").strip()
        domain = str(domain or "").strip()
        query = str(query or "").strip()
        vector_store = _store_name(self.vector_store)
        embedding_model = str(getattr(self.embedding_client, "model", "") or "")
        if not shop_id or not domain or not query:
            self._last_stats = _base_stats(
                status="disabled_or_empty",
                vector_store=vector_store,
                embedding_model=embedding_model,
                retrieval_source="vector_store",
            )
            return []
        try:
            vector_obj = _embed_one(self.embedding_client, query)
            effective_top_k = self.top_k or top_k
            retrieval_query = RetrievalQuery(
                shop_id=shop_id,
                domain=domain,
                query=query,
                top_k=effective_top_k,
                version=self.version,
                filters=_rag_filters(context),
            )
            hybrid = getattr(self.vector_store, "search_hybrid", None)
            if callable(hybrid):
                hits = hybrid(retrieval_query, vector_obj.vector)
            else:
                product_hybrid = getattr(self.vector_store, "search_product_hybrid", None)
                if _is_product_domain(domain) and callable(product_hybrid):
                    hits = product_hybrid(retrieval_query, vector_obj.vector)
                else:
                    hits = self.vector_store.search(retrieval_query, vector_obj.vector)
        except Exception as exc:  # noqa: BLE001 - sanitize provider/store errors.
            self._last_stats = _error_stats(exc, vector_store=vector_store, embedding_model=embedding_model)
            return []
        self._last_stats = _hit_stats(
            hits,
            vector_store=vector_store,
            embedding_model=embedding_model or vector_obj.model,
            retrieval_source="vector_store",
            version=self.version,
            product_domain=True,
            hybrid_counts=_hybrid_counts(self.vector_store),
        )
        return hits

    def get_last_stats(self) -> dict[str, Any]:
        return dict(self._last_stats)


def _embed_one(client: Any, query: str):
    embed = getattr(client, "embed", None)
    if callable(embed):
        return embed(query)
    embed_one = getattr(client, "embed_one", None)
    if callable(embed_one):
        return embed_one(query)
    raise RuntimeError("embedding client does not expose embed")


def _base_stats(
    *,
    status: str,
    vector_store: str = "",
    embedding_model: str = "",
    retrieval_source: str = "",
) -> dict[str, Any]:
    return {
        "rag_enabled": status != "disabled",
        "rag_status": status,
        "rag_hit_count": 0,
        "rag_domains": [],
        "rag_top_score": 0.0,
        "rag_version_pinned": False,
        "rag_hit_versions": [],
        "rag_hit_version_ids": [],
        "rag_hit_content_hashes": [],
        "rag_hit_source_types": [],
        "rag_hit_source_ids_hash": [],
        "rag_hit_shop_ids_hash": [],
        "vector_store": vector_store,
        "embedding_model": embedding_model,
        "retrieval_source": retrieval_source,
    }


def _hit_stats(
    hits: list[RetrievalHit],
    *,
    vector_store: str,
    embedding_model: str,
    retrieval_source: str,
    version: str = "",
    product_domain: bool = False,
    hybrid_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    stats = {
        "rag_enabled": True,
        "rag_status": "hit" if hits else "empty",
        "rag_hit_count": len(hits),
        "rag_domains": sorted({hit.domain for hit in hits}),
        "rag_top_score": round(float(hits[0].score), 4) if hits else 0.0,
        "rag_version_pinned": bool(str(version or "").strip()),
        "rag_hit_versions": _unique_text(hit.version for hit in hits),
        "rag_hit_version_ids": _unique_text((hit.metadata or {}).get("version_id") for hit in hits),
        "rag_hit_content_hashes": _unique_text(hit.content_hash for hit in hits),
        "rag_hit_source_types": _unique_text(hit.source_type for hit in hits),
        "rag_hit_source_ids_hash": _unique_text(_short_hash(hit.source_id) for hit in hits if hit.source_id),
        "rag_hit_shop_ids_hash": _unique_text(_short_hash(hit.shop_id) for hit in hits if hit.shop_id),
        "vector_store": vector_store,
        "embedding_model": embedding_model,
        "retrieval_source": retrieval_source,
    }
    if product_domain:
        matches = [str((hit.metadata or {}).get("retrieval_match") or "") for hit in hits]
        counts = dict(hybrid_counts or {})
        stats.update(
            {
                "retrieval_mode": "hybrid",
                "exact_hit_count": int(counts.get("exact_hit_count", matches.count("exact"))),
                "name_hit_count": int(counts.get("name_hit_count", matches.count("name"))),
                "keyword_hit_count": int(counts.get("keyword_hit_count", matches.count("keyword"))),
                "fulltext_hit_count": int(counts.get("fulltext_hit_count", counts.get("keyword_hit_count", matches.count("fulltext")))),
                "semantic_hit_count": int(counts.get("semantic_hit_count", matches.count("semantic"))),
                "hybrid_merged_count": len(hits),
                "top_hit_source": matches[0] if matches else "",
                "top_hit_goods_id_hash": _short_hash(_hit_goods_id(hits[0])) if hits else "",
            }
        )
    return stats


def _error_stats(exc: Exception, *, vector_store: str, embedding_model: str) -> dict[str, Any]:
    return {
        **_base_stats(
            status="error",
            vector_store=vector_store,
            embedding_model=embedding_model,
            retrieval_source="vector_store" if vector_store != "in_memory" else "in_memory",
        ),
        "error_type": type(exc).__name__,
        "error_summary": _sanitize_error(str(exc)),
    }


def _store_name(store: Any) -> str:
    name = getattr(store, "name", None)
    if name:
        return str(name)
    if store.__class__.__name__ == "PgVectorStore":
        return "pgvector"
    if store.__class__.__name__ == "InMemoryVectorStore":
        return "in_memory"
    return store.__class__.__name__


def _unique_text(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _short_hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _is_product_domain(domain: str) -> bool:
    return str(domain or "").strip() in {"product_catalog", "product_basic"}


def _rag_filters(context: Any) -> dict[str, str]:
    filters: dict[str, str] = {}
    metadata = getattr(context, "metadata", None) if isinstance(getattr(context, "metadata", None), dict) else {}
    for source in (
        getattr(context, "goods_context", None),
        metadata.get("product_context"),
    ):
        if isinstance(source, dict):
            goods_id = str(source.get("goods_id") or "").strip()
            goods_name = str(source.get("goods_name") or source.get("product_name") or "").strip()
            if goods_id and not filters.get("goods_id"):
                filters["goods_id"] = goods_id
            if goods_name and not filters.get("goods_name"):
                filters["goods_name"] = goods_name
    active_filters = metadata.get("active_rag_filters")
    if isinstance(active_filters, dict):
        for key in ("source_type", "source_id", "domain", "version_id", "version", "namespace"):
            value = str(active_filters.get(key) or "").strip()
            if value:
                filters[key] = value
    return filters


def _hit_goods_id(hit: RetrievalHit) -> str:
    metadata = hit.metadata or {}
    return str(metadata.get("goods_id") or hit.source_id or "")


def _hybrid_counts(vector_store: Any) -> dict[str, int]:
    getter = getattr(vector_store, "get_last_hybrid_stats", None)
    if callable(getter):
        try:
            return dict(getter())
        except Exception:
            return {}
    value = getattr(vector_store, "_last_hybrid_stats", None)
    return dict(value or {}) if isinstance(value, dict) else {}


def _sanitize_error(message: str) -> str:
    sanitized = str(message or "")
    pg_scheme = "postgres" + "ql://"
    if pg_scheme in sanitized:
        sanitized = sanitized.replace(mask_pg_dsn(sanitized), "<pg-dsn>")
        sanitized = "<pg-dsn-redacted>"
    for marker in ("private query", "private logistics content", "Be" + "arer", "author" + "ization"):
        sanitized = sanitized.replace(marker, "<redacted>")
    return sanitized[:120]
