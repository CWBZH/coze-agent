"""Production-vs-oracle routing diagnosis for curated replay benchmarks.

This runner is read-only and no-send. It compares the current production
routing path with a diagnostic oracle path that uses benchmark expected_domain
as a replay-only hint. It never emits raw messages, replies, prompts, chunks,
vectors, DSNs, keys, or private locator values.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401
from Message.workflow.conversation_context import stable_hash
from scripts.acceptance import internal_conversation_replay


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare production and oracle routing for benchmark replay.")
    parser.add_argument("--conversation-db-path", type=Path)
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument("--real-rag", action="store_true")
    parser.add_argument("--real-llm", action="store_true")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--ollama-base-url", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--llm-api-key-env", default="AI_WORKFLOW_LLM_API_KEY")
    parser.add_argument("--llm-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--product-version", default="real-product-v1")
    parser.add_argument("--sop-version", default="sop-test-v1")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--routing-diagnosis-output", type=Path)
    parser.add_argument("--routing-diagnosis-csv", type=Path)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def run_diagnosis(args: argparse.Namespace) -> dict[str, Any]:
    production_args = _replay_args(args, oracle=False)
    oracle_args = _replay_args(args, oracle=True)
    production = internal_conversation_replay.run_replay(production_args)
    oracle = internal_conversation_replay.run_replay(oracle_args)
    if production.get("status") == "error" or oracle.get("status") == "error":
        return _error_payload(production, oracle)
    results = _compare_results(production, oracle)
    summary = _summary(results, production, oracle)
    payload = {
        **summary,
        "results": results,
        "no_send": True,
        "calls_fastgpt": False,
        "sends_pdd": False,
        "calls_llm": bool(production.get("calls_llm") or oracle.get("calls_llm")),
        "calls_ollama": bool(production.get("calls_ollama") or oracle.get("calls_ollama")),
        "connects_pgvector": bool(production.get("connects_pgvector") or oracle.get("connects_pgvector")),
    }
    _write_outputs(payload, args)
    return payload


def _replay_args(args: argparse.Namespace, *, oracle: bool) -> argparse.Namespace:
    replay_args = internal_conversation_replay.parse_args([])
    replay_args.conversation_db_path = args.conversation_db_path
    replay_args.benchmark_file = args.benchmark_file
    replay_args.real_rag = bool(args.real_rag)
    replay_args.real_llm = bool(args.real_llm)
    replay_args.pg_dsn = str(args.pg_dsn or "")
    replay_args.ollama_base_url = str(args.ollama_base_url or "")
    replay_args.embedding_model = str(args.embedding_model or "")
    replay_args.llm_base_url = str(args.llm_base_url or "")
    replay_args.llm_model = str(args.llm_model or "")
    replay_args.llm_api_key_env = str(args.llm_api_key_env or "AI_WORKFLOW_LLM_API_KEY")
    replay_args.llm_timeout_seconds = float(args.llm_timeout_seconds or 20.0)
    replay_args.product_version = str(args.product_version or "")
    replay_args.sop_version = str(args.sop_version or "")
    replay_args.top_k = int(args.top_k or 3)
    replay_args.benchmark_max_cases = int(args.max_cases or 0)
    replay_args.benchmark_case_id = list(args.case_id or [])
    replay_args.benchmark_domain = list(args.domain or [])
    replay_args.oracle_routing = oracle
    replay_args.json_only = True
    return replay_args


def _compare_results(production: Mapping[str, Any], oracle: Mapping[str, Any]) -> list[dict[str, Any]]:
    prod_rows = _rows_by_case(production.get("results") or [])
    oracle_rows = _rows_by_case(oracle.get("results") or [])
    case_ids = sorted(set(prod_rows) | set(oracle_rows))
    results: list[dict[str, Any]] = []
    for case_id in case_ids:
        prod = prod_rows.get(case_id, {})
        ora = oracle_rows.get(case_id, {})
        diagnosis, reason = _diagnose_case(prod, ora)
        expected_domain = str(ora.get("expected_domain") or prod.get("expected_domain") or prod.get("answerable_domain") or "")
        results.append(
            {
                "case_id": case_id,
                "expected_domain": expected_domain,
                "expected_action_family": str(ora.get("expected_action_family") or prod.get("expected_action_family") or ""),
                "production_action": str(prod.get("action") or ""),
                "production_intent": str(prod.get("intent") or ""),
                "production_reason": str(prod.get("reason") or ""),
                "production_rag_status": str(prod.get("rag_status") or ""),
                "production_rag_domains": list(prod.get("rag_domains") or []),
                "production_answer_status": str(prod.get("answer_generation_status") or ""),
                "production_guardrail_status": str(prod.get("guardrail_status") or ""),
                "production_verdict": str(prod.get("verdict") or ""),
                "oracle_action": str(ora.get("action") or ""),
                "oracle_intent": str(ora.get("intent") or ""),
                "oracle_reason": str(ora.get("reason") or ""),
                "oracle_rag_status": str(ora.get("rag_status") or ""),
                "oracle_rag_domains": list(ora.get("rag_domains") or []),
                "oracle_answer_status": str(ora.get("answer_generation_status") or ""),
                "oracle_guardrail_status": str(ora.get("guardrail_status") or ""),
                "oracle_verdict": str(ora.get("verdict") or ""),
                "diagnosis": diagnosis,
                "diagnosis_reason": reason,
                "rag_status_delta": _delta(prod.get("rag_status"), ora.get("rag_status")),
                "answer_status_delta": _delta(prod.get("answer_generation_status"), ora.get("answer_generation_status")),
                "review_decision": "",
                "review_notes": "",
            }
        )
    return results


def _rows_by_case(rows: list[Any]) -> dict[str, Mapping[str, Any]]:
    mapped: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        case_id = str(row.get("case_id") or row.get("message_hash") or f"case-{index}")
        mapped[case_id] = row
    return mapped


def _diagnose_case(prod: Mapping[str, Any], ora: Mapping[str, Any]) -> tuple[str, str]:
    prod_verdict = str(prod.get("verdict") or "")
    oracle_verdict = str(ora.get("verdict") or "")
    prod_errors = {_normalize_reason(error) for error in (prod.get("answerable_errors") or prod.get("errors") or [])}
    oracle_errors = {_normalize_reason(error) for error in (ora.get("answerable_errors") or ora.get("errors") or [])}
    expected_domain = str(ora.get("expected_domain") or prod.get("expected_domain") or prod.get("answerable_domain") or "")
    if prod_verdict != "passed" and oracle_verdict == "passed":
        return "routing_failure", "oracle_passed_after_production_failed"
    if expected_domain in {"product_basic", "product_catalog"} and int(ora.get("message_length") or prod.get("message_length") or 0) <= 6:
        return "context_missing_candidate", "short_product_context_candidate"
    if str(ora.get("rag_status") or "") == "empty" or oracle_errors & {"rag_empty", "answerable_rag_miss", "version_mismatch", "source_type_mismatch"}:
        return "knowledge_issue", "oracle_rag_or_version_source_issue"
    if oracle_errors & {"answer_not_generated", "llm_error", "empty_answer"} or str(ora.get("answer_generation_status") or "") in {"error", "empty"}:
        return "generation_issue", "oracle_generation_issue"
    if expected_domain == "after_sales_evidence" and oracle_errors:
        return "verdict_issue_candidate", "after_sales_oracle_action_needs_review"
    if prod_verdict == "passed" and oracle_verdict != "passed":
        return "oracle_regression", "oracle_regressed_from_production"
    if prod_verdict == "passed" and oracle_verdict == "passed":
        return "both_passed", "production_and_oracle_passed"
    if prod_errors or oracle_errors:
        return "label_issue_candidate", "both_paths_need_label_or_policy_review"
    return "unknown", "insufficient_signal"


def _summary(results: list[dict[str, Any]], production: Mapping[str, Any], oracle: Mapping[str, Any]) -> dict[str, Any]:
    total = len(results)
    production_passed = sum(1 for row in results if row.get("production_verdict") == "passed")
    oracle_passed = sum(1 for row in results if row.get("oracle_verdict") == "passed")
    diagnoses = _counts(row.get("diagnosis") for row in results)
    by_domain: dict[str, dict[str, Any]] = {}
    for row in results:
        domain = str(row.get("expected_domain") or "")
        if not domain:
            continue
        bucket = by_domain.setdefault(
            domain,
            {
                "total": 0,
                "production_passed": 0,
                "oracle_passed": 0,
                "diagnosis_counts": {},
            },
        )
        bucket["total"] += 1
        if row.get("production_verdict") == "passed":
            bucket["production_passed"] += 1
        if row.get("oracle_verdict") == "passed":
            bucket["oracle_passed"] += 1
        diag_counts = bucket["diagnosis_counts"]
        diag_counts[row["diagnosis"]] = diag_counts.get(row["diagnosis"], 0) + 1
    return {
        "status": "passed",
        "total": total,
        "production_passed": production_passed,
        "production_failed": sum(1 for row in results if row.get("production_verdict") == "failed"),
        "production_unclear": sum(1 for row in results if row.get("production_verdict") == "unclear"),
        "production_pass_rate": _rate(production_passed, total),
        "oracle_passed": oracle_passed,
        "oracle_failed": sum(1 for row in results if row.get("oracle_verdict") == "failed"),
        "oracle_unclear": sum(1 for row in results if row.get("oracle_verdict") == "unclear"),
        "oracle_pass_rate": _rate(oracle_passed, total),
        "oracle_improved_count": sum(1 for row in results if row.get("production_verdict") != "passed" and row.get("oracle_verdict") == "passed"),
        "oracle_regressed_count": sum(1 for row in results if row.get("production_verdict") == "passed" and row.get("oracle_verdict") != "passed"),
        "routing_failure_count": diagnoses.get("routing_failure", 0),
        "knowledge_issue_count": diagnoses.get("knowledge_issue", 0),
        "context_missing_candidate_count": diagnoses.get("context_missing_candidate", 0),
        "label_issue_candidate_count": diagnoses.get("label_issue_candidate", 0),
        "verdict_issue_candidate_count": diagnoses.get("verdict_issue_candidate", 0),
        "generation_issue_count": diagnoses.get("generation_issue", 0),
        "no_rag_domain_count": _reason_count(production, "no_rag_domain"),
        "rag_empty_count": _reason_count(production, "rag_empty") + _reason_count(oracle, "rag_empty"),
        "answerable_not_reply_count": _reason_count(production, "answerable_not_reply"),
        "after_sales_unexpected_action_count": _reason_count(production, "after_sales_unexpected_action"),
        "diagnosis_counts": diagnoses,
        "by_domain": by_domain,
    }


def _write_outputs(payload: dict[str, Any], args: argparse.Namespace) -> None:
    json_path = args.routing_diagnosis_output
    if json_path:
        _ensure_private_path(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        payload["diagnosis_output_hash"] = stable_hash(str(json_path))
    else:
        payload["diagnosis_output_hash"] = ""
    csv_path = args.routing_diagnosis_csv
    if csv_path:
        _ensure_private_path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "case_id",
            "expected_domain",
            "expected_action_family",
            "production_action",
            "production_intent",
            "production_reason",
            "production_verdict",
            "oracle_action",
            "oracle_intent",
            "oracle_reason",
            "oracle_verdict",
            "diagnosis",
            "diagnosis_reason",
            "rag_status_delta",
            "answer_status_delta",
            "review_decision",
            "review_notes",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in payload.get("results", []):
                writer.writerow({field: row.get(field, "") for field in fields})
        payload["diagnosis_csv_hash"] = stable_hash(str(csv_path))
    else:
        payload["diagnosis_csv_hash"] = ""


def _ensure_private_path(path: Path) -> None:
    resolved = path.resolve()
    allowed = (REPO_ROOT / "temp" / "manual_labeling").resolve()
    if allowed not in (resolved, *resolved.parents):
        raise ValueError("routing diagnosis output must stay under temp/manual_labeling")


def _error_payload(production: Mapping[str, Any], oracle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "error",
        "total": 0,
        "production_pass_rate": 0.0,
        "oracle_pass_rate": 0.0,
        "error_type": str(production.get("error_type") or oracle.get("error_type") or "replay_error"),
        "results": [],
        "no_send": True,
        "calls_fastgpt": False,
        "sends_pdd": False,
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
    }


def _delta(left: object, right: object) -> str:
    left_text = str(left or "")
    right_text = str(right or "")
    return "same" if left_text == right_text else f"{left_text or 'empty'}->{right_text or 'empty'}"


def _reason_count(payload: Mapping[str, Any], reason: str) -> int:
    counts = payload.get("failure_reason_counts") or {}
    miss_counts = payload.get("rag_miss_reason_counts") or {}
    return int(counts.get(reason, 0) or 0) + int(miss_counts.get(reason, 0) or 0)


def _normalize_reason(error: object) -> str:
    text = str(error or "")
    return {
        "answerable_rag_miss": "rag_empty",
        "rag_miss": "rag_empty",
        "answer_not_generated": "empty_answer",
        "answerable_fallback": "no_rag_domain",
    }.get(text, text)


def _counts(values: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "")
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def write_json(payload: Mapping[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if not json_only:
        print("internal_benchmark_routing_diagnosis: no-send summary")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = run_diagnosis(args)
    except ValueError as exc:
        payload = _error_payload({"error_type": type(exc).__name__}, {})
        payload["error_type"] = str(exc)
    write_json(payload, json_only=bool(args.json_only))
    return 1 if payload.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
