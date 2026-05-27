"""Read-only product knowledge RAG indexing profile.

The script reads product_knowledge from SQLite in read-only mode and writes
only to the selected vector store when explicitly requested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - import order avoids existing logger cycle.
from Message.workflow.chunk_builder import build_product_chunks
from Message.workflow.embedding_client import FakeEmbeddingClient, OllamaBgeM3EmbeddingClient
from Message.workflow.vector_store import InMemoryVectorStore, PgVectorStore


PRODUCT_COLUMNS = (
    "goods_id",
    "goods_name",
    "price",
    "price_min",
    "price_max",
    "specifications",
    "usage_method",
    "ingredients",
    "shelf_life",
    "warnings",
    "knowledge_status",
    "manual_notes",
    "fastgpt_answer",
    "created_at",
    "updated_at",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only product DB to RAG indexing smoke.")
    parser.add_argument("--product-db-path", type=Path, required=True)
    parser.add_argument("--from-product-db", action="store_true")
    parser.add_argument("--shop-id", required=True)
    parser.add_argument("--product-version", default="real-product-v1")
    parser.add_argument("--product-domain", choices=["product_catalog", "product_basic"], default="product_catalog")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--embedding-provider", choices=["fake", "ollama"], default="fake")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--embedding-model", default="bge-m3")
    parser.add_argument("--embedding-dimension", type=int, default=1024)
    parser.add_argument("--namespace", default="acceptance")
    parser.add_argument("--index-run-id", default="")
    return parser.parse_args(argv)


def run_index(args: argparse.Namespace) -> dict[str, Any]:
    if not str(args.shop_id or "").strip():
        return _base_payload(args, status="error", error_type="missing_shop_id")
    if not getattr(args, "from_product_db", False):
        return _base_payload(args, status="error", error_type="missing_from_product_db")
    real_error = _validate_real_args(args)
    if real_error:
        return real_error
    if not args.product_db_path.exists():
        return _base_payload(args, status="missing")

    records_result = _load_product_records(args)
    if records_result["status"] != "ok":
        return {**_base_payload(args, status=records_result["status"], error_type=records_result.get("error_type", ""))}

    records = records_result["records"]
    index_run_id = str(args.index_run_id or _new_index_run_id())
    chunks = build_product_chunks(
        records,
        version=str(args.product_version or "real-product-v1"),
        domain=str(args.product_domain or "product_catalog"),
        index_run_id=index_run_id,
        namespace=str(args.namespace or "acceptance"),
        is_test_data=False,
        created_by="internal_product_rag_index",
    )

    embedded_count = 0
    indexed_count = 0
    calls_ollama = bool(args.real and args.embedding_provider == "ollama" and not args.dry_run)
    connects_pgvector = bool(args.real and args.pg_dsn and not args.dry_run)
    if not args.dry_run:
        try:
            embedder = _embedding_client(args)
            store = PgVectorStore(args.pg_dsn) if args.real else InMemoryVectorStore()
            for chunk in chunks:
                vector = embedder.embed(chunk.content)
                store.upsert(chunk, vector.vector, embedding_model=vector.model)
                embedded_count += 1
                indexed_count += 1
        except Exception as exc:  # noqa: BLE001 - sanitized provider/store failure.
            return {
                **_base_payload(args, status="error", error_type=type(exc).__name__),
                "source_record_count": len(records),
                "product_chunk_count": len(chunks),
                "calls_ollama": calls_ollama,
                "connects_pgvector": connects_pgvector,
                "vector_store": "pgvector" if args.real else "in_memory",
                "index_run_id": index_run_id,
            }

    return {
        **_base_payload(args, status="dry_run" if args.dry_run else "ok"),
        "source_record_count": len(records),
        "product_chunk_count": len(chunks),
        "embedded_count": embedded_count,
        "indexed_count": indexed_count,
        "product_version": str(args.product_version or "real-product-v1"),
        "product_domain": str(args.product_domain or "product_catalog"),
        "source_type": "product",
        "calls_ollama": calls_ollama,
        "connects_pgvector": connects_pgvector,
        "vector_store": "pgvector" if args.real else "in_memory",
        "embedding_model": str(args.embedding_model or "bge-m3"),
        "index_run_id": index_run_id,
        "namespace": str(args.namespace or "acceptance"),
    }


def _load_product_records(args: argparse.Namespace) -> dict[str, Any]:
    uri = f"file:{args.product_db_path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "product_knowledge"):
                return {"status": "missing_table", "records": []}
            columns = _table_columns(conn, "product_knowledge")
            rows = _query_product_rows(conn, columns, shop_id=str(args.shop_id), limit=max(1, int(args.limit or 50)))
    except sqlite3.OperationalError as exc:
        return {"status": "error", "error_type": type(exc).__name__, "records": []}
    return {"status": "ok", "records": rows}


def _query_product_rows(
    conn: sqlite3.Connection,
    columns: set[str],
    *,
    shop_id: str,
    limit: int,
) -> list[dict[str, str]]:
    select_cols = [column for column in PRODUCT_COLUMNS if column in columns]
    if "shop_id" in columns:
        select_cols.append("shop_id")
    select_sql = ", ".join(f"pk.{column}" for column in dict.fromkeys(select_cols)) or "pk.rowid"

    if "shop_id" in columns and _table_exists(conn, "shops"):
        shop_columns = _table_columns(conn, "shops")
        if "id" in shop_columns and "shop_id" in shop_columns:
            query = (
                f"SELECT {select_sql}, s.shop_id AS resolved_shop_id "
                "FROM product_knowledge pk JOIN shops s ON CAST(pk.shop_id AS TEXT) = CAST(s.id AS TEXT) "
                "WHERE CAST(s.shop_id AS TEXT) = ? LIMIT ?"
            )
            rows = conn.execute(query, (shop_id, limit)).fetchall()
            return [_row_to_record(row, shop_id=shop_id) for row in rows]

    if "shop_id" not in columns:
        return []
    query = f"SELECT {select_sql} FROM product_knowledge pk WHERE CAST(pk.shop_id AS TEXT) = ? LIMIT ?"
    rows = conn.execute(query, (shop_id, limit)).fetchall()
    return [_row_to_record(row, shop_id=shop_id) for row in rows]


def _row_to_record(row: sqlite3.Row, *, shop_id: str) -> dict[str, str]:
    data = {key: str(row[key] or "") for key in row.keys() if key != "raw_detail_json"}
    data["shop_id"] = shop_id
    data["source_table"] = "product_knowledge"
    return data


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _validate_real_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.real:
        return None
    if not str(args.pg_dsn or "").strip():
        return _base_payload(args, status="error", error_type="missing_pg_dsn")
    if args.embedding_provider != "ollama":
        return _base_payload(args, status="error", error_type="real_requires_ollama")
    if not str(args.ollama_base_url or "").strip():
        return _base_payload(args, status="error", error_type="missing_ollama_base_url")
    return None


def _embedding_client(args: argparse.Namespace):
    if args.embedding_provider == "ollama":
        return OllamaBgeM3EmbeddingClient(base_url=args.ollama_base_url, model=args.embedding_model)
    return FakeEmbeddingClient(dimension=int(args.embedding_dimension or 1024), model=args.embedding_model)


def _base_payload(args: argparse.Namespace, *, status: str, error_type: str = "") -> dict[str, Any]:
    return {
        "status": status,
        "error_type": error_type,
        "db_path_hash": _hash(str(args.product_db_path or "")),
        "db_path_summary": Path(args.product_db_path).name if args.product_db_path else "",
        "shop_id_hash": _hash(str(args.shop_id or "")),
        "source_record_count": 0,
        "product_chunk_count": 0,
        "embedded_count": 0,
        "indexed_count": 0,
        "product_version": str(getattr(args, "product_version", "") or "real-product-v1"),
        "product_domain": str(getattr(args, "product_domain", "") or "product_catalog"),
        "source_type": "product",
        "calls_ollama": False,
        "connects_pgvector": False,
        "vector_store": "pgvector" if getattr(args, "real", False) else "in_memory",
        "embedding_model": str(getattr(args, "embedding_model", "") or "bge-m3"),
        "index_run_id": str(getattr(args, "index_run_id", "") or ""),
        "namespace": str(getattr(args, "namespace", "") or "acceptance"),
    }


def _hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16] if value else ""


def _new_index_run_id() -> str:
    return "rag-product-run-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def write_payload(payload: dict[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
    else:
        print("internal_product_rag_index: " + rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_index(args)
    write_payload(payload, json_only=args.json_only)
    return 1 if payload.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
