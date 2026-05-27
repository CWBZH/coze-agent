"""Core RAG data types for the internal workflow engine.

These types are storage-agnostic and intentionally safe for tests. Full chunk
content and raw vectors are not intended for logs or acceptance artifacts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def stable_content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def stable_json_hash(payload: Any) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def content_summary(content: str, *, limit: int = 120) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def chunk_metadata_value(chunk: "KnowledgeChunk", key: str, default: Any = "") -> Any:
    return dict(chunk.metadata or {}).get(key, default)


def chunk_index_run_id(chunk: "KnowledgeChunk") -> str:
    return str(chunk_metadata_value(chunk, "index_run_id", "") or "")


def chunk_namespace(chunk: "KnowledgeChunk") -> str:
    return str(chunk_metadata_value(chunk, "namespace", "") or "")


def chunk_is_test_data(chunk: "KnowledgeChunk") -> bool:
    value = chunk_metadata_value(chunk, "is_test_data", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    shop_id: str
    domain: str
    source_type: str
    source_id: str
    title: str
    content: str
    version: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(self, "content_hash", stable_content_hash(self.content))

    def validate(self) -> list[str]:
        errors: list[str] = []
        for field_name in ("chunk_id", "shop_id", "domain", "source_type", "source_id", "version"):
            if not str(getattr(self, field_name) or "").strip():
                errors.append(f"{field_name} is required")
        return errors


@dataclass(frozen=True)
class EmbeddingVector:
    model: str
    dimension: int
    vector: list[float]
    vector_hash: str = ""

    def __post_init__(self) -> None:
        if not self.vector_hash:
            object.__setattr__(self, "vector_hash", stable_json_hash([round(float(v), 8) for v in self.vector]))
        if not self.dimension:
            object.__setattr__(self, "dimension", len(self.vector))


@dataclass(frozen=True)
class RetrievalQuery:
    shop_id: str
    domain: str
    query: str
    top_k: int = 5
    version: str = ""
    filters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not str(self.shop_id or "").strip():
            errors.append("shop_id is required")
        if not str(self.domain or "").strip():
            errors.append("domain is required")
        if self.top_k <= 0:
            errors.append("top_k must be positive")
        return errors


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: str
    shop_id: str
    domain: str
    title: str
    content_summary: str
    score: float
    source_type: str
    source_id: str
    version: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: KnowledgeChunk, *, score: float) -> "RetrievalHit":
        return cls(
            chunk_id=chunk.chunk_id,
            shop_id=chunk.shop_id,
            domain=chunk.domain,
            title=chunk.title,
            content_summary=content_summary(chunk.content),
            score=score,
            source_type=chunk.source_type,
            source_id=chunk.source_id,
            version=chunk.version,
            content_hash=chunk.content_hash,
            metadata=_safe_metadata(chunk.metadata),
        )


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    forbidden = {"content", "raw_db_row", "full_product_detail", "full_sop", "api_key", "token", "cookie"}
    return {str(key): value for key, value in dict(metadata or {}).items() if str(key).lower() not in forbidden}
