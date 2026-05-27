"""No-send RAG indexing smoke for internal workflow.

Defaults use fake embeddings and an in-memory vector store. Real Ollama or
pgvector are only used when explicitly requested by flags.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - import order avoids existing logger cycle in tests.
from Message.workflow.chunk_builder import build_product_chunks, build_sop_chunks
from Message.workflow.embedding_client import FakeEmbeddingClient, OllamaBgeM3EmbeddingClient
from Message.workflow.rag_types import KnowledgeChunk, stable_content_hash
from Message.workflow.sop_loader import load_sop_markdown
from Message.workflow.vector_store import mask_pg_dsn
from Message.workflow.vector_store import InMemoryVectorStore, PgVectorStore
from scripts.acceptance.internal_pgvector_smoke import DEFAULT_SCHEMA


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and optionally index internal RAG chunks.")
    parser.add_argument("--shop-id", required=True)
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--sop-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--embedding-provider", choices=["fake", "ollama"], default="fake")
    parser.add_argument("--embedding-model", default="bge-m3")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--embedding-dimension", type=int, default=1024)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--pollution-fixture", action="store_true")
    parser.add_argument("--pollution-kind", choices=["old_version", "wrong_shop", "wrong_domain", "all"], default="all")
    parser.add_argument("--pollution-version", default="old-version")
    parser.add_argument("--pollution-shop-id", default="synthetic-shop-2")
    parser.add_argument("--pollution-domain", default="after_sales_evidence")
    parser.add_argument("--index-run-id", default="")
    parser.add_argument("--namespace", default="acceptance")
    parser.add_argument("--test-data", action="store_true")
    parser.add_argument("--created-by", default="internal_rag_index")
    parser.add_argument("--product-fixture", action="store_true")
    parser.add_argument("--product-version", default="product-test-v1")
    parser.add_argument("--product-domain", choices=["product_basic", "product_catalog"], default="product_catalog")
    return parser.parse_args(argv)


def run_index(args: argparse.Namespace) -> dict[str, Any]:
    real_error = _validate_real_args(args)
    if real_error:
        return real_error
    args.index_run_id = getattr(args, "index_run_id", "") or _new_index_run_id()
    args.namespace = getattr(args, "namespace", "") or "acceptance"
    chunks = build_chunks(args)
    pollution_chunks = [chunk for chunk in chunks if chunk.source_type.startswith("pollution_")]
    product_chunks = [chunk for chunk in chunks if chunk.source_type == "product"]
    domains = sorted({chunk.domain for chunk in chunks})
    versions = sorted({chunk.version for chunk in chunks})
    calls_ollama = args.embedding_provider == "ollama" and not args.dry_run
    connects_pgvector = bool(args.pg_dsn) and not args.dry_run
    status = "dry_run" if args.dry_run else "ok"
    embedded_count = 0
    indexed_count = 0

    if not args.dry_run:
        embedder = _embedding_client(args)
        store = PgVectorStore(args.pg_dsn) if args.pg_dsn else InMemoryVectorStore()
        if args.pg_dsn and getattr(args, "apply_schema", False):
            store.apply_schema(DEFAULT_SCHEMA)
        for chunk in chunks:
            vector = embedder.embed(chunk.content)
            store.upsert(chunk, vector.vector, embedding_model=vector.model)
            embedded_count += 1
            indexed_count += 1

    payload = {
        "status": status,
        "chunk_count": len(chunks),
        "embedded_count": embedded_count,
        "indexed_count": indexed_count,
        "shop_id_hash": _hash(args.shop_id),
        "domains": domains,
        "versions": versions,
        "embedding_model": args.embedding_model,
        "vector_store": "pgvector" if args.pg_dsn else "in_memory",
        "calls_ollama": calls_ollama,
        "connects_pgvector": connects_pgvector,
        "index_run_id": args.index_run_id,
        "namespace": args.namespace,
        "is_test_data": bool(getattr(args, "test_data", False)),
        "pollution_indexed": bool(pollution_chunks) and not args.dry_run,
        "pollution_kind": args.pollution_kind if getattr(args, "pollution_fixture", False) else "",
        "pollution_chunk_count": len(pollution_chunks),
        "pollution_versions": sorted({chunk.version for chunk in pollution_chunks}),
        "pollution_shop_ids_hash": sorted({_hash(chunk.shop_id) for chunk in pollution_chunks}),
        "pollution_domains": sorted({chunk.domain for chunk in pollution_chunks}),
        "pollution_is_test_data": bool(pollution_chunks),
        "product_chunk_count": len(product_chunks),
        "product_version": str(getattr(args, "product_version", "") or ""),
        "product_domains": sorted({chunk.domain for chunk in product_chunks}),
    }
    return payload


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
        "chunk_count": 0,
        "embedded_count": 0,
        "indexed_count": 0,
        "shop_id_hash": _hash(args.shop_id),
        "domains": [],
        "versions": [],
        "embedding_model": args.embedding_model,
        "vector_store": "pgvector" if args.pg_dsn else "none",
        "calls_ollama": False,
        "connects_pgvector": False,
        "dsn": mask_pg_dsn(args.pg_dsn),
        "index_run_id": str(getattr(args, "index_run_id", "") or ""),
        "namespace": str(getattr(args, "namespace", "") or "acceptance"),
        "is_test_data": bool(getattr(args, "test_data", False)),
        "pollution_indexed": False,
        "pollution_kind": "",
        "pollution_chunk_count": 0,
        "pollution_versions": [],
        "pollution_shop_ids_hash": [],
        "pollution_domains": [],
        "pollution_is_test_data": False,
        "product_chunk_count": 0,
        "product_version": str(getattr(args, "product_version", "") or "product-test-v1"),
        "product_domains": [],
    }


def build_chunks(args: argparse.Namespace):
    raw_domains = args.domain or []
    if isinstance(raw_domains, str):
        raw_domains = [raw_domains]
    domains = set(raw_domains)
    chunks = []
    if getattr(args, "product_fixture", False) or not getattr(args, "sop_file", None):
        chunks.extend(
            build_product_chunks(
                _fake_product_records(args.shop_id),
                version=str(getattr(args, "product_version", "") or "product-test-v1"),
                domain=str(getattr(args, "product_domain", "") or "product_catalog"),
                index_run_id=getattr(args, "index_run_id", ""),
                namespace=getattr(args, "namespace", "acceptance"),
                is_test_data=bool(getattr(args, "test_data", False)),
                created_by=getattr(args, "created_by", "internal_rag_index"),
            )
        )
    if args.sop_file:
        sop_result = load_sop_markdown(args.sop_file, shop_id=args.shop_id, domains=domains or None)
        chunks.extend(
            build_sop_chunks(
                sop_result.records,
                index_run_id=getattr(args, "index_run_id", ""),
                namespace=getattr(args, "namespace", "acceptance"),
                is_test_data=bool(getattr(args, "test_data", False)),
                created_by=getattr(args, "created_by", "internal_rag_index"),
            )
        )
    if getattr(args, "pollution_fixture", False):
        chunks.extend(_build_pollution_chunks(args))
    if domains:
        chunks = [chunk for chunk in chunks if chunk.domain in domains or chunk.source_type.startswith("pollution_")]
    return chunks


def _build_pollution_chunks(args: argparse.Namespace) -> list[KnowledgeChunk]:
    kinds = ["old_version", "wrong_shop", "wrong_domain"] if args.pollution_kind == "all" else [args.pollution_kind]
    chunks: list[KnowledgeChunk] = []
    for kind in kinds:
        if kind == "old_version":
            chunks.append(
                _pollution_chunk(
                    shop_id=args.shop_id,
                    domain="logistics_policy",
                    version=args.pollution_version,
                    source_type="pollution_old_version",
                    source_id="pollution-old-version-001",
                    title="Synthetic old version pollution",
                    body="Synthetic old-version logistics policy pollution. Order page remains authoritative.",
                    args=args,
                )
            )
        elif kind == "wrong_shop":
            chunks.append(
                _pollution_chunk(
                    shop_id=args.pollution_shop_id,
                    domain="logistics_policy",
                    version="sop-test-v1",
                    source_type="pollution_wrong_shop",
                    source_id="pollution-wrong-shop-001",
                    title="Synthetic wrong shop pollution",
                    body="Synthetic wrong-shop logistics policy pollution. Order page remains authoritative.",
                    args=args,
                )
            )
        elif kind == "wrong_domain":
            chunks.append(
                _pollution_chunk(
                    shop_id=args.shop_id,
                    domain=args.pollution_domain,
                    version="sop-test-v1",
                    source_type="pollution_wrong_domain",
                    source_id="pollution-wrong-domain-001",
                    title="Synthetic wrong domain pollution",
                    body="Synthetic wrong-domain policy pollution. Evidence is required before after-sales handling.",
                    args=args,
                )
            )
    return chunks


def _pollution_chunk(
    *,
    shop_id: str,
    domain: str,
    version: str,
    source_type: str,
    source_id: str,
    title: str,
    body: str,
    args: argparse.Namespace,
) -> KnowledgeChunk:
    content = f"{title}\n{body}"
    chunk_id = f"{source_type}:{shop_id}:{domain}:{version}:{stable_content_hash(content)[:12]}"
    return KnowledgeChunk(
        chunk_id=chunk_id,
        shop_id=shop_id,
        domain=domain,
        source_type=source_type,
        source_id=source_id,
        title=title,
        content=content,
        version=version,
        metadata={
            "fixture": "pollution",
            "domain": domain,
            "index_run_id": getattr(args, "index_run_id", ""),
            "namespace": getattr(args, "namespace", "acceptance"),
            "is_test_data": True,
            "created_by": getattr(args, "created_by", "internal_rag_index"),
        },
    )


def _embedding_client(args: argparse.Namespace):
    if args.embedding_provider == "ollama":
        return OllamaBgeM3EmbeddingClient(base_url=args.ollama_base_url, model=args.embedding_model)
    return FakeEmbeddingClient(dimension=args.embedding_dimension, model=args.embedding_model)


def _fake_product_records(shop_id: str) -> list[dict[str, str]]:
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
            "manual_notes": "Synthetic record for no-send RAG smoke.",
        }
    ]


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _new_index_run_id() -> str:
    return "rag-run-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def write_payload(payload: dict[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
    else:
        print("internal_rag_index: " + rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_index(args)
    if args.output_json:
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_payload(payload, json_only=args.json_only)
    return 1 if payload.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
