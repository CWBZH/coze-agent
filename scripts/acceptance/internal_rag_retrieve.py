"""No-send RAG retrieval smoke for internal workflow."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - import order avoids existing logger cycle in tests.
from Message.workflow.embedding_client import FakeEmbeddingClient, OllamaBgeM3EmbeddingClient
from Message.workflow.rag_types import RetrievalQuery
from Message.workflow.vector_store import mask_pg_dsn
from Message.workflow.vector_store import InMemoryVectorStore, PgVectorStore
from scripts.acceptance.internal_rag_index import build_chunks


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run metadata-only internal RAG retrieval smoke.")
    parser.add_argument("--shop-id", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--version", default="", help="Optional knowledge version pin.")
    parser.add_argument("--sop-file", type=Path)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--embedding-provider", choices=["fake", "ollama"], default="fake")
    parser.add_argument("--embedding-model", default="bge-m3")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--embedding-dimension", type=int, default=1024)
    parser.add_argument("--real", action="store_true")
    return parser.parse_args(argv)


def run_retrieve(args: argparse.Namespace) -> dict[str, Any]:
    real_error = _validate_real_args(args)
    if real_error:
        return real_error
    calls_ollama = args.embedding_provider == "ollama"
    connects_pgvector = bool(args.pg_dsn)
    embedder = _embedding_client(args)
    store = PgVectorStore(args.pg_dsn) if args.pg_dsn else InMemoryVectorStore()

    if not args.pg_dsn:
        for chunk in build_chunks(args):
            vector = embedder.embed(chunk.content)
            store.upsert(chunk, vector.vector, embedding_model=vector.model)

    query_vector = embedder.embed(args.query)
    hits = store.search(
        RetrievalQuery(shop_id=args.shop_id, domain=args.domain, query=args.query, top_k=args.top_k, version=getattr(args, "version", "") or ""),
        query_vector.vector,
    )
    return {
        "status": "ok",
        "hit_count": len(hits),
        "hits": [
            {
                "chunk_id": hit.chunk_id,
                "shop_id_hash": _hash(hit.shop_id),
                "domain": hit.domain,
                "title_hash": _hash(hit.title),
                "score": round(float(hit.score), 6),
                "version": hit.version,
                "content_hash": hit.content_hash,
                "source_type": hit.source_type,
                "source_id_hash": _hash(hit.source_id),
            }
            for hit in hits
        ],
        "calls_ollama": calls_ollama,
        "connects_pgvector": connects_pgvector,
    }


def _validate_real_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if not getattr(args, "real", False):
        return None
    if not args.pg_dsn:
        return _error_payload(args, "missing_pg_dsn")
    if args.embedding_provider != "ollama":
        return _error_payload(args, "real_requires_ollama")
    return None


def _error_payload(args: argparse.Namespace, error_type: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error_type": error_type,
        "hit_count": 0,
        "hits": [],
        "calls_ollama": False,
        "connects_pgvector": False,
        "dsn": mask_pg_dsn(args.pg_dsn),
    }


def _embedding_client(args: argparse.Namespace):
    if args.embedding_provider == "ollama":
        return OllamaBgeM3EmbeddingClient(base_url=args.ollama_base_url, model=args.embedding_model)
    return FakeEmbeddingClient(dimension=args.embedding_dimension, model=args.embedding_model)


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_retrieve(args)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json_only:
        print(rendered)
    else:
        print("internal_rag_retrieve: " + rendered)
    return 1 if payload.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
