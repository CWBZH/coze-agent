"""No-send answer quality QA for real/fake RAG + answer generation."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - import order avoids logger cycle.
from scripts.acceptance import internal_backend_dry_run
from scripts.acceptance.internal_answer_quality_cases import (
    DEFAULT_SHOP_ID,
    DEFAULT_VERSION,
    AnswerQualityCase,
    load_cases,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run metadata-only internal answer quality QA.")
    parser.add_argument("--real-rag", action="store_true")
    parser.add_argument("--real-llm", action="store_true")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--ollama-base-url", default="")
    parser.add_argument("--embedding-model", default="bge-m3")
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--llm-api-key-env", default="AI_WORKFLOW_LLM_API_KEY")
    parser.add_argument("--shop-id", default=DEFAULT_SHOP_ID)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--product-version", default="")
    parser.add_argument("--product-domain", default="product_catalog")
    parser.add_argument("--domain", default="")
    parser.add_argument("--case-id", default="")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--allow-preview", action="store_true", default=True)
    return parser.parse_args(argv)


def run_qa(args: argparse.Namespace) -> dict[str, Any]:
    setup_error = _validate_args(args)
    cases = _filter_cases(args)
    if setup_error:
        return {**setup_error, "total": len(cases), "results": []}

    results = [_run_case(args, case) for case in cases]
    total = len(results)
    passed = sum(1 for result in results if result["verdict"] == "pass")
    failed = sum(1 for result in results if result["verdict"] == "fail")
    unclear = sum(1 for result in results if result["verdict"] == "unclear")
    p0_failures = sum(1 for result in results if result["priority"] == "P0" and result["verdict"] == "fail")
    forbidden_failures = sum(1 for result in results if "forbidden_phrase_detected" in result["errors"])
    negated_forbidden = sum(int(result.get("negated_forbidden_phrase_count") or 0) for result in results)
    guardrail_blocked = sum(1 for result in results if result["guardrail_status"] == "blocked")
    expected_blocked = sum(1 for result in results if result["expected_guardrail_status"] == "blocked")
    action_matches = sum(1 for result in results if result["action_match"])
    domain_matches = sum(1 for result in results if result["domain_match"])
    version_matches = sum(1 for result in results if result["version_match"])
    source_type_matches = sum(1 for result in results if result["source_type_match"])
    product_results = [result for result in results if result["category"] == "product_catalog"]
    product_source_type_matches = sum(1 for result in product_results if result["source_type_match"])
    return {
        "status": "passed" if failed == 0 and unclear == 0 else ("unclear" if unclear and not failed else "failed"),
        "total": total,
        "passed": passed,
        "failed": failed,
        "unclear": unclear,
        "pass_rate": _rate(passed, total),
        "p0_failures": p0_failures,
        "guardrail_blocked_count": guardrail_blocked,
        "guardrail_expected_blocked_count": expected_blocked,
        "forbidden_phrase_failures": forbidden_failures,
        "negated_forbidden_phrase_count": negated_forbidden,
        "action_match_rate": _rate(action_matches, total),
        "domain_match_rate": _rate(domain_matches, total),
        "version_match_rate": _rate(version_matches, total),
        "source_type_match_rate": _rate(source_type_matches, total),
        "product_case_count": len(product_results),
        "product_version": str(getattr(args, "product_version", "") or "product-test-v1"),
        "sop_version": str(getattr(args, "version", "") or DEFAULT_VERSION),
        "product_source_type_match_rate": _rate(product_source_type_matches, len(product_results)),
        "calls_ollama": bool(args.real_rag),
        "connects_pgvector": bool(args.real_rag),
        "calls_llm": bool(args.real_llm),
        "no_send": True,
        "results": results,
    }


def _validate_args(args: argparse.Namespace) -> dict[str, Any] | None:
    missing: list[str] = []
    if args.real_rag:
        if not str(args.pg_dsn or "").strip():
            missing.append("pg_dsn")
        if not str(args.ollama_base_url or "").strip():
            missing.append("ollama_base_url")
        if not str(args.embedding_model or "").strip():
            missing.append("embedding_model")
    if args.real_llm:
        if not str(args.llm_base_url or "").strip():
            missing.append("llm_base_url")
        if not str(args.llm_model or "").strip():
            missing.append("llm_model")
        if not str(args.llm_api_key_env or "").strip():
            missing.append("llm_api_key_env")
    if not missing:
        return None
    return {
        "status": "error",
        "error_type": "missing_" + "_".join(missing),
        "passed": 0,
        "failed": 1,
        "unclear": 0,
        "pass_rate": 0.0,
        "p0_failures": 0,
        "guardrail_blocked_count": 0,
        "guardrail_expected_blocked_count": 0,
        "forbidden_phrase_failures": 0,
        "negated_forbidden_phrase_count": 0,
        "action_match_rate": 0.0,
        "domain_match_rate": 0.0,
        "version_match_rate": 0.0,
        "source_type_match_rate": 0.0,
        "product_case_count": 0,
        "product_version": str(getattr(args, "product_version", "") or "product-test-v1"),
        "sop_version": str(getattr(args, "version", "") or DEFAULT_VERSION),
        "product_source_type_match_rate": 0.0,
        "calls_ollama": False,
        "connects_pgvector": False,
        "calls_llm": False,
        "no_send": True,
    }


def _filter_cases(args: argparse.Namespace) -> list[AnswerQualityCase]:
    cases = load_cases()
    if args.case_id:
        cases = [case for case in cases if case.case_id == args.case_id]
    if args.domain:
        cases = [case for case in cases if case.domain == args.domain]
    if args.max_cases and args.max_cases > 0:
        cases = cases[: int(args.max_cases)]
    return cases


def _run_case(args: argparse.Namespace, case: AnswerQualityCase) -> dict[str, Any]:
    dry_args = _dry_run_args(args, case)
    try:
        result = asyncio.run(internal_backend_dry_run.run_engine(dry_args))
        summary = internal_backend_dry_run.result_summary(dry_args, result)
    except Exception as exc:  # noqa: BLE001 - external provider failures are unclear per case.
        return _result(case, {}, "unclear", [type(exc).__name__])

    expected_version = _expected_version(args, case)
    expected_domain = _expected_domain(args, case)
    forbidden_check = _forbidden_check(str(result.reply_text or ""), case.forbidden_phrases)
    errors = _evaluate(
        case,
        summary,
        str(result.reply_text or ""),
        expected_domain=expected_domain,
        expected_version=expected_version,
        forbidden_check=forbidden_check,
    )
    verdict = "pass" if not errors else "fail"
    if "empty_answer" in errors or "provider_error" in errors:
        verdict = "unclear"
    return _result(
        case,
        summary,
        verdict,
        errors,
        expected_domain=expected_domain,
        expected_version=expected_version,
        negated_forbidden_phrase_count=forbidden_check["negated_count"],
    )


def _dry_run_args(args: argparse.Namespace, case: AnswerQualityCase) -> argparse.Namespace:
    use_fake_rag = not bool(args.real_rag) and not case.should_transfer_human
    use_real_rag = bool(args.real_rag) and not case.should_transfer_human
    expected_version = _expected_version(args, case)
    return argparse.Namespace(
        shop_id=str(args.shop_id or case.shop_id),
        user_id="",
        buyer_id="synthetic-buyer",
        session_id="synthetic-session",
        message=case.message,
        message_type="text",
        db_path=None,
        use_db=False,
        fake_product=case.domain == "product_catalog",
        sop_file=None,
        history_message=[],
        with_fake_history=False,
        pending_human=False,
        use_conversation_db=False,
        conversation_db_path=None,
        conversation_session_id="",
        conversation_buyer_id="",
        json_only=True,
        dry_run=False,
        use_fake_answer_generator=not bool(args.real_llm) and not case.should_transfer_human,
        fake_answer_style="conservative",
        fake_answer_dangerous=False,
        use_real_answer_generator=bool(args.real_llm) and not case.should_transfer_human,
        llm_base_url=str(args.llm_base_url or ""),
        llm_model=str(args.llm_model or ""),
        llm_api_key_env=str(args.llm_api_key_env or "AI_WORKFLOW_LLM_API_KEY"),
        llm_timeout_seconds=20.0,
        answer_preview_max_chars=120,
        require_answer_generated=not case.should_transfer_human,
        rag_enabled=use_fake_rag or use_real_rag,
        use_fake_rag=use_fake_rag,
        use_real_rag=use_real_rag,
        pg_dsn=str(args.pg_dsn or ""),
        ollama_base_url=str(args.ollama_base_url or ""),
        embedding_model=str(args.embedding_model or "bge-m3"),
        rag_domain=(str(getattr(args, "product_domain", "") or "") if case.domain == "product_catalog" else "")
        or case.expected_rag_domain
        or case.domain,
        rag_version=expected_version,
        rag_top_k=max(1, int(args.top_k or 3)),
        rag_hit_title=f"{case.domain} synthetic policy",
        rag_hit_content=_fake_rag_content(case),
        rag_hit_source_type=case.expected_source_type or "sop",
        rag_e2e_profile=False,
        require_rag_hit=False,
        expect_rag_domain="",
        expect_rag_version="",
        require_rag_version=False,
        expect_shop_id="",
        expect_rag_source_type=case.expected_source_type or "",
        expect_rag_content_hash="",
        expect_answer_generator="",
        expect_guardrail_status="",
    )


def _evaluate(
    case: AnswerQualityCase,
    summary: dict[str, Any],
    answer_text: str,
    *,
    expected_domain: str | None = None,
    expected_version: str | None = None,
    forbidden_check: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    action = str(summary.get("action") or "")
    intent = str(summary.get("intent") or "")
    guardrail = str(summary.get("guardrail_status") or "safe")
    rag_domains = [str(item) for item in summary.get("rag_domains") or []]
    versions = [str(item) for item in summary.get("rag_hit_versions") or []]
    source_types = [str(item) for item in summary.get("rag_hit_source_types") or []]
    answer_length = int(summary.get("answer_length") or 0)
    expected_domain = case.expected_rag_domain if expected_domain is None else expected_domain
    expected_version = case.expected_version if expected_version is None else expected_version

    allowed_actions = set(case.allowed_actions or (case.expected_action,))
    if action not in allowed_actions:
        errors.append("action_mismatch")
    if case.expected_intent and intent != case.expected_intent:
        errors.append("intent_mismatch")
    if expected_domain:
        if expected_domain not in rag_domains:
            errors.append("rag_domain_mismatch")
        if versions and any(version != expected_version for version in versions):
            errors.append("version_mismatch")
        if not versions:
            errors.append("version_mismatch")
        if source_types and any(value != case.expected_source_type for value in source_types):
            errors.append("source_type_mismatch")
        if not source_types:
            errors.append("source_type_mismatch")
    if case.allowed_guardrail_statuses and guardrail not in set(case.allowed_guardrail_statuses):
        errors.append("guardrail_mismatch")
    if case.should_transfer_human and action != "transfer_human":
        errors.append("p0_redline_not_transferred")
    if case.should_request_evidence and action != "request_evidence":
        errors.append("evidence_not_requested")
    if not case.should_transfer_human and action != "transfer_human" and answer_length <= 0:
        errors.append("empty_answer")
    forbidden_check = forbidden_check or _forbidden_check(answer_text, case.forbidden_phrases)
    if forbidden_check["violations"]:
        errors.append("forbidden_phrase_detected")
    if str(summary.get("answer_generation_status") or "").startswith("failed"):
        errors.append("provider_error")
    return errors


def _result(
    case: AnswerQualityCase,
    summary: dict[str, Any],
    verdict: str,
    errors: list[str],
    *,
    expected_domain: str | None = None,
    expected_version: str | None = None,
    negated_forbidden_phrase_count: int = 0,
) -> dict[str, Any]:
    actual_action = str(summary.get("action") or "")
    actual_domains = [str(item) for item in summary.get("rag_domains") or []]
    actual_versions = [str(item) for item in summary.get("rag_hit_versions") or []]
    actual_source_types = [str(item) for item in summary.get("rag_hit_source_types") or []]
    expected_domain = expected_domain if expected_domain is not None else case.expected_rag_domain
    action_match = actual_action in set(case.allowed_actions or (case.expected_action,))
    domain_match = not expected_domain or expected_domain in actual_domains
    version_match = (not expected_domain and not actual_versions) or (
        bool(actual_versions) and all(version == (expected_version or case.expected_version) for version in actual_versions)
    )
    source_type_match = (not expected_domain and not actual_source_types) or (
        bool(actual_source_types) and all(value == case.expected_source_type for value in actual_source_types)
    )
    return {
        "case_id": case.case_id,
        "category": case.category,
        "priority": case.priority,
        "expected_action": case.expected_action,
        "actual_action": actual_action,
        "expected_domain": expected_domain,
        "actual_rag_domains": actual_domains,
        "expected_version": expected_version or case.expected_version,
        "actual_versions": actual_versions,
        "expected_source_type": case.expected_source_type,
        "actual_source_types": actual_source_types,
        "source_type_status": "passed" if source_type_match else "failed",
        "guardrail_status": str(summary.get("guardrail_status") or ""),
        "expected_guardrail_status": case.expected_guardrail_status,
        "answer_length": int(summary.get("answer_length") or 0),
        "answer_hash": str(summary.get("answer_hash") or ""),
        "answer_preview_truncated": str(summary.get("answer_preview_truncated") or "")[:120],
        "action_match": action_match,
        "domain_match": domain_match,
        "version_match": version_match,
        "source_type_match": source_type_match,
        "negated_forbidden_phrase_count": negated_forbidden_phrase_count,
        "verdict": verdict,
        "errors": list(errors),
    }


def _fake_rag_content(case: AnswerQualityCase) -> str:
    if case.domain == "logistics_policy":
        return "Logistics policy: ask buyer to check order logistics page; do not promise arrival time."
    if case.domain == "after_sales_evidence":
        return "After-sales policy: request photos, packaging and order details; human review is required."
    if case.domain == "promotion_policy":
        return "Promotion policy: discounts and gifts follow product page and checkout page."
    if case.domain == "sensitive_user_safety":
        return "Safety policy: check ingredient label and instructions; ask professional advice when needed."
    if case.domain == "product_catalog":
        return "Product knowledge: usage, ingredients, shelf life and price are subject to product page."
    return "Policy summary requires human support."


def _expected_version(args: argparse.Namespace, case: AnswerQualityCase) -> str:
    if case.domain == "product_catalog":
        return str(getattr(args, "product_version", "") or case.expected_version)
    return case.expected_version or str(args.version or DEFAULT_VERSION)


def _expected_domain(args: argparse.Namespace, case: AnswerQualityCase) -> str:
    if case.domain == "product_catalog":
        return str(getattr(args, "product_domain", "") or case.expected_rag_domain)
    return case.expected_rag_domain


NEGATION_MARKERS = (
    "不",
    "不会",
    "不能",
    "不支持",
    "不提供",
    "不承诺",
    "无法",
    "暂不",
    "以页面为准",
    "以结算页为准",
    "not",
    "cannot",
    "can't",
    "don't",
    "doesn't",
    "do not",
    "does not",
    "no ",
    "为准",
    "页面",
    "活动",
    "结算",
    "规则",
    "显示",
)


def _forbidden_check(text: str, forbidden: Sequence[str]) -> dict[str, Any]:
    lowered = str(text or "").lower()
    violations: list[str] = []
    negated: list[str] = []
    for phrase in forbidden:
        needle = str(phrase or "").strip().lower()
        if not needle:
            continue
        start = lowered.find(needle)
        while start >= 0:
            window = lowered[max(0, start - 32) : min(len(lowered), start + len(needle) + 32)]
            if any(marker in window for marker in NEGATION_MARKERS):
                negated.append(_phrase_hash(needle))
            else:
                violations.append(_phrase_hash(needle))
            start = lowered.find(needle, start + len(needle))
    return {"violations": violations, "negated": negated, "negated_count": len(negated)}


def _has_forbidden(text: str, forbidden: Sequence[str]) -> bool:
    return bool(_forbidden_check(text, forbidden)["violations"])


def _phrase_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _rate(numerator: int, denominator: int) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def write_payload(payload: dict[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
    else:
        print("internal_answer_quality_qa: " + rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_qa(args)
    write_payload(payload, json_only=args.json_only)
    return 1 if payload.get("status") in {"error", "failed"} or int(payload.get("failed") or 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
