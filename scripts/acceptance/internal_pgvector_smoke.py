"""Explicit pgvector connectivity/schema smoke for internal RAG."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - avoids existing import cycle in tests.
from Message.workflow.vector_store import PgVectorStore, mask_pg_dsn


DEFAULT_SCHEMA = REPO_ROOT / "deploy" / "sql" / "pgvector_knowledge_chunks.sql"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run metadata-only pgvector smoke.")
    parser.add_argument("--fake", action="store_true", help="Do not connect to PostgreSQL.")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--schema-path", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def run_smoke(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.fake or not args.pg_dsn:
        return (
            {
                "status": "ok",
                "vector_store": "fake",
                "connects_pgvector": False,
                "schema_applied": False,
                "extension_available": True,
                "table_available": True,
                "columns_ok": True,
                "error_type": "",
            },
            0,
        )
    try:
        store = PgVectorStore(args.pg_dsn)
        schema_applied = False
        if args.apply_schema:
            store.apply_schema(args.schema_path)
            schema_applied = True
        check = store.check_schema()
        status = "ok" if check["extension_available"] and check["table_available"] and check["columns_ok"] else "schema_incomplete"
        return (
            {
                "status": status,
                "vector_store": "pgvector",
                "connects_pgvector": True,
                "schema_applied": schema_applied,
                "extension_available": bool(check["extension_available"]),
                "table_available": bool(check["table_available"]),
                "columns_ok": bool(check["columns_ok"]),
                "error_type": "" if status == "ok" else "schema_incomplete",
                "dsn": mask_pg_dsn(args.pg_dsn),
            },
            0 if status == "ok" else 1,
        )
    except Exception as exc:  # noqa: BLE001 - smoke output must be sanitized.
        return (
            {
                "status": "error",
                "vector_store": "pgvector",
                "connects_pgvector": True,
                "schema_applied": False,
                "extension_available": False,
                "table_available": False,
                "columns_ok": False,
                "error_type": type(exc).__name__,
                "dsn": mask_pg_dsn(args.pg_dsn),
            },
            1,
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload, code = run_smoke(args)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered if args.json_only else "internal_pgvector_smoke: " + rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
