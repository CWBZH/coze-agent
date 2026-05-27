"""Retrieval-only QA runner for internal RAG.

Default mode is fake and local: fake embeddings plus an in-memory vector store.
Real pgvector/Ollama retrieval is only used with explicit --real and required
connection flags.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - import order avoids logger cycle.
from Message.workflow.embedding_client import FakeEmbeddingClient, OllamaBgeM3EmbeddingClient
from Message.workflow.rag_types import RetrievalHit, RetrievalQuery
from Message.workflow.vector_store import InMemoryVectorStore, PgVectorStore, mask_pg_dsn
from scripts.acceptance.internal_rag_index import build_chunks
from scripts.acceptance.internal_rag_qa_cases import DEFAULT_SHOP_ID, DEFAULT_VERSION, load_cases


DEFAULT_SOP_FILE = REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run metadata-only internal RAG retrieval QA.")
    parser.add_argument("--real", action="store_true", help="Use explicit pgvector + Ollama.")
    parser.add_argument("--pg-dsn", default="", help="PostgreSQL/pgvector DSN for --real.")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--embedding-model", default="bge-m3")
    parser.add_argument("--shop-id", default=DEFAULT_SHOP_ID)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--sop-file", type=Path, default=DEFAULT_SOP_FILE)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--case-id", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--require-version", action="store_true", default=True)
    parser.add_argument("--run-pollution-tests", action="store_true")
    parser.add_argument("--expected-shop-id", default="")
    parser.add_argument("--expected-version", default="")
    parser.add_argument("--expected-domain", default="")
    parser.add_argument("--fail-on-cross-shop", action="store_true")
    parser.add_argument("--fail-on-cross-domain", action="store_true")
    parser.add_argument("--fail-on-wrong-version", action="store_true")
    parser.add_argument("--pollution-fixture", action="store_true")
    parser.add_argument("--pollution-kind", choices=["old_version", "wrong_shop", "wrong_domain", "all"], default="all")
    parser.add_argument("--pollution-version", default="old-version")
    parser.add_argument("--pollution-shop-id", default="synthetic-shop-2")
    parser.add_argument("--pollution-domain", default="after_sales_evidence")
    return parser.parse_args(argv)


def run_qa(args: argparse.Namespace) -> dict[str, Any]:
    setup_error = _validate_args(args)
    if setup_error:
        return setup_error
    cases = _filter_cases(args)
    try:
        embedder, store = _build_retrieval_stack(args)
    except Exception as exc:  # noqa: BLE001 - external failures become unclear.
        return _unclear_payload(args, cases, type(exc).__name__)

    results = [_run_case(args, case, embedder, store) for case in cases]
    passed = sum(1 for result in results if result["verdict"] == "pass")
    failed = sum(1 for result in results if result["verdict"] == "fail")
    unclear = sum(1 for result in results if result["verdict"] == "unclear")
    total = len(results)
    hit_pass = sum(1 for result in results if int(result["hit_count"]) >= 1)
    domain_pass = sum(1 for result in results if not result.get("domain_errors"))
    version_pass = sum(1 for result in results if not result.get("version_errors"))
    wrong_version_failures = sum(1 for result in results if result.get("wrong_version_detected"))
    cross_domain_failures = sum(1 for result in results if result.get("cross_domain_detected"))
    cross_shop_failures = sum(1 for result in results if result.get("cross_shop_detected"))
    return {
        "status": "passed" if failed == 0 and unclear == 0 else ("unclear" if unclear and not failed else "failed"),
        "total": total,
        "passed": passed,
        "failed": failed,
        "unclear": unclear,
        "retrieval_hit_rate": _rate(hit_pass, total),
        "domain_match_rate": _rate(domain_pass, total),
        "version_match_rate": _rate(version_pass, total),
        "cross_domain_failures": cross_domain_failures,
        "cross_shop_failures": cross_shop_failures,
        "wrong_version_failures": wrong_version_failures,
        "pollution_status": _pollution_status(args, cross_shop_failures, cross_domain_failures, wrong_version_failures),
        "calls_ollama": bool(getattr(args, "real", False)),
        "connects_pgvector": bool(getattr(args, "real", False)),
        "results": results,
    }


def _validate_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if not getattr(args, "real", False):
        return None
    missing = []
    if not str(getattr(args, "pg_dsn", "") or "").strip():
        missing.append("pg_dsn")
    if not str(getattr(args, "ollama_base_url", "") or "").strip():
        missing.append("ollama_base_url")
    if not str(getattr(args, "embedding_model", "") or "").strip():
        missing.append("embedding_model")
    if missing:
        return {
            "status": "error",
            "error_type": "missing_" + "_".join(missing),
            "total": 0,
            "passed": 0,
            "failed": 1,
            "unclear": 0,
            "retrieval_hit_rate": 0.0,
            "domain_match_rate": 0.0,
            "version_match_rate": 0.0,
            "cross_domain_failures": 0,
            "cross_shop_failures": 0,
            "wrong_version_failures": 0,
            "pollution_status": "not_run",
            "calls_ollama": False,
            "connects_pgvector": False,
            "dsn": mask_pg_dsn(str(getattr(args, "pg_dsn", "") or "")),
            "results": [],
        }
    return None


def _filter_cases(args: argparse.Namespace):
    cases = load_cases()
    if args.case_id:
        cases = [case for case in cases if case.case_id == args.case_id]
    if args.domain:
        cases = [case for case in cases if case.domain == args.domain]
    return cases


def _build_retrieval_stack(args: argparse.Namespace):
    if getattr(args, "real", False):
        return (
            OllamaBgeM3EmbeddingClient(base_url=args.ollama_base_url, model=args.embedding_model),
            PgVectorStore(args.pg_dsn),
        )
    embedder = FakeEmbeddingClient(model=args.embedding_model)
    store = InMemoryVectorStore()
    chunk_args = argparse.Namespace(
        shop_id=args.shop_id,
        domain=[],
        sop_file=args.sop_file,
        pollution_fixture=bool(getattr(args, "pollution_fixture", False)),
        pollution_kind=getattr(args, "pollution_kind", "all"),
        pollution_version=getattr(args, "pollution_version", "old-version"),
        pollution_shop_id=getattr(args, "pollution_shop_id", "synthetic-shop-2"),
        pollution_domain=getattr(args, "pollution_domain", "after_sales_evidence"),
    )
    for chunk in build_chunks(chunk_args):
        vector = embedder.embed(chunk.content)
        store.upsert(chunk, vector.vector, embedding_model=vector.model)
    return embedder, store


def _run_case(args: argparse.Namespace, case: Any, embedder: Any, store: Any) -> dict[str, Any]:
    shop_id = str(args.shop_id or case.shop_id)
    expected_version = str(getattr(args, "expected_version", "") or args.version or case.expected_version)
    expected_shop_id = str(getattr(args, "expected_shop_id", "") or shop_id or case.shop_id)
    expected_domain = str(getattr(args, "expected_domain", "") or case.domain)
    try:
        query_vector = embedder.embed(case.query)
        hits = store.search(
            RetrievalQuery(
                shop_id=shop_id,
                domain=case.domain,
                query=case.query,
                top_k=max(1, int(args.top_k or 3)),
                version=expected_version,
            ),
            query_vector.vector,
        )
    except Exception as exc:  # noqa: BLE001 - per-case external errors are unclear.
        return _case_result(case, expected_version, [], "unclear", [type(exc).__name__])

    errors = _evaluate_hits(
        case,
        hits,
        expected_version,
        expected_shop_id=expected_shop_id,
        expected_domain=expected_domain,
        require_version=bool(args.require_version),
        fail_on_cross_shop=bool(getattr(args, "fail_on_cross_shop", False)),
        fail_on_cross_domain=bool(getattr(args, "fail_on_cross_domain", False)),
        fail_on_wrong_version=bool(getattr(args, "fail_on_wrong_version", False)),
        check_source_type=not bool(getattr(args, "run_pollution_tests", False)),
    )
    verdict = "pass" if not errors else "fail"
    return _case_result(case, expected_version, hits, verdict, errors)


def _evaluate_hits(
    case: Any,
    hits: list[RetrievalHit],
    expected_version: str,
    *,
    expected_shop_id: str,
    expected_domain: str,
    require_version: bool,
    fail_on_cross_shop: bool = False,
    fail_on_cross_domain: bool = False,
    fail_on_wrong_version: bool = False,
    check_source_type: bool = True,
) -> list[str]:
    errors: list[str] = []
    if len(hits) < int(case.expected_min_hits):
        errors.append("hit_count_below_minimum")
        if require_version:
            errors.append("version_mismatch")
        return errors
    if hits[0].domain != expected_domain:
        errors.append("top_domain_mismatch")
    forbidden = set(case.forbidden_domains or ())
    if any(hit.domain in forbidden or hit.domain != expected_domain for hit in hits):
        errors.append("forbidden_domain_hit")
    if any(hit.shop_id != expected_shop_id for hit in hits):
        errors.append("shop_id_mismatch")
    if require_version and any(hit.version != expected_version for hit in hits):
        errors.append("version_mismatch")
    if check_source_type and any(hit.source_type != case.expected_source_type for hit in hits):
        errors.append("source_type_mismatch")
    if fail_on_cross_shop and "shop_id_mismatch" in errors and "cross_shop_detected" not in errors:
        errors.append("cross_shop_detected")
    if fail_on_cross_domain and "forbidden_domain_hit" in errors and "cross_domain_detected" not in errors:
        errors.append("cross_domain_detected")
    if fail_on_wrong_version and "version_mismatch" in errors and "wrong_version_detected" not in errors:
        errors.append("wrong_version_detected")
    return errors


def _case_result(case: Any, expected_version: str, hits: list[RetrievalHit], verdict: str, errors: list[str]) -> dict[str, Any]:
    hit_domains = _unique(hit.domain for hit in hits)
    hit_versions = _unique(hit.version for hit in hits)
    hit_shop_ids_hash = _unique(_short_hash(hit.shop_id) for hit in hits if hit.shop_id)
    cross_shop_detected = "shop_id_mismatch" in errors or "cross_shop_detected" in errors
    cross_domain_detected = "forbidden_domain_hit" in errors or "top_domain_mismatch" in errors or "cross_domain_detected" in errors
    wrong_version_detected = "version_mismatch" in errors or "wrong_version_detected" in errors
    return {
        "case_id": case.case_id,
        "domain": case.domain,
        "expected_version": expected_version,
        "hit_count": len(hits),
        "top_score": round(float(hits[0].score), 6) if hits else 0.0,
        "hit_domains": hit_domains,
        "hit_versions": hit_versions,
        "hit_source_types": _unique(hit.source_type for hit in hits),
        "hit_source_ids_hash": _unique(_short_hash(hit.source_id) for hit in hits if hit.source_id),
        "hit_shop_ids_hash": hit_shop_ids_hash,
        "hit_content_hashes": _unique(hit.content_hash for hit in hits),
        "verdict": verdict,
        "errors": list(errors),
        "domain_errors": [error for error in errors if "domain" in error],
        "version_errors": [error for error in errors if "version" in error],
        "cross_domain_detected": cross_domain_detected,
        "cross_shop_detected": cross_shop_detected,
        "wrong_version_detected": wrong_version_detected,
        "cross_domain_failure": cross_domain_detected,
        "cross_shop_failure": cross_shop_detected,
    }


def _unclear_payload(args: argparse.Namespace, cases: list[Any], error_type: str) -> dict[str, Any]:
    return {
        "status": "unclear",
        "total": len(cases),
        "passed": 0,
        "failed": 0,
        "unclear": len(cases),
        "retrieval_hit_rate": 0.0,
        "domain_match_rate": 0.0,
        "version_match_rate": 0.0,
        "cross_domain_failures": 0,
        "cross_shop_failures": 0,
        "wrong_version_failures": 0,
        "pollution_status": "not_run",
        "calls_ollama": bool(getattr(args, "real", False)),
        "connects_pgvector": bool(getattr(args, "real", False)),
        "error_type": error_type,
        "results": [
            {
                "case_id": case.case_id,
                "domain": case.domain,
                "expected_version": str(args.version or case.expected_version),
                "hit_count": 0,
                "top_score": 0.0,
                "hit_domains": [],
                "hit_versions": [],
                "verdict": "unclear",
                "errors": [error_type],
            }
            for case in cases
        ],
    }


def _pollution_status(args: argparse.Namespace, cross_shop: int, cross_domain: int, wrong_version: int) -> str:
    if not getattr(args, "run_pollution_tests", False):
        return "not_run"
    if cross_shop or cross_domain or wrong_version:
        return "failed"
    return "passed"


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _short_hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def write_payload(payload: dict[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
    else:
        print("internal_rag_retrieval_qa: " + rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_qa(args)
    write_payload(payload, json_only=args.json_only)
    return 1 if payload.get("status") in {"error", "failed"} or int(payload.get("failed") or 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
