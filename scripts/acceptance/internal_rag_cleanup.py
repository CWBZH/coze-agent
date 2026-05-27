"""Safe cleanup for controlled internal RAG acceptance chunks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - import order avoids logger cycle.
from Message.workflow.rag_types import KnowledgeChunk
from Message.workflow.vector_store import InMemoryVectorStore, PgVectorStore, mask_pg_dsn


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely clean controlled internal RAG acceptance chunks.")
    parser.add_argument("--fake", action="store_true", help="Use local fake store; default when no --pg-dsn is supplied.")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--shop-id", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--index-run-id", default="")
    parser.add_argument("--namespace", default="acceptance")
    parser.add_argument("--source-type-prefix", default="pollution_")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-delete", action="store_true")
    parser.add_argument("--audit-legacy-pollution", action="store_true")
    parser.add_argument("--legacy-cleanup", action="store_true")
    parser.add_argument("--legacy-confirm-delete", action="store_true")
    parser.add_argument("--legacy-source-type-prefix", default="pollution_")
    parser.add_argument("--legacy-shop-id", default="")
    parser.add_argument("--legacy-wrong-shop-id", default="")
    parser.add_argument("--legacy-version", default="")
    parser.add_argument("--legacy-domain", default="")
    parser.add_argument("--legacy-dry-run", action="store_true")
    parser.add_argument("--legacy-namespace-missing-ok", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def run_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    fake = bool(args.fake)
    if not fake and not args.pg_dsn:
        return _error_payload(args, "missing_pg_dsn")
    if not fake and not args.confirm_delete:
        args.dry_run = True
    try:
        store = _fake_store() if fake else PgVectorStore(args.pg_dsn)
        if getattr(args, "audit_legacy_pollution", False):
            result = store.audit_legacy_pollution(
                source_type_prefix=args.legacy_source_type_prefix,
                legacy_version=args.legacy_version or "old-version",
                legacy_shop_id=args.legacy_shop_id or "synthetic-shop-1",
                legacy_wrong_shop_id=args.legacy_wrong_shop_id or "synthetic-shop-2",
                legacy_domain=args.legacy_domain,
            )
            return {
                "status": result.status,
                "connects_pgvector": not fake,
                "legacy_candidate_count": result.legacy_candidate_count,
                "legacy_source_types": result.legacy_source_types or [],
                "legacy_versions": result.legacy_versions or [],
                "legacy_domains": result.legacy_domains or [],
                "legacy_shop_ids_hash": result.legacy_shop_ids_hash or [],
                "has_non_pollution_candidates": result.has_non_pollution_candidates,
                "error_type": result.error_type,
            }
        if getattr(args, "legacy_cleanup", False):
            dry_run = bool(args.legacy_dry_run or not args.legacy_confirm_delete)
            result = store.delete_legacy_pollution(
                source_type_prefix=args.legacy_source_type_prefix,
                version=args.legacy_version or None,
                shop_id=args.legacy_shop_id or args.legacy_wrong_shop_id or None,
                domain=args.legacy_domain or None,
                dry_run=dry_run,
            )
            return {
                "status": result.status,
                "dry_run": bool(result.dry_run),
                "legacy_cleanup": True,
                "connects_pgvector": not fake,
                "matched_count": result.matched_count,
                "deleted_count": result.deleted_count,
                "filters_summary": _filters_summary(result.filters or {}),
                "safety_status": "passed" if result.status == "ok" else "failed",
                "error_type": result.error_type,
            }
        result = store.delete_chunks(
            shop_id=args.shop_id or None,
            domain=args.domain or None,
            version=args.version or None,
            source_type_prefix=args.source_type_prefix or None,
            index_run_id=args.index_run_id or None,
            namespace=args.namespace or None,
            dry_run=bool(args.dry_run or (not args.confirm_delete)),
        )
    except Exception as exc:  # noqa: BLE001 - CLI must sanitize external failures.
        return _error_payload(args, type(exc).__name__)
    return {
        "status": result.status,
        "dry_run": bool(result.dry_run),
        "connects_pgvector": not fake,
        "matched_count": result.matched_count,
        "deleted_count": result.deleted_count,
        "filters_summary": _filters_summary(result.filters or {}),
        "error_type": result.error_type,
    }


def _fake_store() -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    store.upsert(
        KnowledgeChunk(
            chunk_id="fake-pollution",
            shop_id="synthetic-shop-1",
            domain="logistics_policy",
            source_type="pollution_old_version",
            source_id="pollution-1",
            title="pollution",
            content="controlled pollution content",
            version="old-version",
            metadata={"namespace": "acceptance", "is_test_data": True, "index_run_id": "fake-run"},
        ),
        [1, 0],
    )
    store.upsert(
        KnowledgeChunk(
            chunk_id="legacy-pollution-old-version",
            shop_id="synthetic-shop-1",
            domain="logistics_policy",
            source_type="pollution_old_version",
            source_id="legacy-pollution",
            title="legacy-pollution",
            content="legacy controlled pollution content",
            version="old-version",
            metadata={},
        ),
        [1, 0],
    )
    store.upsert(
        KnowledgeChunk(
            chunk_id="fake-sop",
            shop_id="synthetic-shop-1",
            domain="logistics_policy",
            source_type="sop",
            source_id="sop-1",
            title="sop",
            content="safe sop content",
            version="sop-test-v1",
            metadata={"namespace": "acceptance", "is_test_data": False, "index_run_id": "fake-run"},
        ),
        [1, 0],
    )
    return store


def _error_payload(args: argparse.Namespace, error_type: str) -> dict[str, Any]:
    return {
        "status": "error",
        "dry_run": True,
        "legacy_cleanup": bool(getattr(args, "legacy_cleanup", False)),
        "connects_pgvector": False,
        "matched_count": 0,
        "deleted_count": 0,
        "legacy_candidate_count": 0,
        "legacy_source_types": [],
        "legacy_versions": [],
        "legacy_domains": [],
        "legacy_shop_ids_hash": [],
        "has_non_pollution_candidates": False,
        "filters_summary": _filters_summary(vars(args)),
        "safety_status": "failed",
        "error_type": error_type,
        "dsn": mask_pg_dsn(str(getattr(args, "pg_dsn", "") or "")),
    }


def _filters_summary(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "shop_id_hash": _hash(filters.get("shop_id") or ""),
        "domain": str(filters.get("domain") or ""),
        "version": str(filters.get("version") or ""),
        "index_run_id_hash": _hash(filters.get("index_run_id") or ""),
        "namespace": str(filters.get("namespace") or ""),
        "source_type_prefix": str(filters.get("source_type_prefix") or ""),
        "is_test_data": filters.get("is_test_data"),
    }


def _hash(value: object) -> str:
    import hashlib

    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_cleanup(args)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json_only:
        print(rendered)
    else:
        print("internal_rag_cleanup: " + rendered)
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
