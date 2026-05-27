"""Unified no-send acceptance artifact writer for the internal engine."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "temp" / "acceptance" / "internal-engine"
ARTIFACT_NAMES = (
    "manifest.json",
    "synthetic_report.json",
    "dry_run_report.json",
    "comparison_report.json",
    "summary.json",
)
NO_SEND_FLAGS = {
    "no_send": True,
    "calls_fastgpt": False,
    "calls_llm": False,
    "sends_pdd": False,
}

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.acceptance import compare_internal_fastgpt
from scripts.acceptance import conversation_context_schema_probe
from scripts.acceptance import internal_backend_dry_run
from scripts.acceptance import internal_answer_quality_qa
from scripts.acceptance import internal_conversation_replay
from scripts.acceptance import internal_manual_labeling_pack
from scripts.acceptance import internal_replay_benchmark
from scripts.acceptance import internal_engine_synthetic_qa
from scripts.acceptance import internal_product_coverage_qa
from scripts.acceptance import internal_rag_index
from scripts.acceptance import internal_rag_cleanup
from scripts.acceptance import internal_rag_retrieval_qa
from scripts.acceptance import internal_pgvector_smoke
from scripts.acceptance import internal_rag_embedding_smoke
from scripts.acceptance import internal_rag_retrieve
from scripts.acceptance.internal_report_schema import (
    SCHEMA_VERSION,
    scan_json_payload_for_forbidden_fields,
    validate_report_schema,
)


DRY_RUN_EXAMPLE_MESSAGE = "\u6536\u5230\u7834\u635f\u4e86"
DRY_RUN_EXAMPLE_SHOP_ID = "synthetic-shop-1"


def default_output_dir(now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_ROOT / f"run-{stamp}"


def build_path_plan(output_dir: Path | None = None) -> dict[str, Any]:
    target_dir = (output_dir or default_output_dir()).resolve()
    return {
        "output_dir": str(target_dir),
        "files": {name: str(target_dir / name) for name in ARTIFACT_NAMES},
    }


def build_artifacts(
    *,
    output_dir: Path | None = None,
    command: Sequence[str] | None = None,
    no_write: bool = False,
    synthetic_limit: int | None = None,
    sop_file: Path | str | None = None,
    conversation_db_path: Path | str | None = None,
    use_fake_answer_generator: bool = False,
    rag_smoke: bool = True,
    rag_smoke_real: bool = False,
    rag_engine_real: bool = False,
    rag_e2e_profile: bool = False,
    require_rag_hit: bool = False,
    expect_rag_domain: str = "",
    expect_rag_version: str = "",
    require_rag_version: bool = False,
    expect_rag_source_type: str = "",
    expect_answer_generator: str = "",
    expect_guardrail_status: str = "",
    fake_answer_dangerous: bool = False,
    rag_engine_domain: str = "logistics_policy",
    rag_version: str = "",
    rag_engine_query: str = "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
    pg_dsn: str = "",
    ollama_base_url: str = "",
    embedding_model: str = "",
    rag_retrieval_qa: bool = False,
    rag_retrieval_qa_real: bool = False,
    rag_qa_version: str = "sop-test-v1",
    rag_qa_domain: str = "",
    rag_qa_case_id: str = "",
    rag_release_gate: bool = False,
    rag_release_real: bool = False,
    rag_release_version: str = "sop-test-v1",
    rag_release_shop_id: str = DRY_RUN_EXAMPLE_SHOP_ID,
    rag_release_min_hit_rate: float = 0.9,
    rag_release_min_domain_match_rate: float = 0.9,
    rag_release_require_version_match: bool = False,
    rag_release_require_no_cross_shop: bool = False,
    rag_release_require_no_cross_domain: bool = False,
    rag_release_run_pollution_tests: bool = False,
    cleanup_rag_pollution_before: bool = False,
    cleanup_rag_pollution_after: bool = False,
    rag_cleanup_dry_run: bool = True,
    rag_cleanup_source_type_prefix: str = "pollution_",
    rag_cleanup_namespace: str = "acceptance",
    audit_rag_legacy_pollution: bool = False,
    require_no_rag_legacy_pollution: bool = False,
    cleanup_rag_legacy_pollution_before: bool = False,
    cleanup_rag_legacy_pollution_after: bool = False,
    legacy_cleanup_confirm_delete: bool = False,
    legacy_cleanup_version: str = "",
    legacy_cleanup_shop_id: str = "",
    legacy_cleanup_domain: str = "",
    llm_answer_real: bool = False,
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key_env: str = "AI_WORKFLOW_LLM_API_KEY",
    llm_timeout_seconds: float = 20.0,
    require_answer_generated: bool = False,
    answer_quality_qa: bool = False,
    answer_quality_real: bool = False,
    answer_quality_domain: str = "",
    answer_quality_case_id: str = "",
    answer_quality_max_cases: int = 0,
    answer_quality_profile: str = "",
    answer_quality_product_version: str = "",
    answer_quality_min_pass_rate: float = 0.9,
    answer_quality_require_no_p0_failures: bool = True,
    answer_quality_require_no_forbidden: bool = False,
    answer_quality_require_source_type_match: bool = False,
    product_coverage_qa: bool = False,
    product_coverage_real: bool = False,
    product_db_path: Path | str | None = None,
    product_version: str = "real-product-v1",
    product_domain: str = "product_catalog",
    product_coverage_limit: int = 50,
    product_coverage_min_hit_rate: float = 0.9,
    product_coverage_min_field_rate: float = 0.8,
    conversation_replay: bool = False,
    conversation_replay_real: bool = False,
    conversation_shop_id: str = DRY_RUN_EXAMPLE_SHOP_ID,
    conversation_buyer_id: str = "",
    conversation_session_id: str = "",
    conversation_limit: int = 10,
    conversation_min_pass_rate: float = 0.8,
    conversation_max_failures: int = 0,
    conversation_allow_unclear_rate: float = 0.3,
    answerable_conversation_replay: bool = False,
    answerable_replay_real: bool = False,
    answerable_replay_domain: str = "",
    answerable_replay_max_per_domain: int = 3,
    answerable_replay_min_pass_rate: float = 0.8,
    answerable_replay_max_unclear_rate: float = 0.3,
    answerable_replay_require_no_failures: bool = True,
    answerable_replay_require_rag_hit: bool = False,
    answerable_replay_require_answer_generated: bool = False,
    answerable_replay_selector_audit: bool = False,
    answerable_replay_selector_audit_only: bool = False,
    answerable_replay_require_min_shops: int = 0,
    answerable_replay_require_min_domains: int = 0,
    answerable_replay_require_domain_coverage: bool = False,
    answerable_replay_per_shop_limit: int = 0,
    answerable_replay_per_domain_limit: int = 0,
    answerable_replay_allow_empty_shop: bool = False,
    replay_candidate_pool: bool = False,
    replay_candidate_output: Path | str | None = None,
    replay_benchmark_file: Path | str | None = None,
    replay_benchmark: bool = False,
    replay_benchmark_real: bool = False,
    replay_benchmark_min_pass_rate: float = 0.8,
    replay_benchmark_max_unclear_rate: float = 0.3,
    pending_human_audit: bool = False,
    manual_labeling_pack: bool = False,
    manual_labeling_output_dir: Path | str | None = None,
    manual_labeling_profile: str = "broad",
    replay_label_benchmark: bool = False,
    label_input: Path | str | None = None,
    label_benchmark_output: Path | str | None = None,
) -> dict[str, Any]:
    """Build acceptance artifacts and optionally write them to disk.

    When ``no_write`` is true, this returns the same path plan and payloads but
    does not create directories or files.
    """
    path_plan = build_path_plan(output_dir)
    created_at = _utc_now_iso()
    run_id = Path(path_plan["output_dir"]).name

    synthetic_raw = internal_engine_synthetic_qa.run_cases(
        limit=synthetic_limit,
        sop_file=sop_file,
        use_fake_answer_generator=use_fake_answer_generator,
    )
    dry_run_raw = _run_backend_example(
        sop_file,
        conversation_db_path=conversation_db_path,
        use_fake_answer_generator=use_fake_answer_generator,
        rag_engine_real=rag_engine_real,
        rag_e2e_profile=rag_e2e_profile,
        require_rag_hit=require_rag_hit,
        expect_rag_domain=expect_rag_domain,
        expect_rag_version=expect_rag_version,
        require_rag_version=require_rag_version,
        expect_rag_source_type=expect_rag_source_type,
        expect_answer_generator=expect_answer_generator,
        expect_guardrail_status=expect_guardrail_status,
        fake_answer_dangerous=fake_answer_dangerous,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model,
        rag_domain=rag_engine_domain,
        rag_version=rag_version,
        rag_query=rag_engine_query,
        llm_answer_real=llm_answer_real,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key_env=llm_api_key_env,
        llm_timeout_seconds=llm_timeout_seconds,
        require_answer_generated=require_answer_generated,
    )
    conversation_smoke = _conversation_smoke(conversation_db_path, dry_run_raw)
    cleanup_before = _rag_cleanup(
        enabled=cleanup_rag_pollution_before,
        real=rag_release_real,
        pg_dsn=pg_dsn,
        dry_run=rag_cleanup_dry_run,
        source_type_prefix=rag_cleanup_source_type_prefix,
        namespace=rag_cleanup_namespace,
    )
    legacy_audit_before = _legacy_audit(
        enabled=audit_rag_legacy_pollution or cleanup_rag_legacy_pollution_before or cleanup_rag_legacy_pollution_after,
        real=rag_release_real,
        pg_dsn=pg_dsn,
    )
    legacy_cleanup_before = _legacy_cleanup(
        enabled=cleanup_rag_legacy_pollution_before,
        real=rag_release_real,
        pg_dsn=pg_dsn,
        confirm_delete=legacy_cleanup_confirm_delete,
        version=legacy_cleanup_version,
        shop_id=legacy_cleanup_shop_id,
        domain=legacy_cleanup_domain,
    )
    rag_smoke_result = (
        _real_rag_smoke(sop_file, pg_dsn=pg_dsn, ollama_base_url=ollama_base_url, embedding_model=embedding_model)
        if rag_smoke_real
        else (_rag_smoke(sop_file) if rag_smoke else _rag_skipped())
    )
    rag_qa_result = _rag_retrieval_qa(
        sop_file,
        enabled=rag_retrieval_qa or rag_retrieval_qa_real,
        real=rag_retrieval_qa_real,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model or "bge-m3",
        version=rag_qa_version,
        domain=rag_qa_domain,
        case_id=rag_qa_case_id,
    )
    rag_release_result = _rag_release_gate(
        sop_file,
        enabled=rag_release_gate,
        real=rag_release_real,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model or "bge-m3",
        version=rag_release_version,
        shop_id=rag_release_shop_id,
        min_hit_rate=rag_release_min_hit_rate,
        min_domain_match_rate=rag_release_min_domain_match_rate,
        require_version_match=rag_release_require_version_match,
        require_no_cross_shop=rag_release_require_no_cross_shop,
        require_no_cross_domain=rag_release_require_no_cross_domain,
        run_pollution_tests=rag_release_run_pollution_tests,
    )
    answer_quality_result = _answer_quality_qa(
        enabled=answer_quality_qa or answer_quality_real,
        real=answer_quality_real,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model or "bge-m3",
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key_env=llm_api_key_env,
        shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        version=rag_release_version or "sop-test-v1",
        domain=answer_quality_domain,
        case_id=answer_quality_case_id,
        max_cases=answer_quality_max_cases,
        profile=answer_quality_profile,
        product_version=answer_quality_product_version,
        min_pass_rate=answer_quality_min_pass_rate,
        require_no_p0_failures=answer_quality_require_no_p0_failures,
        require_no_forbidden=answer_quality_require_no_forbidden,
        require_source_type_match=answer_quality_require_source_type_match,
    )
    product_coverage_result = _product_coverage_qa(
        enabled=product_coverage_qa or product_coverage_real,
        real=product_coverage_real,
        product_db_path=product_db_path,
        shop_id=rag_release_shop_id or DRY_RUN_EXAMPLE_SHOP_ID,
        product_version=product_version,
        product_domain=product_domain,
        limit=product_coverage_limit,
        min_hit_rate=product_coverage_min_hit_rate,
        min_field_rate=product_coverage_min_field_rate,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model or "bge-m3",
    )
    conversation_replay_result = _conversation_replay(
        enabled=conversation_replay or conversation_replay_real or answerable_conversation_replay or answerable_replay_real or replay_candidate_pool or replay_benchmark or replay_benchmark_real or pending_human_audit,
        real=conversation_replay_real or answerable_replay_real or replay_benchmark_real,
        conversation_db_path=conversation_db_path,
        shop_id=conversation_shop_id or rag_release_shop_id or DRY_RUN_EXAMPLE_SHOP_ID,
        buyer_id=conversation_buyer_id,
        session_id=conversation_session_id,
        limit=conversation_limit,
        min_pass_rate=conversation_min_pass_rate,
        max_failures=conversation_max_failures,
        allow_unclear_rate=conversation_allow_unclear_rate,
        answerable_only=answerable_conversation_replay or answerable_replay_real,
        answerable_domain=answerable_replay_domain,
        answerable_max_per_domain=answerable_replay_max_per_domain,
        answerable_min_pass_rate=answerable_replay_min_pass_rate,
        answerable_max_unclear_rate=answerable_replay_max_unclear_rate,
        answerable_require_no_failures=answerable_replay_require_no_failures,
        answerable_require_rag_hit=answerable_replay_require_rag_hit,
        answerable_require_answer_generated=answerable_replay_require_answer_generated,
        selector_audit=answerable_replay_selector_audit,
        selector_audit_only=answerable_replay_selector_audit_only,
        require_min_shops=answerable_replay_require_min_shops,
        require_min_domains=answerable_replay_require_min_domains,
        require_domain_coverage=answerable_replay_require_domain_coverage,
        per_shop_limit=answerable_replay_per_shop_limit,
        per_domain_limit=answerable_replay_per_domain_limit,
        allow_empty_shop=answerable_replay_allow_empty_shop,
        generate_candidate_pool=replay_candidate_pool,
        candidate_output=replay_candidate_output,
        benchmark_file=replay_benchmark_file,
        benchmark_enabled=replay_benchmark or replay_benchmark_real,
        benchmark_min_pass_rate=replay_benchmark_min_pass_rate,
        benchmark_max_unclear_rate=replay_benchmark_max_unclear_rate,
        pending_human_audit=pending_human_audit,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model or "bge-m3",
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key_env=llm_api_key_env,
        product_version=product_version,
        sop_version=rag_release_version or "sop-test-v1",
    )
    manual_labeling_result = _manual_labeling_pack(
        enabled=manual_labeling_pack,
        conversation_db_path=conversation_db_path,
        shop_id=conversation_shop_id or rag_release_shop_id or DRY_RUN_EXAMPLE_SHOP_ID,
        output_dir=manual_labeling_output_dir,
        profile=manual_labeling_profile,
    )
    label_benchmark_result = _label_benchmark(
        enabled=replay_label_benchmark,
        label_input=label_input,
        benchmark_output=label_benchmark_output,
    )
    cleanup_after = _rag_cleanup(
        enabled=cleanup_rag_pollution_after,
        real=rag_release_real,
        pg_dsn=pg_dsn,
        dry_run=rag_cleanup_dry_run,
        source_type_prefix=rag_cleanup_source_type_prefix,
        namespace=rag_cleanup_namespace,
    )
    legacy_cleanup_after = _legacy_cleanup(
        enabled=cleanup_rag_legacy_pollution_after,
        real=rag_release_real,
        pg_dsn=pg_dsn,
        confirm_delete=legacy_cleanup_confirm_delete,
        version=legacy_cleanup_version,
        shop_id=legacy_cleanup_shop_id,
        domain=legacy_cleanup_domain,
    )
    comparison_raw = compare_internal_fastgpt.build_comparison(
        synthetic_raw,
        None,
        internal_only=True,
    )
    synthetic_report = canonical_synthetic_report(synthetic_raw, generated_at=created_at)
    dry_run_report = canonical_dry_run_report(dry_run_raw, generated_at=created_at)
    comparison_report = canonical_comparison_report(comparison_raw, generated_at=created_at)
    summary = _build_summary(
        run_id=run_id,
        created_at=created_at,
        synthetic_report=synthetic_report,
        dry_run_report=dry_run_report,
        comparison_report=comparison_report,
        conversation_smoke=conversation_smoke,
        rag_smoke=rag_smoke_result,
        rag_qa=rag_qa_result,
        rag_release=rag_release_result,
        answer_quality=answer_quality_result,
        product_coverage=product_coverage_result,
        conversation_replay=conversation_replay_result,
        cleanup_before=cleanup_before,
        cleanup_after=cleanup_after,
        legacy_audit=legacy_audit_before,
        require_no_legacy=require_no_rag_legacy_pollution,
        legacy_cleanup_before=legacy_cleanup_before,
        legacy_cleanup_after=legacy_cleanup_after,
        manual_labeling=manual_labeling_result,
        label_benchmark=label_benchmark_result,
        no_write=no_write,
    )
    summary["artifact_dir"] = "" if no_write else path_plan["output_dir"]
    manifest = _build_manifest(
        run_id=run_id,
        created_at=created_at,
        command=_sanitize_command(command),
        files=path_plan["files"],
    )

    payloads: dict[str, dict[str, Any]] = {
        "manifest.json": manifest,
        "synthetic_report.json": synthetic_report,
        "dry_run_report.json": dry_run_report,
        "comparison_report.json": comparison_report,
        "summary.json": summary,
    }

    if not no_write:
        _write_payloads(Path(path_plan["output_dir"]), payloads)
    artifact_scan_errors = [] if no_write else scan_artifact_for_forbidden_fields(path_plan["output_dir"])

    return {
        **path_plan,
        "no_write": no_write,
        "would_write": list(ARTIFACT_NAMES),
        "artifacts": payloads,
        "artifact_scan_errors": artifact_scan_errors,
        "schema_errors": {
            name: validate_report_schema(payload)
            for name, payload in payloads.items()
            if name.endswith("_report.json")
        },
    }


def canonical_synthetic_report(raw: Mapping[str, Any], *, generated_at: str) -> dict[str, Any]:
    rows = [row for row in raw.get("cases", []) if isinstance(row, Mapping)]
    summary = raw.get("summary") if isinstance(raw.get("summary"), Mapping) else {}
    return _canonical_report(
        report_type="synthetic",
        generated_at=generated_at,
        sop_version=_text(raw.get("sop_version")),
        knowledge_version=_top_knowledge_version(rows),
        shop_id_hash="",
        passed=_int(summary.get("passed")),
        failed=_int(summary.get("failed")),
        unclear=_int(summary.get("unclear")),
        results=[_canonical_result(row) for row in rows],
    )


def canonical_dry_run_report(raw: Mapping[str, Any], *, generated_at: str) -> dict[str, Any]:
    row = {
        "case_id": "dry-run-example",
        "category": "dry-run",
        "priority": "P0",
        "action": raw.get("action", ""),
        "intent": raw.get("intent", ""),
        "actual_reason": raw.get("reason", ""),
        "risk_flags": raw.get("risk_flags", []),
        "knowledge_source": raw.get("knowledge_source", ""),
        "knowledge_hit_count": raw.get("knowledge_hit_count", 0),
        "sop_domain": _first(raw.get("sop_domains")),
        "sop_version": raw.get("sop_version", ""),
        "knowledge_version": raw.get("knowledge_version", ""),
        "workflow_version": raw.get("workflow_version", ""),
        "guardrail_status": raw.get("guardrail_status", ""),
        "answer_generator": raw.get("answer_generator", ""),
        "answer_generation_source": raw.get("answer_generation_source", ""),
        "answer_confidence": raw.get("answer_confidence", 0.0),
        "answer_generation_status": raw.get("answer_generation_status", ""),
        "answer_length": raw.get("answer_length", 0),
        "answer_hash": raw.get("answer_hash", ""),
        "answer_preview_truncated": raw.get("answer_preview_truncated", ""),
        "used_history_count": raw.get("used_history_count", 0),
        "used_rag_hit_count": raw.get("used_rag_hit_count", 0),
        "prompt_hash": raw.get("prompt_hash", ""),
        "calls_llm": raw.get("calls_llm", False),
        "rag_enabled": raw.get("rag_enabled", False),
        "rag_status": raw.get("rag_status", ""),
        "rag_hit_count": raw.get("rag_hit_count", 0),
        "rag_domains": raw.get("rag_domains", []),
        "rag_top_score": raw.get("rag_top_score", 0.0),
        "rag_version_pinned": raw.get("rag_version_pinned", False),
        "rag_expected_version": raw.get("rag_expected_version", ""),
        "rag_hit_versions": raw.get("rag_hit_versions", []),
        "rag_version_status": raw.get("rag_version_status", ""),
        "rag_shop_status": raw.get("rag_shop_status", ""),
        "rag_source_type_status": raw.get("rag_source_type_status", ""),
        "rag_hit_content_hashes": raw.get("rag_hit_content_hashes", []),
        "rag_hit_source_types": raw.get("rag_hit_source_types", []),
        "rag_hit_source_ids_hash": raw.get("rag_hit_source_ids_hash", []),
        "retrieval_source": raw.get("retrieval_source", ""),
        "calls_ollama": raw.get("calls_ollama", False),
        "connects_pgvector": raw.get("connects_pgvector", False),
        "rag_e2e_profile": raw.get("rag_e2e_profile", False),
        "rag_e2e_status": raw.get("rag_e2e_status", ""),
        "rag_required": raw.get("rag_required", False),
        "rag_requirement_status": raw.get("rag_requirement_status", ""),
        "answer_generator_required": raw.get("answer_generator_required", ""),
        "answer_generation_status": raw.get("answer_generation_status", ""),
        "guardrail_required": raw.get("guardrail_required", False),
        "guardrail_requirement_status": raw.get("guardrail_requirement_status", ""),
        "status": "passed",
        "failures": [],
    }
    return _canonical_report(
        report_type="dry-run",
        generated_at=generated_at,
        sop_version=_text(raw.get("sop_version")),
        knowledge_version=_text(raw.get("knowledge_version")),
        shop_id_hash=_text(raw.get("shop_id_hash")),
        passed=1,
        failed=0,
        unclear=0,
        results=[_canonical_result(row)],
    )


def canonical_comparison_report(raw: Mapping[str, Any], *, generated_at: str) -> dict[str, Any]:
    rows = [row for row in raw.get("cases", []) if isinstance(row, Mapping)]
    summary = raw.get("summary") if isinstance(raw.get("summary"), Mapping) else {}
    return _canonical_report(
        report_type="comparison",
        generated_at=generated_at,
        sop_version=_top_text(rows, "sop_version"),
        knowledge_version=_top_knowledge_version(rows),
        shop_id_hash="",
        passed=_int(summary.get("pass")),
        failed=_int(summary.get("fail")),
        unclear=_int(summary.get("unclear")),
        results=[_canonical_result(row) for row in rows],
    )


def write_json_payload(payload: Mapping[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
        return

    print("internal_acceptance_artifacts: no-send artifact plan")
    print(rendered)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write unified no-send acceptance artifacts for InternalWorkflowEngine."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Artifact directory. Defaults to temp/acceptance/internal-engine/run-YYYYMMDD-HHMMSS.",
    )
    parser.add_argument("--no-write", action="store_true", help="Return the path plan without creating files.")
    parser.add_argument("--json-only", action="store_true", help="Print only parseable JSON.")
    parser.add_argument("--limit", type=int, help="Run at most this many synthetic acceptance cases.")
    parser.add_argument("--sop-file", type=Path, help="Optional reviewed SOP Markdown fixture.")
    parser.add_argument("--conversation-db-path", type=Path, help="Optional read-only conversation DB smoke path.")
    parser.add_argument("--use-fake-answer-generator", action="store_true", help="Use offline fake answer generator.")
    parser.add_argument("--skip-rag-smoke", action="store_true", help="Skip fake RAG smoke.")
    parser.add_argument("--rag-smoke", action="store_true", help="Run fake RAG smoke; enabled by default.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command = [Path(sys.argv[0]).name, *(argv if argv is not None else sys.argv[1:])]
    result = build_artifacts(
        output_dir=args.output_dir,
        command=command,
        no_write=args.no_write,
        synthetic_limit=args.limit,
        sop_file=args.sop_file,
        conversation_db_path=args.conversation_db_path,
        use_fake_answer_generator=args.use_fake_answer_generator,
        rag_smoke=not args.skip_rag_smoke,
        rag_smoke_real=False,
    )
    output = _public_result(result)
    write_json_payload(output, json_only=args.json_only)
    summary = result["artifacts"]["summary.json"]
    return 1 if summary.get("failed") else 0


def _build_manifest(
    *,
    run_id: str,
    created_at: str,
    command: Sequence[str] | None,
    files: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": created_at,
        "backend": "internal",
        "schema_version": SCHEMA_VERSION,
        "command": list(command or []),
        "files": dict(files),
        **NO_SEND_FLAGS,
    }


def _build_summary(
    *,
    run_id: str,
    created_at: str,
    synthetic_report: Mapping[str, Any],
    dry_run_report: Mapping[str, Any],
    comparison_report: Mapping[str, Any],
    conversation_smoke: Mapping[str, Any],
    rag_smoke: Mapping[str, Any],
    rag_qa: Mapping[str, Any],
    rag_release: Mapping[str, Any],
    answer_quality: Mapping[str, Any],
    product_coverage: Mapping[str, Any],
    conversation_replay: Mapping[str, Any],
    cleanup_before: Mapping[str, Any],
    cleanup_after: Mapping[str, Any],
    legacy_audit: Mapping[str, Any],
    require_no_legacy: bool,
    legacy_cleanup_before: Mapping[str, Any],
    legacy_cleanup_after: Mapping[str, Any],
    manual_labeling: Mapping[str, Any],
    label_benchmark: Mapping[str, Any],
    no_write: bool,
) -> dict[str, Any]:
    dry_run_rag_status = _text(_result_value(dry_run_report, "rag_status"))
    dry_run_calls_ollama = bool(_result_value(dry_run_report, "calls_ollama"))
    dry_run_connects_pgvector = bool(_result_value(dry_run_report, "connects_pgvector"))
    dry_run_calls_llm = bool(_result_value(dry_run_report, "calls_llm"))
    dry_run_rag_e2e_status = _text(_result_value(dry_run_report, "rag_e2e_status"))
    dry_run_answer_generation_status = _text(_result_value(dry_run_report, "answer_generation_status"))
    return {
        "run_id": run_id,
        "created_at": created_at,
        "backend": "internal",
        "schema_version": SCHEMA_VERSION,
        **NO_SEND_FLAGS,
        "calls_llm": dry_run_calls_llm or bool(answer_quality.get("calls_llm", False)) or bool(conversation_replay.get("calls_llm", False)),
        "no_write": no_write,
        "passed": int(synthetic_report.get("passed", 0))
        + int(dry_run_report.get("passed", 0))
        + int(comparison_report.get("passed", 0)),
        "failed": int(synthetic_report.get("failed", 0))
        + int(dry_run_report.get("failed", 0))
        + int(comparison_report.get("failed", 0))
        + (1 if _text(rag_smoke.get("rag_status")) == "error" else 0)
        + (1 if _text(rag_qa.get("rag_qa_status")) == "failed" else 0)
        + (1 if _text(rag_release.get("rag_release_status")) == "failed" else 0)
        + (1 if _text(answer_quality.get("answer_quality_status")) == "failed" else 0)
        + (1 if _text(product_coverage.get("product_coverage_status")) in {"failed", "error", "unclear"} else 0)
        + (1 if _text(conversation_replay.get("conversation_replay_status")) in {"failed", "error"} else 0)
        + (1 if _text(conversation_replay.get("answerable_replay_status")) in {"failed", "error"} else 0)
        + (1 if _text(conversation_replay.get("replay_benchmark_status")) in {"failed", "error"} else 0)
        + (1 if _text(cleanup_before.get("status")) == "error" or _text(cleanup_before.get("status")) == "rejected" else 0)
        + (1 if _text(cleanup_after.get("status")) == "error" or _text(cleanup_after.get("status")) == "rejected" else 0)
        + (1 if _text(legacy_audit.get("status")) == "error" or _text(legacy_audit.get("status")) == "rejected" else 0)
        + (1 if require_no_legacy and _int(legacy_audit.get("legacy_candidate_count")) > 0 else 0)
        + (1 if _text(legacy_cleanup_before.get("status")) == "error" or _text(legacy_cleanup_before.get("status")) == "rejected" else 0)
        + (1 if _text(legacy_cleanup_after.get("status")) == "error" or _text(legacy_cleanup_after.get("status")) == "rejected" else 0)
        + (1 if _text(manual_labeling.get("status")) == "failed" else 0)
        + (1 if _text(label_benchmark.get("status")) == "failed" else 0)
        + (1 if dry_run_rag_status.startswith("error") else 0)
        + (1 if dry_run_answer_generation_status.startswith("failed") else 0)
        + (1 if dry_run_rag_e2e_status == "failed" else 0),
        "unclear": int(synthetic_report.get("unclear", 0))
        + int(dry_run_report.get("unclear", 0))
        + int(comparison_report.get("unclear", 0)),
        "artifact_dir": "",
        "synthetic_summary": {
            "total": synthetic_report.get("case_count", 0),
            "passed": synthetic_report.get("passed", 0),
            "failed": synthetic_report.get("failed", 0),
            "unclear": synthetic_report.get("unclear", 0),
        },
        "dry_run": {
            "runner": dry_run_report.get("backend"),
            "dry_run": dry_run_report.get("dry_run"),
            "action": dry_run_report.get("action"),
            "knowledge_hit_count": dry_run_report.get("knowledge_hit_count"),
        },
        "comparison_summary": {
            "total": comparison_report.get("case_count", 0),
            "passed": comparison_report.get("passed", 0),
            "failed": comparison_report.get("failed", 0),
            "unclear": comparison_report.get("unclear", 0),
        },
        "conversation_smoke_status": _text(conversation_smoke.get("conversation_smoke_status")),
        "conversation_schema_status": _text(conversation_smoke.get("conversation_schema_status")),
        "history_message_count": _int(conversation_smoke.get("history_message_count")),
        "history_window_size": _int(conversation_smoke.get("history_window_size")),
        "pending_human": bool(conversation_smoke.get("pending_human", False)),
        "rag_status": _text(rag_smoke.get("rag_status")),
        "vector_store": _text(rag_smoke.get("vector_store")),
        "embedding_model": _text(rag_smoke.get("embedding_model")),
        "chunk_count": _int(rag_smoke.get("chunk_count")),
        "retrieval_hit_count": _int(rag_smoke.get("retrieval_hit_count")),
        "calls_ollama": bool(rag_smoke.get("calls_ollama", False)) or bool(rag_qa.get("calls_ollama", False)) or bool(rag_release.get("calls_ollama", False)) or bool(answer_quality.get("calls_ollama", False)) or bool(product_coverage.get("calls_ollama", False)) or bool(conversation_replay.get("calls_ollama", False)) or dry_run_calls_ollama,
        "connects_pgvector": bool(rag_smoke.get("connects_pgvector", False)) or bool(rag_qa.get("connects_pgvector", False)) or bool(rag_release.get("connects_pgvector", False)) or bool(answer_quality.get("connects_pgvector", False)) or bool(product_coverage.get("connects_pgvector", False)) or bool(conversation_replay.get("connects_pgvector", False)) or dry_run_connects_pgvector,
        "rag_real_status": _text(rag_smoke.get("rag_real_status")),
        "ollama_status": _text(rag_smoke.get("ollama_status")),
        "pgvector_status": _text(rag_smoke.get("pgvector_status")),
        "rag_engine_status": dry_run_rag_status,
        "rag_engine_hit_count": _int(_result_value(dry_run_report, "rag_hit_count")),
        "rag_engine_real": dry_run_calls_ollama or dry_run_connects_pgvector,
        "rag_e2e_status": dry_run_rag_e2e_status,
        "rag_requirement_status": _text(_result_value(dry_run_report, "rag_requirement_status")),
        "rag_version_status": _text(_result_value(dry_run_report, "rag_version_status")),
        "rag_expected_version": _text(_result_value(dry_run_report, "rag_expected_version")),
        "rag_hit_versions": list(_result_value(dry_run_report, "rag_hit_versions") or []),
        "rag_source_type_status": _text(_result_value(dry_run_report, "rag_source_type_status")),
        "answer_generation_status": _text(_result_value(dry_run_report, "answer_generation_status")),
        "llm_answer_status": dry_run_answer_generation_status or "not_run",
        "llm_answer_generator": _text(_result_value(dry_run_report, "answer_generator")),
        "llm_answer_length": _int(_result_value(dry_run_report, "answer_length")),
        "llm_answer_hash": _text(_result_value(dry_run_report, "answer_hash")),
        "llm_answer_preview_truncated": _text(_result_value(dry_run_report, "answer_preview_truncated")),
        "llm_guardrail_status": _text(_result_value(dry_run_report, "guardrail_status")),
        "guardrail_requirement_status": _text(_result_value(dry_run_report, "guardrail_requirement_status")),
        "rag_engine_domain": _first(_result_value(dry_run_report, "rag_domains")),
        "rag_qa_status": _text(rag_qa.get("rag_qa_status")),
        "rag_qa_total": _int(rag_qa.get("rag_qa_total")),
        "rag_qa_passed": _int(rag_qa.get("rag_qa_passed")),
        "rag_qa_failed": _int(rag_qa.get("rag_qa_failed")),
        "rag_qa_hit_rate": _float(rag_qa.get("rag_qa_hit_rate")),
        "rag_qa_domain_match_rate": _float(rag_qa.get("rag_qa_domain_match_rate")),
        "rag_qa_version_match_rate": _float(rag_qa.get("rag_qa_version_match_rate")),
        "rag_release_status": _text(rag_release.get("rag_release_status")),
        "rag_release_real": bool(rag_release.get("rag_release_real", False)),
        "rag_release_version": _text(rag_release.get("rag_release_version")),
        "rag_release_shop_id_hash": _text(rag_release.get("rag_release_shop_id_hash")),
        "rag_release_total": _int(rag_release.get("rag_release_total")),
        "rag_release_passed": _int(rag_release.get("rag_release_passed")),
        "rag_release_failed": _int(rag_release.get("rag_release_failed")),
        "rag_release_hit_rate": _float(rag_release.get("rag_release_hit_rate")),
        "rag_release_domain_match_rate": _float(rag_release.get("rag_release_domain_match_rate")),
        "rag_release_version_match_rate": _float(rag_release.get("rag_release_version_match_rate")),
        "rag_release_cross_shop_failures": _int(rag_release.get("rag_release_cross_shop_failures")),
        "rag_release_cross_domain_failures": _int(rag_release.get("rag_release_cross_domain_failures")),
        "rag_release_wrong_version_failures": _int(rag_release.get("rag_release_wrong_version_failures")),
        "rag_release_pollution_status": _text(rag_release.get("rag_release_pollution_status")),
        "answer_quality_status": _text(answer_quality.get("answer_quality_status")),
        "answer_quality_total": _int(answer_quality.get("answer_quality_total")),
        "answer_quality_passed": _int(answer_quality.get("answer_quality_passed")),
        "answer_quality_failed": _int(answer_quality.get("answer_quality_failed")),
        "answer_quality_pass_rate": _float(answer_quality.get("answer_quality_pass_rate")),
        "answer_quality_p0_failures": _int(answer_quality.get("answer_quality_p0_failures")),
        "answer_quality_forbidden_phrase_failures": _int(answer_quality.get("answer_quality_forbidden_phrase_failures")),
        "answer_quality_negated_forbidden_phrase_count": _int(answer_quality.get("answer_quality_negated_forbidden_phrase_count")),
        "answer_quality_guardrail_blocked_count": _int(answer_quality.get("answer_quality_guardrail_blocked_count")),
        "answer_quality_action_match_rate": _float(answer_quality.get("answer_quality_action_match_rate")),
        "answer_quality_domain_match_rate": _float(answer_quality.get("answer_quality_domain_match_rate")),
        "answer_quality_source_type_match_rate": _float(answer_quality.get("answer_quality_source_type_match_rate")),
        "answer_quality_version_match_rate": _float(answer_quality.get("answer_quality_version_match_rate")),
        "answer_quality_profile": _text(answer_quality.get("answer_quality_profile")),
        "answer_quality_release_status": _text(answer_quality.get("answer_quality_release_status")),
        "answer_quality_release_min_pass_rate": _float(answer_quality.get("answer_quality_release_min_pass_rate")),
        "answer_quality_product_source_type_match_rate": _float(answer_quality.get("answer_quality_product_source_type_match_rate")),
        "product_coverage_status": _text(product_coverage.get("product_coverage_status")),
        "product_coverage_total": _int(product_coverage.get("product_coverage_total")),
        "product_coverage_passed": _int(product_coverage.get("product_coverage_passed")),
        "product_coverage_failed": _int(product_coverage.get("product_coverage_failed")),
        "product_coverage_hit_rate": _float(product_coverage.get("product_coverage_hit_rate")),
        "product_coverage_field_rate": _float(product_coverage.get("product_coverage_field_rate")),
        "product_coverage_source_type_match_rate": _float(product_coverage.get("product_coverage_source_type_match_rate")),
        "product_coverage_version_match_rate": _float(product_coverage.get("product_coverage_version_match_rate")),
        "conversation_replay_status": _text(conversation_replay.get("conversation_replay_status")),
        "conversation_replay_total": _int(conversation_replay.get("conversation_replay_total")),
        "conversation_replay_passed": _int(conversation_replay.get("conversation_replay_passed")),
        "conversation_replay_failed": _int(conversation_replay.get("conversation_replay_failed")),
        "conversation_replay_unclear": _int(conversation_replay.get("conversation_replay_unclear")),
        "conversation_replay_pass_rate": _float(conversation_replay.get("conversation_replay_pass_rate")),
        "conversation_replay_rag_hit_rate": _float(conversation_replay.get("conversation_replay_rag_hit_rate")),
        "conversation_replay_guardrail_blocked_count": _int(conversation_replay.get("conversation_replay_guardrail_blocked_count")),
        "conversation_replay_transfer_human_count": _int(conversation_replay.get("conversation_replay_transfer_human_count")),
        "answerable_replay_status": _text(conversation_replay.get("answerable_replay_status")),
        "answerable_replay_total": _int(conversation_replay.get("answerable_replay_total")),
        "answerable_replay_passed": _int(conversation_replay.get("answerable_replay_passed")),
        "answerable_replay_failed": _int(conversation_replay.get("answerable_replay_failed")),
        "answerable_replay_unclear": _int(conversation_replay.get("answerable_replay_unclear")),
        "answerable_replay_pass_rate": _float(conversation_replay.get("answerable_replay_pass_rate")),
        "answerable_replay_rag_hit_rate": _float(conversation_replay.get("answerable_replay_rag_hit_rate")),
        "answerable_replay_answer_generated_rate": _float(conversation_replay.get("answerable_replay_answer_generated_rate")),
        "answerable_selector_scanned_total": _int(conversation_replay.get("answerable_selector_scanned_total")),
        "answerable_selector_candidate_total": _int(conversation_replay.get("answerable_selector_candidate_total")),
        "answerable_selector_selected_total": _int(conversation_replay.get("answerable_selector_selected_total")),
        "answerable_selector_excluded_by_reason": dict(conversation_replay.get("answerable_selector_excluded_by_reason") or {}),
        "answerable_selector_selected_by_domain": dict(conversation_replay.get("answerable_selector_selected_by_domain") or {}),
        "answerable_replay_shops_total": _int(conversation_replay.get("answerable_replay_shops_total")),
        "answerable_replay_shops_with_candidates": _int(conversation_replay.get("answerable_replay_shops_with_candidates")),
        "answerable_replay_domain_coverage_status": _text(conversation_replay.get("answerable_replay_domain_coverage_status")),
        "answerable_replay_domains_missing": list(conversation_replay.get("answerable_replay_domains_missing") or []),
        "answerable_replay_unclear_reason_counts": dict(conversation_replay.get("answerable_replay_unclear_reason_counts") or {}),
        "answerable_replay_rag_miss_reason_counts": dict(conversation_replay.get("answerable_replay_rag_miss_reason_counts") or {}),
        "replay_candidate_total": _int(conversation_replay.get("replay_candidate_total")),
        "replay_candidate_selected_by_domain": dict(conversation_replay.get("replay_candidate_selected_by_domain") or {}),
        "replay_candidate_excluded_by_reason": dict(conversation_replay.get("replay_candidate_excluded_by_reason") or {}),
        "replay_benchmark_case_count": _int(conversation_replay.get("replay_benchmark_case_count")),
        "replay_benchmark_pass_rate": _float(conversation_replay.get("replay_benchmark_pass_rate")),
        "replay_benchmark_unclear_rate": _float(conversation_replay.get("replay_benchmark_unclear_rate")),
        "pending_human_answerable_candidates": _int(conversation_replay.get("pending_human_answerable_candidates")),
        "manual_labeling_candidate_count": _int(manual_labeling.get("candidate_count")),
        "manual_labeling_selected_by_domain": dict(manual_labeling.get("selected_by_domain") or {}),
        "label_benchmark_case_count": _int(label_benchmark.get("benchmark_case_count")),
        "rag_cleanup_before_status": _text(cleanup_before.get("status")),
        "rag_cleanup_after_status": _text(cleanup_after.get("status")),
        "rag_cleanup_deleted_count": _int(cleanup_before.get("deleted_count")) + _int(cleanup_after.get("deleted_count")),
        "rag_cleanup_dry_run": bool(cleanup_before.get("dry_run", True)) and bool(cleanup_after.get("dry_run", True)),
        "rag_legacy_audit_status": _text(legacy_audit.get("status")),
        "rag_legacy_candidate_count": _int(legacy_audit.get("legacy_candidate_count")),
        "rag_legacy_cleanup_status": _legacy_cleanup_status(legacy_cleanup_before, legacy_cleanup_after),
        "rag_legacy_cleanup_deleted_count": _int(legacy_cleanup_before.get("deleted_count"))
        + _int(legacy_cleanup_after.get("deleted_count")),
        "rag_legacy_cleanup_dry_run": bool(legacy_cleanup_before.get("dry_run", True))
        and bool(legacy_cleanup_after.get("dry_run", True)),
        "answer_generator": _text(_result_value(dry_run_report, "answer_generator")),
        "guardrail_status": _text(_result_value(dry_run_report, "guardrail_status")),
    }


def _dry_run_args() -> argparse.Namespace:
    return argparse.Namespace(
        shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        user_id="",
        buyer_id="synthetic-buyer",
        session_id="synthetic-session",
        message=DRY_RUN_EXAMPLE_MESSAGE,
        message_type="text",
        db_path=None,
        use_db=False,
        fake_product=True,
        sop_file=None,
        history_message=[],
        with_fake_history=False,
        pending_human=False,
        use_conversation_db=False,
        conversation_db_path=None,
        conversation_session_id="",
        conversation_buyer_id="",
        use_fake_answer_generator=False,
        use_real_answer_generator=False,
        llm_base_url="",
        llm_model="",
        llm_api_key_env="AI_WORKFLOW_LLM_API_KEY",
        llm_timeout_seconds=20.0,
        answer_preview_max_chars=160,
        require_answer_generated=False,
        fake_answer_style="conservative",
        fake_answer_dangerous=False,
        rag_enabled=False,
        use_fake_rag=False,
        use_real_rag=False,
        pg_dsn="",
        ollama_base_url="",
        embedding_model="",
        rag_domain="logistics_policy",
        rag_version="",
        rag_top_k=3,
        rag_hit_title="synthetic RAG hit",
        rag_hit_content="synthetic safe RAG content",
        rag_e2e_profile=False,
        require_rag_hit=False,
        expect_rag_domain="",
        expect_rag_version="",
        require_rag_version=False,
        expect_shop_id="",
        expect_rag_source_type="",
        expect_rag_content_hash="",
        expect_answer_generator="",
        expect_guardrail_status="",
        json_only=True,
        dry_run=True,
    )


def _write_payloads(output_dir: Path, payloads: Mapping[str, Mapping[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _public_result(result: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = result["artifacts"]
    return {
        "output_dir": result["output_dir"],
        "files": result["files"],
        "no_write": result["no_write"],
        "would_write": result["would_write"],
        "manifest": artifacts["manifest.json"],
        "summary": artifacts["summary.json"],
        "artifact_scan_errors": result.get("artifact_scan_errors", []),
    }


def scan_artifact_for_forbidden_fields(path: str | Path) -> list[str]:
    """Scan one JSON file or an artifact directory for forbidden raw fields."""
    target = Path(path)
    if not target.exists():
        return [f"{target}: path does not exist"]
    if target.is_file():
        return _scan_json_file(target)
    if target.is_dir():
        errors: list[str] = []
        for json_file in sorted(target.glob("*.json")):
            errors.extend(_scan_json_file(json_file))
        return errors
    return [f"{target}: unsupported artifact path"]


def _scan_json_file(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [f"{path.name}: invalid JSON"]
    errors = scan_json_payload_for_forbidden_fields(payload)
    return [f"{path.name}: {error}" for error in errors]


def _run_backend_example(
    sop_file: Path | str | None,
    *,
    conversation_db_path: Path | str | None = None,
    use_fake_answer_generator: bool = False,
    rag_engine_real: bool = False,
    rag_e2e_profile: bool = False,
    require_rag_hit: bool = False,
    expect_rag_domain: str = "",
    expect_rag_version: str = "",
    require_rag_version: bool = False,
    expect_rag_source_type: str = "",
    expect_answer_generator: str = "",
    expect_guardrail_status: str = "",
    fake_answer_dangerous: bool = False,
    pg_dsn: str = "",
    ollama_base_url: str = "",
    embedding_model: str = "",
    rag_domain: str = "logistics_policy",
    rag_version: str = "",
    rag_query: str = "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
    llm_answer_real: bool = False,
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key_env: str = "AI_WORKFLOW_LLM_API_KEY",
    llm_timeout_seconds: float = 20.0,
    require_answer_generated: bool = False,
) -> dict[str, Any]:
    args = _dry_run_args()
    args.sop_file = Path(sop_file) if sop_file else None
    if conversation_db_path:
        args.use_conversation_db = True
        args.conversation_db_path = Path(conversation_db_path)
    args.use_fake_answer_generator = use_fake_answer_generator
    if rag_engine_real:
        args.message = rag_query
        args.rag_enabled = True
        args.use_real_rag = True
        args.pg_dsn = pg_dsn
        args.ollama_base_url = ollama_base_url
        args.embedding_model = embedding_model
        args.rag_domain = rag_domain
        args.rag_version = rag_version
        args.rag_top_k = 3
        args.use_fake_answer_generator = not llm_answer_real
    elif rag_e2e_profile:
        args.message = rag_query
        args.rag_enabled = True
        args.use_fake_rag = True
        args.rag_domain = rag_domain
        args.rag_version = rag_version
        args.rag_top_k = 3
        args.use_fake_answer_generator = not llm_answer_real
    if llm_answer_real:
        args.use_real_answer_generator = True
        args.use_fake_answer_generator = False
        args.llm_base_url = llm_base_url
        args.llm_model = llm_model
        args.llm_api_key_env = llm_api_key_env
        args.llm_timeout_seconds = llm_timeout_seconds
        args.require_answer_generated = require_answer_generated
    args.fake_answer_dangerous = fake_answer_dangerous
    args.rag_e2e_profile = rag_e2e_profile
    args.require_rag_hit = require_rag_hit
    args.expect_rag_domain = expect_rag_domain
    args.expect_rag_version = expect_rag_version
    args.require_rag_version = require_rag_version
    args.expect_shop_id = DRY_RUN_EXAMPLE_SHOP_ID if expect_rag_version else ""
    args.expect_rag_source_type = expect_rag_source_type
    args.expect_rag_content_hash = ""
    args.expect_answer_generator = expect_answer_generator
    args.expect_guardrail_status = expect_guardrail_status
    try:
        result = asyncio.run(internal_backend_dry_run.run_engine(args))
        return internal_backend_dry_run.result_summary(args, result)
    except ValueError as exc:
        return _dry_run_error_summary(args, exc)


def _conversation_smoke(
    conversation_db_path: Path | str | None,
    dry_run_raw: Mapping[str, Any],
) -> dict[str, Any]:
    if not conversation_db_path:
        return {
            "conversation_smoke_status": "skipped",
            "conversation_schema_status": "skipped",
            "history_message_count": 0,
            "history_window_size": 0,
            "pending_human": False,
        }
    probe = conversation_context_schema_probe.probe_schema(conversation_db_path)
    return {
        "conversation_smoke_status": "ok",
        "conversation_schema_status": _text(probe.get("status")),
        "history_message_count": _int(dry_run_raw.get("history_message_count")),
        "history_window_size": _int(dry_run_raw.get("history_window_size")),
        "pending_human": bool(dry_run_raw.get("pending_human", False)),
    }


def _rag_smoke(sop_file: Path | str | None) -> dict[str, Any]:
    sop_path = Path(sop_file) if sop_file else REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"
    index_args = argparse.Namespace(
        shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        domain=[],
        sop_file=sop_path,
        dry_run=False,
        json_only=True,
        output_json=None,
        pg_dsn="",
        embedding_provider="fake",
        embedding_model="bge-m3",
        embedding_dimension=1024,
    )
    retrieve_args = argparse.Namespace(
        shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        domain="logistics_policy",
        query="why has it not arrived",
        top_k=3,
        sop_file=sop_path,
        json_only=True,
        pg_dsn="",
        embedding_provider="fake",
        embedding_model="bge-m3",
        embedding_dimension=1024,
    )
    try:
        indexed = internal_rag_index.run_index(index_args)
        retrieved = internal_rag_retrieve.run_retrieve(retrieve_args)
    except Exception as exc:  # noqa: BLE001 - smoke failure is summarized.
        return {
            "rag_status": f"error:{type(exc).__name__}",
            "vector_store": "in_memory",
            "embedding_model": "bge-m3",
            "chunk_count": 0,
            "retrieval_hit_count": 0,
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    return {
        "rag_status": "ok" if _int(retrieved.get("hit_count")) > 0 else "empty",
        "rag_real_status": "not_run",
        "ollama_status": "not_run",
        "pgvector_status": "not_run",
        "vector_store": _text(indexed.get("vector_store")) or "in_memory",
        "embedding_model": _text(indexed.get("embedding_model")) or "bge-m3",
        "chunk_count": _int(indexed.get("chunk_count")),
        "retrieval_hit_count": _int(retrieved.get("hit_count")),
        "calls_ollama": bool(indexed.get("calls_ollama")) or bool(retrieved.get("calls_ollama")),
        "connects_pgvector": bool(indexed.get("connects_pgvector")) or bool(retrieved.get("connects_pgvector")),
    }


def _rag_skipped() -> dict[str, Any]:
    return {
        "rag_status": "skipped",
        "rag_real_status": "not_run",
        "ollama_status": "not_run",
        "pgvector_status": "not_run",
        "vector_store": "",
        "embedding_model": "",
        "chunk_count": 0,
        "retrieval_hit_count": 0,
        "calls_ollama": False,
        "connects_pgvector": False,
    }


def _rag_retrieval_qa(
    sop_file: Path | str | None,
    *,
    enabled: bool,
    real: bool,
    pg_dsn: str,
    ollama_base_url: str,
    embedding_model: str,
    version: str,
    domain: str,
    case_id: str,
) -> dict[str, Any]:
    if not enabled:
        return {
            "rag_qa_status": "skipped",
            "rag_qa_total": 0,
            "rag_qa_passed": 0,
            "rag_qa_failed": 0,
            "rag_qa_hit_rate": 0.0,
            "rag_qa_domain_match_rate": 0.0,
            "rag_qa_version_match_rate": 0.0,
        }
    args = argparse.Namespace(
        real=real,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model or "bge-m3",
        shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        version=version or "sop-test-v1",
        sop_file=Path(sop_file) if sop_file else REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md",
        json_only=True,
        case_id=case_id,
        domain=domain,
        top_k=3,
        require_version=True,
        run_pollution_tests=False,
        expected_shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        expected_version=version or "sop-test-v1",
        expected_domain="",
        fail_on_cross_shop=False,
        fail_on_cross_domain=False,
        fail_on_wrong_version=False,
        pollution_fixture=False,
        pollution_kind="all",
        pollution_version="old-version",
        pollution_shop_id="synthetic-shop-2",
        pollution_domain="unrelated_policy",
    )
    payload = internal_rag_retrieval_qa.run_qa(args)
    return {
        "rag_qa_status": _text(payload.get("status")),
        "rag_qa_total": _int(payload.get("total")),
        "rag_qa_passed": _int(payload.get("passed")),
        "rag_qa_failed": _int(payload.get("failed")),
        "rag_qa_hit_rate": _float(payload.get("retrieval_hit_rate")),
        "rag_qa_domain_match_rate": _float(payload.get("domain_match_rate")),
        "rag_qa_version_match_rate": _float(payload.get("version_match_rate")),
        "rag_qa_cross_shop_failures": _int(payload.get("cross_shop_failures")),
        "rag_qa_cross_domain_failures": _int(payload.get("cross_domain_failures")),
        "rag_qa_wrong_version_failures": _int(payload.get("wrong_version_failures")),
        "rag_qa_pollution_status": _text(payload.get("pollution_status")),
        "calls_ollama": bool(payload.get("calls_ollama", False)),
        "connects_pgvector": bool(payload.get("connects_pgvector", False)),
    }


def _rag_release_gate(
    sop_file: Path | str | None,
    *,
    enabled: bool,
    real: bool,
    pg_dsn: str,
    ollama_base_url: str,
    embedding_model: str,
    version: str,
    shop_id: str,
    min_hit_rate: float,
    min_domain_match_rate: float,
    require_version_match: bool,
    require_no_cross_shop: bool,
    require_no_cross_domain: bool,
    run_pollution_tests: bool,
) -> dict[str, Any]:
    release_version = version or "sop-test-v1"
    release_shop_id = shop_id or DRY_RUN_EXAMPLE_SHOP_ID
    skipped = {
        "rag_release_status": "skipped",
        "rag_release_real": bool(real),
        "rag_release_version": release_version,
        "rag_release_shop_id_hash": _short_hash(release_shop_id),
        "rag_release_total": 0,
        "rag_release_passed": 0,
        "rag_release_failed": 0,
        "rag_release_hit_rate": 0.0,
        "rag_release_domain_match_rate": 0.0,
        "rag_release_version_match_rate": 0.0,
        "rag_release_cross_shop_failures": 0,
        "rag_release_cross_domain_failures": 0,
        "rag_release_wrong_version_failures": 0,
        "rag_release_pollution_status": "not_run",
        "calls_ollama": False,
        "connects_pgvector": False,
    }
    if not enabled:
        return skipped
    if real and (not pg_dsn or not ollama_base_url or not embedding_model):
        return {
            **skipped,
            "rag_release_status": "failed",
            "rag_release_failed": 1,
            "rag_release_pollution_status": "not_run",
            "error_type": _missing_real_rag_error(pg_dsn, ollama_base_url, embedding_model),
        }
    args = argparse.Namespace(
        real=real,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model or "bge-m3",
        shop_id=release_shop_id,
        version=release_version,
        sop_file=Path(sop_file) if sop_file else REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md",
        json_only=True,
        case_id="",
        domain="",
        top_k=3,
        require_version=True,
        run_pollution_tests=run_pollution_tests,
        expected_shop_id=release_shop_id,
        expected_version=release_version,
        expected_domain="",
        fail_on_cross_shop=require_no_cross_shop,
        fail_on_cross_domain=require_no_cross_domain,
        fail_on_wrong_version=require_version_match,
        pollution_fixture=run_pollution_tests,
        pollution_kind="all",
        pollution_version="old-version",
        pollution_shop_id="synthetic-shop-2",
        pollution_domain="unrelated_policy",
    )
    payload = internal_rag_retrieval_qa.run_qa(args)
    hit_rate = _float(payload.get("retrieval_hit_rate"))
    domain_rate = _float(payload.get("domain_match_rate"))
    version_rate = _float(payload.get("version_match_rate"))
    cross_shop = _int(payload.get("cross_shop_failures"))
    cross_domain = _int(payload.get("cross_domain_failures"))
    wrong_version = _int(payload.get("wrong_version_failures"))
    failed = _int(payload.get("failed"))
    failed += 1 if hit_rate < float(min_hit_rate) else 0
    failed += 1 if domain_rate < float(min_domain_match_rate) else 0
    failed += 1 if require_version_match and version_rate < 1.0 else 0
    failed += 1 if require_no_cross_shop and cross_shop else 0
    failed += 1 if require_no_cross_domain and cross_domain else 0
    failed += 1 if require_version_match and wrong_version else 0
    return {
        "rag_release_status": "passed" if failed == 0 and payload.get("status") == "passed" else "failed",
        "rag_release_real": bool(real),
        "rag_release_version": release_version,
        "rag_release_shop_id_hash": _short_hash(release_shop_id),
        "rag_release_total": _int(payload.get("total")),
        "rag_release_passed": _int(payload.get("passed")),
        "rag_release_failed": failed,
        "rag_release_hit_rate": hit_rate,
        "rag_release_domain_match_rate": domain_rate,
        "rag_release_version_match_rate": version_rate,
        "rag_release_cross_shop_failures": cross_shop,
        "rag_release_cross_domain_failures": cross_domain,
        "rag_release_wrong_version_failures": wrong_version,
        "rag_release_pollution_status": _text(payload.get("pollution_status")),
        "calls_ollama": bool(payload.get("calls_ollama", False)),
        "connects_pgvector": bool(payload.get("connects_pgvector", False)),
    }


def _answer_quality_qa(
    *,
    enabled: bool,
    real: bool,
    pg_dsn: str,
    ollama_base_url: str,
    embedding_model: str,
    llm_base_url: str,
    llm_model: str,
    llm_api_key_env: str,
    shop_id: str,
    version: str,
    domain: str,
    case_id: str,
    max_cases: int,
    profile: str = "",
    product_version: str = "",
    min_pass_rate: float = 0.9,
    require_no_p0_failures: bool = True,
    require_no_forbidden: bool = False,
    require_source_type_match: bool = False,
) -> dict[str, Any]:
    profile = _normalize_answer_quality_profile(profile, enabled=enabled, real=real)
    if not enabled:
        return {
            "answer_quality_profile": "skipped",
            "answer_quality_release_status": "skipped",
            "answer_quality_release_min_pass_rate": float(min_pass_rate),
            "answer_quality_status": "skipped",
            "answer_quality_total": 0,
            "answer_quality_passed": 0,
            "answer_quality_failed": 0,
            "answer_quality_pass_rate": 0.0,
            "answer_quality_p0_failures": 0,
            "answer_quality_forbidden_phrase_failures": 0,
            "answer_quality_negated_forbidden_phrase_count": 0,
            "answer_quality_guardrail_blocked_count": 0,
            "answer_quality_action_match_rate": 0.0,
            "answer_quality_domain_match_rate": 0.0,
            "answer_quality_source_type_match_rate": 0.0,
            "answer_quality_version_match_rate": 0.0,
            "answer_quality_product_source_type_match_rate": 0.0,
            "calls_ollama": False,
            "connects_pgvector": False,
            "calls_llm": False,
        }
    payload = internal_answer_quality_qa.run_qa(
        argparse.Namespace(
            real_rag=real,
            real_llm=real,
            pg_dsn=pg_dsn,
            ollama_base_url=ollama_base_url,
            embedding_model=embedding_model or "bge-m3",
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_api_key_env=llm_api_key_env,
            shop_id=shop_id,
            version=version or "sop-test-v1",
            domain=domain,
            case_id=case_id,
            top_k=3,
            json_only=True,
            max_cases=max(0, int(max_cases or 0)),
            product_version=product_version or "product-test-v1",
            product_domain="product_catalog",
            allow_preview=True,
        )
    )
    pass_rate = _float(payload.get("pass_rate"))
    p0_failures = _int(payload.get("p0_failures"))
    failed = _int(payload.get("failed"))
    forbidden_failures = _int(payload.get("forbidden_phrase_failures"))
    source_type_rate = _float(payload.get("source_type_match_rate"))
    domain_rate = _float(payload.get("domain_match_rate"))
    version_rate = _float(payload.get("version_match_rate"))
    if pass_rate < float(min_pass_rate):
        failed += 1
    if require_no_p0_failures and p0_failures:
        failed += 1
    if require_no_forbidden and forbidden_failures:
        failed += 1
    if require_source_type_match and source_type_rate < 0.9:
        failed += 1
    if profile == "real_full" and (domain_rate < 0.9 or version_rate < 1.0):
        failed += 1
    release_status = "passed" if failed == 0 and payload.get("status") == "passed" else "failed"
    return {
        "answer_quality_profile": profile,
        "answer_quality_release_status": release_status,
        "answer_quality_release_min_pass_rate": float(min_pass_rate),
        "answer_quality_status": release_status,
        "answer_quality_total": _int(payload.get("total")),
        "answer_quality_passed": _int(payload.get("passed")),
        "answer_quality_failed": failed,
        "answer_quality_pass_rate": pass_rate,
        "answer_quality_p0_failures": p0_failures,
        "answer_quality_forbidden_phrase_failures": forbidden_failures,
        "answer_quality_negated_forbidden_phrase_count": _int(payload.get("negated_forbidden_phrase_count")),
        "answer_quality_guardrail_blocked_count": _int(payload.get("guardrail_blocked_count")),
        "answer_quality_action_match_rate": _float(payload.get("action_match_rate")),
        "answer_quality_domain_match_rate": _float(payload.get("domain_match_rate")),
        "answer_quality_source_type_match_rate": _float(payload.get("source_type_match_rate")),
        "answer_quality_version_match_rate": _float(payload.get("version_match_rate")),
        "answer_quality_product_source_type_match_rate": _float(payload.get("product_source_type_match_rate")),
        "calls_ollama": bool(payload.get("calls_ollama", False)),
        "connects_pgvector": bool(payload.get("connects_pgvector", False)),
        "calls_llm": bool(payload.get("calls_llm", False)),
    }


def _normalize_answer_quality_profile(profile: str, *, enabled: bool, real: bool) -> str:
    value = str(profile or "").strip()
    if value:
        return value
    if not enabled:
        return "skipped"
    return "real_full" if real else "fake_mandatory"


def _product_coverage_qa(
    *,
    enabled: bool,
    real: bool,
    product_db_path: Path | str | None,
    shop_id: str,
    product_version: str,
    product_domain: str,
    limit: int,
    min_hit_rate: float,
    min_field_rate: float,
    pg_dsn: str,
    ollama_base_url: str,
    embedding_model: str,
) -> dict[str, Any]:
    if not enabled:
        return {
            "product_coverage_status": "skipped",
            "product_coverage_total": 0,
            "product_coverage_passed": 0,
            "product_coverage_failed": 0,
            "product_coverage_hit_rate": 0.0,
            "product_coverage_field_rate": 0.0,
            "product_coverage_source_type_match_rate": 0.0,
            "product_coverage_version_match_rate": 0.0,
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    payload = internal_product_coverage_qa.run_qa(
        argparse.Namespace(
            product_db_path=Path(product_db_path) if product_db_path else Path("temp/missing.db"),
            from_product_db=bool(real),
            shop_id=shop_id,
            limit=max(1, int(limit or 50)),
            real_rag=real,
            pg_dsn=pg_dsn,
            ollama_base_url=ollama_base_url,
            embedding_model=embedding_model or "bge-m3",
            embedding_dimension=1024,
            product_version=product_version or "real-product-v1",
            product_domain=product_domain or "product_catalog",
            case_id="",
            expected_min_hit_rate=float(min_hit_rate),
            expected_min_field_coverage_rate=float(min_field_rate),
            json_only=True,
        )
    )
    status = _text(payload.get("status"))
    return {
        "product_coverage_status": status,
        "product_coverage_total": _int(payload.get("total")),
        "product_coverage_passed": _int(payload.get("passed")),
        "product_coverage_failed": _int(payload.get("failed")),
        "product_coverage_hit_rate": _float(payload.get("hit_rate")),
        "product_coverage_field_rate": _float(payload.get("field_coverage_rate")),
        "product_coverage_source_type_match_rate": _float(payload.get("source_type_match_rate")),
        "product_coverage_version_match_rate": _float(payload.get("version_match_rate")),
        "calls_ollama": bool(payload.get("calls_ollama", False)),
        "connects_pgvector": bool(payload.get("connects_pgvector", False)),
    }


def _manual_labeling_pack(
    *,
    enabled: bool,
    conversation_db_path: Path | str | None,
    shop_id: str | Sequence[str],
    output_dir: Path | str | None,
    profile: str,
) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "skipped",
            "candidate_count": 0,
            "selected_by_domain": {},
            "calls_llm": False,
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    shop_ids = [str(item) for item in shop_id] if isinstance(shop_id, (list, tuple)) else [str(shop_id or DRY_RUN_EXAMPLE_SHOP_ID)]
    args = argparse.Namespace(
        conversation_db_path=Path(conversation_db_path) if conversation_db_path else None,
        shop_id=shop_ids,
        output_dir=Path(output_dir) if output_dir else REPO_ROOT / "temp" / "manual_labeling" / "gate-pack",
        allow_custom_output_dir=False,
        max_scan=1000,
        max_per_domain=50,
        include_pending_human=True,
        include_unclassified=True,
        preview_max_chars=80,
        domain=[],
        manual_labeling_profile=profile or "broad",
        json_only=True,
    )
    return internal_manual_labeling_pack.run(args)


def _label_benchmark(
    *,
    enabled: bool,
    label_input: Path | str | None,
    benchmark_output: Path | str | None,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "skipped", "benchmark_case_count": 0}
    args = argparse.Namespace(
        build_benchmark_from_labels=True,
        label_input=Path(label_input) if label_input else None,
        benchmark_output=Path(benchmark_output) if benchmark_output else None,
        include_status="approved",
        include_domain=[],
        max_per_domain=10,
        min_per_domain=0,
        allow_missing_domain=True,
        json_only=True,
    )
    return internal_replay_benchmark.build_benchmark_from_labels(args)


def _conversation_replay(
    *,
    enabled: bool,
    real: bool,
    conversation_db_path: Path | str | None,
    shop_id: str,
    buyer_id: str,
    session_id: str,
    limit: int,
    min_pass_rate: float,
    max_failures: int,
    allow_unclear_rate: float,
    answerable_only: bool,
    answerable_domain: str,
    answerable_max_per_domain: int,
    answerable_min_pass_rate: float,
    answerable_max_unclear_rate: float,
    answerable_require_no_failures: bool,
    answerable_require_rag_hit: bool,
    answerable_require_answer_generated: bool,
    selector_audit: bool,
    selector_audit_only: bool,
    require_min_shops: int,
    require_min_domains: int,
    require_domain_coverage: bool,
    per_shop_limit: int,
    per_domain_limit: int,
    allow_empty_shop: bool,
    generate_candidate_pool: bool,
    candidate_output: Path | str | None,
    benchmark_file: Path | str | None,
    benchmark_enabled: bool,
    benchmark_min_pass_rate: float,
    benchmark_max_unclear_rate: float,
    pending_human_audit: bool,
    pg_dsn: str,
    ollama_base_url: str,
    embedding_model: str,
    llm_base_url: str,
    llm_model: str,
    llm_api_key_env: str,
    product_version: str,
    sop_version: str,
) -> dict[str, Any]:
    if not enabled:
        return {
            "conversation_replay_status": "skipped",
            "conversation_replay_total": 0,
            "conversation_replay_passed": 0,
            "conversation_replay_failed": 0,
            "conversation_replay_unclear": 0,
            "conversation_replay_pass_rate": 0.0,
            "conversation_replay_rag_hit_rate": 0.0,
            "conversation_replay_guardrail_blocked_count": 0,
            "conversation_replay_transfer_human_count": 0,
            "answerable_replay_status": "skipped",
            "answerable_replay_total": 0,
            "answerable_replay_passed": 0,
            "answerable_replay_failed": 0,
            "answerable_replay_unclear": 0,
            "answerable_replay_pass_rate": 0.0,
            "answerable_replay_rag_hit_rate": 0.0,
            "answerable_replay_answer_generated_rate": 0.0,
            "answerable_selector_scanned_total": 0,
            "answerable_selector_candidate_total": 0,
            "answerable_selector_selected_total": 0,
            "answerable_selector_excluded_by_reason": {},
            "answerable_selector_selected_by_domain": {},
            "answerable_replay_shops_total": 0,
            "answerable_replay_shops_with_candidates": 0,
            "answerable_replay_domain_coverage_status": "skipped",
            "answerable_replay_domains_missing": [],
            "answerable_replay_unclear_reason_counts": {},
            "answerable_replay_rag_miss_reason_counts": {},
            "replay_candidate_total": 0,
            "replay_candidate_selected_by_domain": {},
            "replay_candidate_excluded_by_reason": {},
            "replay_benchmark_case_count": 0,
            "replay_benchmark_pass_rate": 0.0,
            "replay_benchmark_unclear_rate": 0.0,
            "pending_human_answerable_candidates": 0,
            "calls_llm": False,
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    payload = internal_conversation_replay.run_replay(
        argparse.Namespace(
            conversation_db_path=Path(conversation_db_path) if conversation_db_path else None,
            shop_id=shop_id if shop_id else DRY_RUN_EXAMPLE_SHOP_ID,
            shop_ids="",
            buyer_id=str(buyer_id or ""),
            session_id=str(session_id or ""),
            limit=max(1, int(limit or 10)),
            since="",
            until="",
            real_rag=bool(real),
            real_llm=bool(real),
            pg_dsn=pg_dsn,
            ollama_base_url=ollama_base_url,
            embedding_model=embedding_model or "bge-m3",
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_api_key_env=llm_api_key_env,
            llm_timeout_seconds=20.0,
            product_version=product_version or "real-product-v1",
            sop_version=sop_version or "sop-test-v1",
            top_k=3,
            json_only=True,
            max_messages=max(0, int(limit or 10)),
            include_pending_human=False,
            exclude_pending_human=False,
            answerable_only=bool(answerable_only),
            answerable_domain=str(answerable_domain or ""),
            answerable_max_per_domain=max(1, int(answerable_max_per_domain or 3)),
            answerable_min_message_length=2,
            answerable_keyword_profile="default",
            exclude_short_acks=True,
            exclude_system_like=True,
            exclude_media_only=True,
            include_redline=bool(answerable_only),
            include_sensitive=bool(answerable_only),
            require_answerable_rag_hit=bool(answerable_require_rag_hit),
            require_answer_generated=bool(answerable_require_answer_generated),
            allow_transfer_for_redline=True,
            allow_request_evidence_for_after_sales=True,
            answerable_min_pass_rate=float(answerable_min_pass_rate or 0.8),
            answerable_max_unclear_rate=float(answerable_max_unclear_rate or 0.3),
            answerable_require_no_failures=bool(answerable_require_no_failures),
            selector_audit=bool(selector_audit),
            selector_audit_only=bool(selector_audit_only),
            selector_audit_include_pending_human=False,
            selector_audit_max_scan=0,
            selector_audit_domain=str(answerable_domain or ""),
            selector_audit_shop_id=[],
            selector_audit_output_samples=False,
            max_shops=0,
            per_shop_limit=max(0, int(per_shop_limit or 0)),
            per_domain_limit=max(0, int(per_domain_limit or 0)),
            require_min_domains=max(0, int(require_min_domains or 0)),
            require_min_shops=max(0, int(require_min_shops or 0)),
            allow_empty_shop=bool(allow_empty_shop),
            shop_product_version_map="",
            shop_sop_version_map="",
            baseline_domains="product_basic,logistics_policy,after_sales_evidence,promotion_policy,redline_escalation,sensitive_user_safety",
            min_cases_per_domain=0,
            max_cases_per_domain=max(0, int(per_domain_limit or 0)),
            require_domain_coverage=bool(require_domain_coverage),
            generate_candidate_pool=bool(generate_candidate_pool),
            candidate_output=Path(candidate_output) if candidate_output else None,
            candidate_max_scan=0,
            candidate_per_shop_limit=0,
            candidate_per_domain_limit=max(0, int(per_domain_limit or 0)),
            candidate_include_pending_human=False,
            candidate_include_unclassified=False,
            candidate_min_message_length=0,
            candidate_shop_id=[],
            candidate_domain=[],
            benchmark_file=Path(benchmark_file) if benchmark_file else None,
            benchmark_version="",
            benchmark_case_id=[],
            benchmark_domain=[],
            benchmark_max_cases=0,
            benchmark_require_rag=False,
            benchmark_require_answer=False,
            pending_human_audit=bool(pending_human_audit),
            pending_human_audit_only=bool(pending_human_audit) and not (answerable_only or benchmark_enabled),
            pending_human_domain="",
            pending_human_max_scan=0,
        )
    )
    status = _text(payload.get("status"))
    pass_rate = _float(payload.get("pass_rate"))
    failed = _int(payload.get("failed"))
    unclear_rate = _float(payload.get("unclear_rate"))
    replay_status = status
    if status == "error":
        replay_status = "error"
    elif (generate_candidate_pool or pending_human_audit) and not benchmark_enabled and not answerable_only:
        replay_status = "passed"
    elif failed > int(max_failures or 0):
        replay_status = "failed"
    elif pass_rate < float(min_pass_rate):
        replay_status = "failed"
    elif unclear_rate > float(allow_unclear_rate):
        replay_status = "failed"
    elif status in {"passed", "completed"}:
        replay_status = "passed"
    benchmark_status = "skipped"
    if benchmark_enabled:
        benchmark_status = "passed"
        if _int(payload.get("benchmark_failed")) > 0:
            benchmark_status = "failed"
        elif _float(payload.get("benchmark_pass_rate")) < float(benchmark_min_pass_rate or 0.8):
            benchmark_status = "failed"
        elif _rate(_int(payload.get("benchmark_unclear")), max(1, _int(payload.get("benchmark_case_count")))) > float(benchmark_max_unclear_rate or 0.3):
            benchmark_status = "failed"
    if benchmark_status == "failed":
        replay_status = "failed"
    answerable_status = "skipped"
    if answerable_only:
        answerable_status = _text(payload.get("status"))
        if answerable_status in {"passed", "completed"}:
            answerable_status = "passed"
    return {
        "conversation_replay_status": replay_status,
        "conversation_replay_total": _int(payload.get("total")),
        "conversation_replay_passed": _int(payload.get("passed")),
        "conversation_replay_failed": _int(payload.get("failed")),
        "conversation_replay_unclear": _int(payload.get("unclear")),
        "conversation_replay_pass_rate": pass_rate,
        "conversation_replay_rag_hit_rate": _float(payload.get("rag_hit_rate")),
        "conversation_replay_guardrail_blocked_count": _int(payload.get("guardrail_blocked_count")),
        "conversation_replay_transfer_human_count": _int(payload.get("transfer_human_count")),
        "answerable_replay_status": answerable_status,
        "answerable_replay_total": _int(payload.get("answerable_total")),
        "answerable_replay_passed": _int(payload.get("answerable_passed")),
        "answerable_replay_failed": _int(payload.get("answerable_failed")),
        "answerable_replay_unclear": _int(payload.get("answerable_unclear")),
        "answerable_replay_pass_rate": _float(payload.get("answerable_pass_rate")),
        "answerable_replay_rag_hit_rate": _float(payload.get("answerable_rag_hit_rate")),
        "answerable_replay_answer_generated_rate": _float(payload.get("answerable_answer_generated_rate")),
        "answerable_selector_scanned_total": _int(payload.get("scanned_total")),
        "answerable_selector_candidate_total": _int(payload.get("candidate_total")),
        "answerable_selector_selected_total": _int(payload.get("selected_total")),
        "answerable_selector_excluded_by_reason": dict(payload.get("excluded_by_reason") or {}),
        "answerable_selector_selected_by_domain": dict(payload.get("selected_by_domain") or {}),
        "answerable_replay_shops_total": _int(payload.get("shops_total")),
        "answerable_replay_shops_with_candidates": _int(payload.get("shops_with_candidates")),
        "answerable_replay_domain_coverage_status": _text(payload.get("domain_coverage_status")),
        "answerable_replay_domains_missing": list(payload.get("domains_missing") or []),
        "answerable_replay_unclear_reason_counts": dict(payload.get("unclear_reason_counts") or {}),
        "answerable_replay_rag_miss_reason_counts": dict(payload.get("rag_miss_reason_counts") or {}),
        "replay_candidate_total": _int(payload.get("candidate_total")),
        "replay_candidate_selected_by_domain": dict(payload.get("selected_by_domain") or {}),
        "replay_candidate_excluded_by_reason": dict(payload.get("excluded_by_reason") or {}),
        "replay_benchmark_case_count": _int(payload.get("benchmark_case_count")),
        "replay_benchmark_pass_rate": _float(payload.get("benchmark_pass_rate")),
        "replay_benchmark_unclear_rate": _rate(_int(payload.get("benchmark_unclear")), max(1, _int(payload.get("benchmark_case_count")))),
        "replay_benchmark_status": benchmark_status,
        "pending_human_answerable_candidates": _int(payload.get("pending_human_answerable_candidates")),
        "calls_llm": bool(payload.get("calls_llm", False)),
        "calls_ollama": bool(payload.get("calls_ollama", False)),
        "connects_pgvector": bool(payload.get("connects_pgvector", False)),
    }


def _rag_cleanup(
    *,
    enabled: bool,
    real: bool,
    pg_dsn: str,
    dry_run: bool,
    source_type_prefix: str,
    namespace: str,
) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "skipped",
            "dry_run": True,
            "connects_pgvector": False,
            "matched_count": 0,
            "deleted_count": 0,
            "error_type": "",
        }
    args = argparse.Namespace(
        fake=not real,
        pg_dsn=pg_dsn,
        shop_id="",
        domain="",
        version="",
        index_run_id="",
        namespace=namespace,
        source_type_prefix=source_type_prefix,
        dry_run=dry_run,
        confirm_delete=not dry_run,
        json_only=True,
    )
    return internal_rag_cleanup.run_cleanup(args)


def _legacy_audit(*, enabled: bool, real: bool, pg_dsn: str) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "skipped",
            "connects_pgvector": False,
            "legacy_candidate_count": 0,
            "legacy_source_types": [],
            "legacy_versions": [],
            "legacy_domains": [],
            "legacy_shop_ids_hash": [],
            "has_non_pollution_candidates": False,
            "error_type": "",
        }
    args = argparse.Namespace(
        fake=not real,
        pg_dsn=pg_dsn,
        audit_legacy_pollution=True,
        legacy_cleanup=False,
        legacy_confirm_delete=False,
        legacy_source_type_prefix="pollution_",
        legacy_shop_id="synthetic-shop-1",
        legacy_wrong_shop_id="synthetic-shop-2",
        legacy_version="old-version",
        legacy_domain="",
        legacy_dry_run=True,
        source_type_prefix="pollution_",
        namespace="acceptance",
        shop_id="",
        domain="",
        version="",
        index_run_id="",
        dry_run=True,
        confirm_delete=False,
        json_only=True,
    )
    return internal_rag_cleanup.run_cleanup(args)


def _legacy_cleanup(
    *,
    enabled: bool,
    real: bool,
    pg_dsn: str,
    confirm_delete: bool,
    version: str,
    shop_id: str,
    domain: str,
) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "skipped",
            "dry_run": True,
            "legacy_cleanup": False,
            "connects_pgvector": False,
            "matched_count": 0,
            "deleted_count": 0,
            "error_type": "",
        }
    args = argparse.Namespace(
        fake=not real,
        pg_dsn=pg_dsn,
        audit_legacy_pollution=False,
        legacy_cleanup=True,
        legacy_confirm_delete=confirm_delete,
        legacy_source_type_prefix="pollution_",
        legacy_shop_id=shop_id,
        legacy_wrong_shop_id="",
        legacy_version=version,
        legacy_domain=domain,
        legacy_dry_run=not confirm_delete,
        source_type_prefix="pollution_",
        namespace="acceptance",
        shop_id="",
        domain="",
        version="",
        index_run_id="",
        dry_run=True,
        confirm_delete=False,
        json_only=True,
    )
    return internal_rag_cleanup.run_cleanup(args)


def _legacy_cleanup_status(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    statuses = [_text(before.get("status")), _text(after.get("status"))]
    active = [status for status in statuses if status and status != "skipped"]
    if not active:
        return "skipped"
    if any(status in {"error", "rejected"} for status in active):
        return "failed"
    return active[-1]


def _missing_real_rag_error(pg_dsn: str, ollama_base_url: str, embedding_model: str) -> str:
    missing = []
    if not pg_dsn:
        missing.append("pg_dsn")
    if not ollama_base_url:
        missing.append("ollama_base_url")
    if not embedding_model:
        missing.append("embedding_model")
    return "missing_" + "_".join(missing)


def _dry_run_error_summary(args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    return {
        **internal_backend_dry_run.base_summary(args),
        "dry_run": False,
        "action": "fallback",
        "intent": "",
        "reason": "rag_engine_config_error",
        "risk_flags": ["rag_engine_config_error"],
        "workflow_version": "internal-v1",
        "sop_version": None,
        "knowledge_version": None,
        "knowledge_hit_count": 0,
        "knowledge_source": "",
        "guardrail_status": "",
        "answer_generator": "",
        "answer_generation_source": "",
        "answer_generation_status": "failed_config",
        "answer_confidence": 0.0,
        "answer_length": 0,
        "answer_hash": "",
        "answer_preview_truncated": "",
        "used_history_count": 0,
        "used_rag_hit_count": 0,
        "prompt_hash": "",
        "calls_llm": False,
        "rag_enabled": bool(getattr(args, "use_real_rag", False)),
        "rag_status": f"error:{type(exc).__name__}",
        "rag_hit_count": 0,
        "rag_domains": [],
        "rag_top_score": 0.0,
        "rag_version_pinned": bool(getattr(args, "rag_version", "")),
        "rag_expected_version": str(getattr(args, "expect_rag_version", "") or ""),
        "rag_hit_versions": [],
        "rag_version_status": "failed_missing_version" if getattr(args, "require_rag_version", False) else "not_required",
        "rag_shop_status": "not_required",
        "rag_source_type_status": "not_required",
        "rag_hit_content_hashes": [],
        "rag_hit_source_types": [],
        "rag_hit_source_ids_hash": [],
        "vector_store": "pgvector" if getattr(args, "use_real_rag", False) else "",
        "embedding_model": str(getattr(args, "embedding_model", "") or ""),
        "retrieval_source": "",
        "calls_ollama": False,
        "connects_pgvector": False,
        "rag_e2e_profile": bool(getattr(args, "rag_e2e_profile", False)),
        "rag_e2e_status": "failed" if getattr(args, "rag_e2e_profile", False) else "ok",
        "rag_required": bool(getattr(args, "require_rag_hit", False)),
        "rag_requirement_status": "failed_no_hit" if getattr(args, "require_rag_hit", False) else "not_required",
        "answer_generator_required": str(getattr(args, "expect_answer_generator", "") or ""),
        "answer_generation_status": "failed_config"
        if getattr(args, "use_real_answer_generator", False)
        else ("failed" if getattr(args, "expect_answer_generator", "") else "not_required"),
        "guardrail_required": bool(getattr(args, "expect_guardrail_status", "")),
        "guardrail_requirement_status": "failed" if getattr(args, "expect_guardrail_status", "") else "not_required",
        "errors": [_sanitize_error(str(exc))],
    }


def _real_rag_smoke(
    sop_file: Path | str | None,
    *,
    pg_dsn: str,
    ollama_base_url: str,
    embedding_model: str,
) -> dict[str, Any]:
    if not pg_dsn:
        return {
            "rag_status": "error",
            "rag_real_status": "missing_pg_dsn",
            "ollama_status": "not_run",
            "pgvector_status": "not_run",
            "vector_store": "pgvector",
            "embedding_model": embedding_model,
            "chunk_count": 0,
            "retrieval_hit_count": 0,
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    embed_payload, embed_code = internal_rag_embedding_smoke.run_smoke(
        argparse.Namespace(
            provider="ollama",
            base_url=ollama_base_url,
            model=embedding_model,
            text="synthetic rag real smoke text",
            dimension=None,
            timeout=15.0,
            json_only=True,
        )
    )
    pg_payload, pg_code = internal_pgvector_smoke.run_smoke(
        argparse.Namespace(
            fake=False,
            pg_dsn=pg_dsn,
            apply_schema=False,
            check_only=True,
            schema_path=internal_pgvector_smoke.DEFAULT_SCHEMA,
            json_only=True,
        )
    )
    if embed_code or pg_code:
        return {
            "rag_status": "error",
            "rag_real_status": "error",
            "ollama_status": _text(embed_payload.get("status")),
            "pgvector_status": _text(pg_payload.get("status")),
            "vector_store": "pgvector",
            "embedding_model": embedding_model,
            "chunk_count": 0,
            "retrieval_hit_count": 0,
            "calls_ollama": bool(embed_payload.get("calls_ollama", True)),
            "connects_pgvector": bool(pg_payload.get("connects_pgvector", True)),
        }
    sop_path = Path(sop_file) if sop_file else REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"
    index_args = argparse.Namespace(
        shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        domain=[],
        sop_file=sop_path,
        dry_run=False,
        json_only=True,
        output_json=None,
        pg_dsn=pg_dsn,
        apply_schema=False,
        embedding_provider="ollama",
        embedding_model=embedding_model,
        ollama_base_url=ollama_base_url,
        embedding_dimension=1024,
        real=True,
    )
    retrieve_args = argparse.Namespace(
        shop_id=DRY_RUN_EXAMPLE_SHOP_ID,
        domain="logistics_policy",
        query="why has it not arrived",
        top_k=3,
        sop_file=sop_path,
        json_only=True,
        pg_dsn=pg_dsn,
        embedding_provider="ollama",
        embedding_model=embedding_model,
        ollama_base_url=ollama_base_url,
        embedding_dimension=1024,
        real=True,
    )
    indexed = internal_rag_index.run_index(index_args)
    retrieved = internal_rag_retrieve.run_retrieve(retrieve_args)
    return {
        "rag_status": "ok" if indexed.get("status") == "ok" and retrieved.get("status") == "ok" else "error",
        "rag_real_status": "ok" if indexed.get("status") == "ok" and retrieved.get("status") == "ok" else "error",
        "ollama_status": "ok",
        "pgvector_status": "ok",
        "vector_store": "pgvector",
        "embedding_model": embedding_model,
        "chunk_count": _int(indexed.get("chunk_count")),
        "retrieval_hit_count": _int(retrieved.get("hit_count")),
        "calls_ollama": True,
        "connects_pgvector": True,
    }


def _sanitize_command(command: Sequence[str] | None) -> list[str]:
    sanitized: list[str] = []
    mask_next = False
    for value in list(command or []):
        if mask_next:
            sanitized.append("<masked>")
            mask_next = False
            continue
        sanitized.append(value)
        if value == "--pg-dsn":
            mask_next = True
    return sanitized


def _sanitize_error(message: str) -> str:
    text = str(message or "")
    if "postgresql://" in text:
        return "configuration error"
    return text


def _canonical_report(
    *,
    report_type: str,
    generated_at: str,
    sop_version: str,
    knowledge_version: str,
    shop_id_hash: str,
    passed: int,
    failed: int,
    unclear: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "report_type": report_type,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "backend": "internal",
        "workflow_version": _top_text(results, "workflow_version") or "internal-v1",
        "sop_version": sop_version,
        "knowledge_version": knowledge_version,
        "shop_id_hash": shop_id_hash,
        "case_count": len(results),
        "passed": passed,
        "failed": failed,
        "unclear": unclear,
        "results": results,
    }


def _canonical_result(row: Mapping[str, Any]) -> dict[str, Any]:
    status = _text(row.get("status") or row.get("verdict") or "passed")
    return {
        "case_id": _text(row.get("case_id")),
        "category": _text(row.get("category")),
        "priority": _text(row.get("priority")),
        "action": _text(row.get("action") or row.get("actual_action") or row.get("internal_action")),
        "intent": _text(row.get("intent") or row.get("actual_intent") or row.get("internal_intent")),
        "reason": _text(row.get("actual_reason") or row.get("reason")),
        "risk_flags": list(row.get("risk_flags") or []),
        "knowledge_source": _text(row.get("knowledge_source")),
        "knowledge_hit_count": _int(row.get("knowledge_hit_count")),
        "sop_domain": _text(row.get("sop_domain")),
        "sop_version": _text(row.get("sop_version")),
        "knowledge_version": _text(row.get("knowledge_version")),
        "workflow_version": _text(row.get("workflow_version")) or "internal-v1",
        "guardrail_status": _text(row.get("guardrail_status")),
        "answer_generator": _text(row.get("answer_generator")),
        "answer_generation_source": _text(row.get("answer_generation_source")),
        "answer_generation_status": _text(row.get("answer_generation_status")) or _text(row.get("llm_answer_status")),
        "answer_confidence": _float(row.get("answer_confidence")),
        "answer_length": _int(row.get("answer_length")),
        "answer_hash": _text(row.get("answer_hash")),
        "answer_preview_truncated": _text(row.get("answer_preview_truncated")),
        "used_history_count": _int(row.get("used_history_count")),
        "used_rag_hit_count": _int(row.get("used_rag_hit_count")),
        "prompt_hash": _text(row.get("prompt_hash")),
        "calls_llm": bool(row.get("calls_llm", False)),
        "rag_enabled": bool(row.get("rag_enabled", False)),
        "rag_status": _text(row.get("rag_status")),
        "rag_hit_count": _int(row.get("rag_hit_count")),
        "rag_domains": list(row.get("rag_domains") or []),
        "rag_top_score": _float(row.get("rag_top_score")),
        "rag_version_pinned": bool(row.get("rag_version_pinned", False)),
        "rag_expected_version": _text(row.get("rag_expected_version")),
        "rag_hit_versions": list(row.get("rag_hit_versions") or []),
        "rag_version_status": _text(row.get("rag_version_status")),
        "rag_shop_status": _text(row.get("rag_shop_status")),
        "rag_source_type_status": _text(row.get("rag_source_type_status")),
        "rag_hit_content_hashes": list(row.get("rag_hit_content_hashes") or []),
        "rag_hit_source_types": list(row.get("rag_hit_source_types") or []),
        "rag_hit_source_ids_hash": list(row.get("rag_hit_source_ids_hash") or []),
        "retrieval_source": _text(row.get("retrieval_source")),
        "calls_ollama": bool(row.get("calls_ollama", False)),
        "connects_pgvector": bool(row.get("connects_pgvector", False)),
        "rag_e2e_profile": bool(row.get("rag_e2e_profile", False)),
        "rag_e2e_status": _text(row.get("rag_e2e_status")),
        "rag_required": bool(row.get("rag_required", False)),
        "rag_requirement_status": _text(row.get("rag_requirement_status")),
        "answer_generator_required": _text(row.get("answer_generator_required")),
        "answer_generation_status": _text(row.get("answer_generation_status")),
        "guardrail_required": bool(row.get("guardrail_required", False)),
        "guardrail_requirement_status": _text(row.get("guardrail_requirement_status")),
        "verdict": status,
        "errors": list(row.get("failures") or row.get("errors") or []),
    }


def _top_knowledge_version(rows: Sequence[Mapping[str, Any]]) -> str:
    return _top_text(rows, "knowledge_version")


def _top_text(rows: Sequence[Mapping[str, Any]], field: str) -> str:
    for row in rows:
        value = _text(row.get(field))
        if value:
            return value
    return ""


def _first(value: object) -> str:
    if isinstance(value, list) and value:
        return _text(value[0])
    return _text(value)


def _result_value(report: Mapping[str, Any], field: str) -> object:
    results = report.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, Mapping):
            return first.get(field)
    return ""


def _text(value: object) -> str:
    return str(value or "").strip()


def _int(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _rate(numerator: int, denominator: int) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def _short_hash(value: object) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
