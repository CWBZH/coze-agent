"""No-send product knowledge retrieval coverage QA."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401
from Message.workflow.chunk_builder import build_product_chunks
from Message.workflow.embedding_client import FakeEmbeddingClient, OllamaBgeM3EmbeddingClient
from Message.workflow.rag_types import RetrievalHit, RetrievalQuery
from Message.workflow.vector_store import InMemoryVectorStore, PgVectorStore
from scripts.acceptance.internal_product_coverage_cases import (
    DEFAULT_PRODUCT_DOMAIN,
    DEFAULT_PRODUCT_VERSION,
    DEFAULT_SHOP_ID,
    ProductCoverageCase,
    build_cases_from_records,
    fake_product_records,
)
from scripts.acceptance.internal_product_rag_index import _load_product_records


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run product RAG coverage QA without sending messages.")
    parser.add_argument("--product-db-path", type=Path, default=Path("temp/missing.db"))
    parser.add_argument("--from-product-db", action="store_true")
    parser.add_argument("--shop-id", default=DEFAULT_SHOP_ID)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--real-rag", action="store_true")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--ollama-base-url", default="")
    parser.add_argument("--embedding-model", default="bge-m3")
    parser.add_argument("--embedding-dimension", type=int, default=1024)
    parser.add_argument("--product-version", default=DEFAULT_PRODUCT_VERSION)
    parser.add_argument("--product-domain", default=DEFAULT_PRODUCT_DOMAIN)
    parser.add_argument("--case-id", default="")
    parser.add_argument("--expected-min-hit-rate", type=float, default=0.9)
    parser.add_argument("--expected-min-field-coverage-rate", type=float, default=0.8)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def run_qa(args: argparse.Namespace) -> dict[str, Any]:
    setup_error = _validate_args(args)
    if setup_error:
        return setup_error
    records_result = _records(args)
    if records_result["status"] != "ok":
        return _summary(
            status="unclear",
            error_type=records_result.get("error_type") or records_result["status"],
            records=[],
            results=[],
            args=args,
        )
    records = records_result["records"]
    cases = build_cases_from_records(
        records,
        shop_id=args.shop_id,
        version=args.product_version,
        domain=args.product_domain,
        limit=args.limit,
    )
    if args.case_id:
        cases = [case for case in cases if case.case_id == args.case_id]
    if not cases:
        return _summary(status="unclear", error_type="no_cases", records=records, results=[], args=args)

    try:
        embedder = _embedder(args)
        store = _store(args)
        for chunk in build_product_chunks(
            records,
            version=args.product_version,
            domain=args.product_domain,
            namespace="acceptance",
            created_by="internal_product_coverage_qa",
        ):
            vector = embedder.embed(chunk.content)
            if not args.real_rag:
                store.upsert(chunk, vector.vector, embedding_model=vector.model)
        results = [_run_case(args, case, embedder=embedder, store=store) for case in cases]
    except Exception as exc:  # noqa: BLE001 - provider/store failures are sanitized.
        return _summary(status="unclear", error_type=type(exc).__name__, records=records, results=[], args=args)

    summary = _summary(status="", error_type="", records=records, results=results, args=args)
    failed = int(summary["failed"])
    if summary["hit_rate"] < args.expected_min_hit_rate:
        failed += 1
    if summary["field_coverage_rate"] < args.expected_min_field_coverage_rate:
        failed += 1
    summary["failed"] = failed
    summary["status"] = "passed" if failed == 0 and int(summary["unclear"]) == 0 else "failed"
    return summary


def _run_case(args: argparse.Namespace, case: ProductCoverageCase, *, embedder: Any, store: Any) -> dict[str, Any]:
    vector = embedder.embed(case.query)
    hits = store.search(
        RetrievalQuery(
            shop_id=case.shop_id,
            domain=case.expected_domain,
            query=case.query,
            top_k=3,
            version=case.expected_version,
        ),
        vector.vector,
    )
    errors: list[str] = []
    if len(hits) < case.expected_min_hits:
        errors.append("hit_count")
    if hits and hits[0].domain != case.expected_domain:
        errors.append("top_domain")
    if any(hit.shop_id != case.shop_id for hit in hits):
        errors.append("cross_shop")
    if any(hit.domain != case.expected_domain for hit in hits):
        errors.append("cross_domain")
    if any(hit.version != case.expected_version for hit in hits):
        errors.append("wrong_version")
    if any(hit.source_type != case.expected_source_type for hit in hits):
        errors.append("source_type")
    field_detected = _field_detected(case.expected_field, hits)
    if not field_detected:
        errors.append("field_missing")
    return {
        "case_id": case.case_id,
        "expected_field": case.expected_field,
        "hit_count": len(hits),
        "top_score": round(float(hits[0].score), 6) if hits else 0.0,
        "hit_domains": sorted({hit.domain for hit in hits}),
        "hit_versions": sorted({hit.version for hit in hits}),
        "hit_source_types": sorted({hit.source_type for hit in hits}),
        "hit_content_hashes": [hit.content_hash for hit in hits],
        "field_detected": field_detected,
        "verdict": "pass" if not errors else "fail",
        "errors": errors,
    }


def _field_detected(field: str, hits: Sequence[RetrievalHit]) -> bool:
    for hit in hits:
        flags = dict((hit.metadata or {}).get("field_flags") or {})
        if bool(flags.get(field)):
            return True
    return False


def _records(args: argparse.Namespace) -> dict[str, Any]:
    if not args.from_product_db:
        return {"status": "ok", "records": fake_product_records(args.shop_id)}
    if not args.product_db_path.exists():
        return {"status": "missing_db", "records": []}
    return _load_product_records(args)


def _validate_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if not str(args.shop_id or "").strip():
        return _summary(status="error", error_type="missing_shop_id", records=[], results=[], args=args)
    if args.real_rag:
        missing: list[str] = []
        if not str(args.pg_dsn or "").strip():
            missing.append("pg_dsn")
        if not str(args.ollama_base_url or "").strip():
            missing.append("ollama_base_url")
        if not str(args.embedding_model or "").strip():
            missing.append("embedding_model")
        if missing:
            return _summary(status="error", error_type="missing_" + "_".join(missing), records=[], results=[], args=args)
    return None


def _embedder(args: argparse.Namespace):
    if args.real_rag:
        return OllamaBgeM3EmbeddingClient(base_url=args.ollama_base_url, model=args.embedding_model)
    return FakeEmbeddingClient(dimension=args.embedding_dimension, model=args.embedding_model)


def _store(args: argparse.Namespace):
    return PgVectorStore(args.pg_dsn) if args.real_rag else InMemoryVectorStore()


def _summary(
    *,
    status: str,
    error_type: str,
    records: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.get("verdict") == "pass")
    failed = sum(1 for result in results if result.get("verdict") == "fail")
    unclear = sum(1 for result in results if result.get("verdict") == "unclear")
    hit_cases = sum(1 for result in results if int(result.get("hit_count") or 0) > 0)
    domain_matches = sum(1 for result in results if result.get("hit_domains") == [args.product_domain])
    version_matches = sum(1 for result in results if result.get("hit_versions") == [args.product_version])
    source_matches = sum(1 for result in results if result.get("hit_source_types") == ["product"])
    field_matches = sum(1 for result in results if result.get("field_detected") is True)
    cross_shop = sum(1 for result in results if "cross_shop" in (result.get("errors") or []))
    cross_domain = sum(1 for result in results if "cross_domain" in (result.get("errors") or []))
    wrong_version = sum(1 for result in results if "wrong_version" in (result.get("errors") or []))
    final_status = status or ("passed" if failed == 0 and unclear == 0 else "failed")
    return {
        "status": final_status,
        "error_type": error_type,
        "total": total,
        "passed": passed,
        "failed": failed,
        "unclear": unclear,
        "hit_rate": _rate(hit_cases, total),
        "domain_match_rate": _rate(domain_matches, total),
        "version_match_rate": _rate(version_matches, total),
        "source_type_match_rate": _rate(source_matches, total),
        "field_coverage_rate": _rate(field_matches, total),
        "cross_shop_failures": cross_shop,
        "cross_domain_failures": cross_domain,
        "wrong_version_failures": wrong_version,
        "source_record_count": len(records),
        "product_version": args.product_version,
        "product_domain": args.product_domain,
        "calls_ollama": bool(args.real_rag) and final_status not in {"error"},
        "connects_pgvector": bool(args.real_rag) and final_status not in {"error"},
        "calls_llm": False,
        "no_send": True,
        "results": list(results),
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def write_payload(payload: dict[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
    else:
        print("internal_product_coverage_qa: " + rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_qa(args)
    write_payload(payload, json_only=args.json_only)
    return 1 if payload.get("status") in {"error", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
