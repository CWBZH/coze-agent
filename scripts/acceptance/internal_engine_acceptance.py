"""One-command no-send acceptance runner for the internal workflow engine."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.acceptance import internal_engine_synthetic_qa
from scripts.acceptance.internal_acceptance_artifacts import (
    DRY_RUN_EXAMPLE_MESSAGE,
    DRY_RUN_EXAMPLE_SHOP_ID,
    build_artifacts,
    build_path_plan,
)
from scripts.acceptance.internal_report_schema import validate_report_schema


DEFAULT_SOP_FILE = Path("docs/acceptance/fixtures/internal_sop_example.md")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one-command no-send acceptance for InternalWorkflowEngine."
    )
    parser.add_argument(
        "--sop-file",
        type=Path,
        default=DEFAULT_SOP_FILE,
        help="Reviewed SOP Markdown fixture.",
    )
    parser.add_argument(
        "--artifact-dir",
        "--output-dir",
        dest="artifact_dir",
        type=Path,
        help="Artifact directory. Defaults under temp/acceptance/internal-engine.",
    )
    parser.add_argument("--json-only", action="store_true", help="Print only JSON.")
    parser.add_argument("--dry-run", action="store_true", help="List the plan without executing engines.")
    parser.add_argument("--no-write", action="store_true", help="Do not write artifact files.")
    parser.add_argument("--conversation-db-path", type=Path, help="Optional read-only conversation DB smoke path.")
    parser.add_argument("--skip-conversation-smoke", action="store_true", help="Do not run optional conversation DB smoke.")
    parser.add_argument("--require-conversation-db", action="store_true", help="Fail if the optional conversation DB is missing.")
    parser.add_argument("--use-fake-answer-generator", action="store_true", help="Use offline fake answer generator.")
    parser.add_argument("--skip-rag-smoke", action="store_true", help="Skip fake RAG smoke.")
    parser.add_argument("--rag-smoke", action="store_true", help="Run fake RAG smoke; enabled by default.")
    parser.add_argument("--rag-smoke-real", action="store_true", help="Run explicit real Ollama + pgvector smoke.")
    parser.add_argument("--rag-engine-real", action="store_true", help="Run explicit real RAG retriever through InternalWorkflowEngine.")
    parser.add_argument("--rag-e2e-profile", action="store_true", help="Run internal RAG answer-generation E2E profile.")
    parser.add_argument("--require-rag-hit", action="store_true", help="Require RAG hit in E2E profile.")
    parser.add_argument("--expect-rag-domain", default="", help="Expected RAG domain for E2E profile.")
    parser.add_argument("--expect-rag-version", default="", help="Expected RAG version for E2E profile.")
    parser.add_argument("--require-rag-version", action="store_true", help="Require matching RAG hit versions.")
    parser.add_argument("--expect-rag-source-type", default="", help="Expected RAG source_type for E2E profile.")
    parser.add_argument("--expect-answer-generator", default="", help="Expected answer generator for E2E profile.")
    parser.add_argument("--fake-answer-dangerous", action="store_true", help="Use risky fake draft for guardrail E2E profile.")
    parser.add_argument("--expect-guardrail-blocked", action="store_true", help="Require guardrail_status=blocked.")
    parser.add_argument("--pg-dsn", default="", help="PostgreSQL/pgvector DSN for explicit real RAG smoke.")
    parser.add_argument("--ollama-base-url", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--rag-domain", default="logistics_policy")
    parser.add_argument("--rag-version", default="")
    parser.add_argument("--rag-query", default="\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230")
    parser.add_argument("--rag-retrieval-qa", action="store_true", help="Run fake retrieval-only RAG QA.")
    parser.add_argument("--rag-retrieval-qa-real", action="store_true", help="Run real retrieval-only RAG QA.")
    parser.add_argument("--rag-qa-version", default="sop-test-v1")
    parser.add_argument("--rag-qa-domain", default="")
    parser.add_argument("--rag-qa-case-id", default="")
    parser.add_argument("--rag-release-gate", action="store_true", help="Run version-pinned RAG release gate.")
    parser.add_argument("--rag-release-real", action="store_true", help="Release gate must use real Ollama + pgvector.")
    parser.add_argument("--rag-release-version", default="sop-test-v1")
    parser.add_argument("--rag-release-shop-id", default=DRY_RUN_EXAMPLE_SHOP_ID)
    parser.add_argument("--rag-release-min-hit-rate", type=float, default=0.9)
    parser.add_argument("--rag-release-min-domain-match-rate", type=float, default=0.9)
    parser.add_argument("--rag-release-require-version-match", action="store_true")
    parser.add_argument("--rag-release-require-no-cross-shop", action="store_true")
    parser.add_argument("--rag-release-require-no-cross-domain", action="store_true")
    parser.add_argument("--rag-release-run-pollution-tests", action="store_true")
    parser.add_argument("--cleanup-rag-pollution-before", action="store_true")
    parser.add_argument("--cleanup-rag-pollution-after", action="store_true")
    parser.add_argument("--rag-cleanup-dry-run", action="store_true", default=True)
    parser.add_argument("--rag-cleanup-source-type-prefix", default="pollution_")
    parser.add_argument("--rag-cleanup-namespace", default="acceptance")
    parser.add_argument("--audit-rag-legacy-pollution", action="store_true")
    parser.add_argument("--require-no-rag-legacy-pollution", action="store_true")
    parser.add_argument("--cleanup-rag-legacy-pollution-before", action="store_true")
    parser.add_argument("--cleanup-rag-legacy-pollution-after", action="store_true")
    parser.add_argument("--legacy-cleanup-confirm-delete", action="store_true")
    parser.add_argument("--legacy-cleanup-version", default="")
    parser.add_argument("--legacy-cleanup-shop-id", default="")
    parser.add_argument("--legacy-cleanup-domain", default="")
    parser.add_argument("--llm-answer-real", action="store_true", help="Run explicit no-send real LLM answer profile.")
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--llm-api-key-env", default="AI_WORKFLOW_LLM_API_KEY")
    parser.add_argument("--llm-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--require-answer-generated", action="store_true")
    parser.add_argument("--expect-guardrail-status", default="")
    parser.add_argument("--answer-quality-qa", action="store_true", help="Run answer quality QA.")
    parser.add_argument("--answer-quality-real", action="store_true", help="Run answer quality QA with real RAG + real LLM.")
    parser.add_argument("--answer-quality-profile", choices=["fake_mandatory", "real_smoke", "real_full"], default="")
    parser.add_argument("--answer-quality-real-full", action="store_true")
    parser.add_argument("--answer-quality-real-smoke", action="store_true")
    parser.add_argument("--answer-quality-smoke-max-cases", type=int, default=10)
    parser.add_argument("--answer-quality-release-min-pass-rate", type=float, default=0.9)
    parser.add_argument("--answer-quality-release-require-no-p0", action="store_true")
    parser.add_argument("--answer-quality-release-require-no-forbidden", action="store_true")
    parser.add_argument("--answer-quality-release-require-source-type-match", action="store_true")
    parser.add_argument("--answer-quality-domain", default="")
    parser.add_argument("--answer-quality-case-id", default="")
    parser.add_argument("--answer-quality-max-cases", type=int, default=0)
    parser.add_argument("--answer-quality-product-version", default="")
    parser.add_argument("--answer-quality-min-pass-rate", type=float, default=0.9)
    parser.add_argument("--answer-quality-allow-preview", action="store_true", default=True)
    parser.add_argument("--answer-quality-require-no-p0-failures", action="store_true", default=True)
    parser.add_argument("--product-coverage-qa", action="store_true", help="Run fake product RAG coverage QA.")
    parser.add_argument("--product-coverage-real", action="store_true", help="Run product RAG coverage QA with SQLite + real RAG.")
    parser.add_argument("--product-db-path", type=Path, default=Path("temp/missing.db"))
    parser.add_argument("--shop-id", default="", help="Shop id for product coverage QA.")
    parser.add_argument("--product-version", default="real-product-v1")
    parser.add_argument("--product-domain", default="product_catalog")
    parser.add_argument("--product-coverage-limit", type=int, default=50)
    parser.add_argument("--product-coverage-min-hit-rate", type=float, default=0.9)
    parser.add_argument("--product-coverage-min-field-rate", type=float, default=0.8)
    parser.add_argument("--conversation-replay", action="store_true", help="Run historical conversation no-send replay.")
    parser.add_argument("--conversation-replay-real", action="store_true", help="Run conversation replay with real RAG + real LLM.")
    parser.add_argument("--conversation-shop-id", action="append", default=[])
    parser.add_argument("--conversation-buyer-id", default="")
    parser.add_argument("--conversation-session-id", default="")
    parser.add_argument("--conversation-limit", type=int, default=10)
    parser.add_argument("--conversation-min-pass-rate", type=float, default=0.8)
    parser.add_argument("--conversation-max-failures", type=int, default=0)
    parser.add_argument("--conversation-allow-unclear-rate", type=float, default=0.3)
    parser.add_argument("--answerable-conversation-replay", action="store_true")
    parser.add_argument("--answerable-replay-real", action="store_true")
    parser.add_argument("--answerable-replay-domain", default="")
    parser.add_argument("--answerable-replay-max-per-domain", type=int, default=3)
    parser.add_argument("--answerable-replay-min-pass-rate", type=float, default=0.8)
    parser.add_argument("--answerable-replay-max-unclear-rate", type=float, default=0.3)
    parser.add_argument("--answerable-replay-require-no-failures", action="store_true", default=True)
    parser.add_argument("--answerable-replay-require-rag-hit", action="store_true")
    parser.add_argument("--answerable-replay-require-answer-generated", action="store_true")
    parser.add_argument("--answerable-replay-selector-audit", action="store_true")
    parser.add_argument("--answerable-replay-selector-audit-only", action="store_true")
    parser.add_argument("--answerable-replay-require-min-shops", type=int, default=0)
    parser.add_argument("--answerable-replay-require-min-domains", type=int, default=0)
    parser.add_argument("--answerable-replay-require-domain-coverage", action="store_true")
    parser.add_argument("--answerable-replay-per-shop-limit", type=int, default=0)
    parser.add_argument("--answerable-replay-per-domain-limit", type=int, default=0)
    parser.add_argument("--answerable-replay-allow-empty-shop", action="store_true")
    parser.add_argument("--replay-candidate-pool", action="store_true")
    parser.add_argument("--replay-candidate-output", type=Path)
    parser.add_argument("--replay-benchmark-file", type=Path)
    parser.add_argument("--replay-benchmark", action="store_true")
    parser.add_argument("--replay-benchmark-real", action="store_true")
    parser.add_argument("--replay-benchmark-min-pass-rate", type=float, default=0.8)
    parser.add_argument("--replay-benchmark-max-unclear-rate", type=float, default=0.3)
    parser.add_argument("--pending-human-audit", action="store_true")
    parser.add_argument("--manual-labeling-pack", action="store_true")
    parser.add_argument("--manual-labeling-output-dir", type=Path)
    parser.add_argument("--manual-labeling-profile", choices=["conservative", "balanced", "broad"], default="broad")
    parser.add_argument("--replay-label-benchmark", action="store_true")
    parser.add_argument("--label-input", type=Path)
    parser.add_argument("--label-benchmark-output", type=Path)
    return parser.parse_args(argv)


def dry_run_plan(
    *,
    sop_file: Path,
    artifact_dir: Path | None = None,
    no_write: bool = False,
    conversation_db_path: Path | None = None,
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
    fake_answer_dangerous: bool = False,
    expect_guardrail_status: str = "",
    rag_domain: str = "logistics_policy",
    rag_version: str = "",
    rag_query: str = "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
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
    product_db_path: Path | None = None,
    product_coverage_shop_id: str = "",
    product_version: str = "real-product-v1",
    product_domain: str = "product_catalog",
    product_coverage_limit: int = 50,
    product_coverage_min_hit_rate: float = 0.9,
    product_coverage_min_field_rate: float = 0.8,
    conversation_replay: bool = False,
    conversation_replay_real: bool = False,
    conversation_shop_id: str = "",
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
    synthetic_plan = internal_engine_synthetic_qa.dry_run_cases(sop_file=sop_file)
    path_plan = build_path_plan(artifact_dir)
    return {
        "runner": "internal_engine_acceptance",
        "dry_run": True,
        "summary": {
            "passed": 0,
            "failed": 0,
            "unclear": 0,
            "artifact_dir": "" if no_write else path_plan["output_dir"],
            "no_send": True,
            "calls_fastgpt": False,
            "calls_llm": False,
            "sends_pdd": False,
        },
        "plan": {
            "synthetic_cases": {
                "runner": "internal_engine_synthetic_qa",
                "case_count": synthetic_plan["summary"]["total"],
                "engine": "not_executed",
            },
            "dry_run_example": {
                "runner": "internal_backend_dry_run",
                "shop_id_hash": _short_hash(DRY_RUN_EXAMPLE_SHOP_ID),
                "message_length": len(DRY_RUN_EXAMPLE_MESSAGE),
                "message_hash": _short_hash(DRY_RUN_EXAMPLE_MESSAGE),
                "engine": "not_executed",
            },
            "comparison": {
                "runner": "compare_internal_fastgpt",
                "mode": "internal_only",
                "engine": "not_executed",
            },
            "answer_generator": "fake" if use_fake_answer_generator else "",
            "writes_artifacts": not no_write,
            "conversation_smoke": {
                "enabled": conversation_db_path is not None,
                "db_path_hash": _short_hash(str(conversation_db_path or "")) if conversation_db_path else "",
            },
            "rag_smoke": {
                "enabled": rag_smoke,
                "real": rag_smoke_real,
                "embedding_provider": "fake",
                "vector_store": "in_memory",
            },
            "rag_engine_smoke": {
                "enabled": rag_engine_real,
                "e2e_profile": rag_e2e_profile,
                "domain": rag_domain,
                "version": rag_version,
                "query_hash": _short_hash(rag_query) if rag_query else "",
                "engine": "not_executed",
            },
            "rag_retrieval_qa": {
                "enabled": rag_retrieval_qa or rag_retrieval_qa_real,
                "real": rag_retrieval_qa_real,
                "version": rag_qa_version,
                "domain": rag_qa_domain,
                "case_id": rag_qa_case_id,
            },
            "rag_release_gate": {
                "enabled": rag_release_gate,
                "real": rag_release_real,
                "version": rag_release_version,
                "shop_id_hash": _short_hash(rag_release_shop_id),
                "run_pollution_tests": rag_release_run_pollution_tests,
                "engine": "not_executed",
            },
            "rag_cleanup": {
                "before": cleanup_rag_pollution_before,
                "after": cleanup_rag_pollution_after,
                "dry_run": rag_cleanup_dry_run,
            },
            "rag_legacy_pollution": {
                "audit": audit_rag_legacy_pollution,
                "require_clean": require_no_rag_legacy_pollution,
                "cleanup_before": cleanup_rag_legacy_pollution_before,
                "cleanup_after": cleanup_rag_legacy_pollution_after,
            },
            "llm_answer": {
                "enabled": llm_answer_real,
                "model": llm_model,
                "api_key_env": llm_api_key_env if llm_answer_real else "",
                "engine": "not_executed",
            },
            "answer_quality_qa": {
                "enabled": answer_quality_qa or answer_quality_real,
                "real": answer_quality_real,
                "domain": answer_quality_domain,
                "case_id": answer_quality_case_id,
                "max_cases": answer_quality_max_cases,
                "profile": answer_quality_profile,
            },
            "product_coverage_qa": {
                "enabled": product_coverage_qa or product_coverage_real,
                "real": product_coverage_real,
                "db_path_hash": _short_hash(str(product_db_path or "")) if product_db_path else "",
                "shop_id_hash": _short_hash(product_coverage_shop_id or rag_release_shop_id),
                "version": product_version,
                "domain": product_domain,
                "limit": product_coverage_limit,
            },
            "conversation_replay": {
                "enabled": conversation_replay or conversation_replay_real or answerable_conversation_replay or answerable_replay_real,
                "real": conversation_replay_real or answerable_replay_real,
                "db_path_hash": _short_hash(str(conversation_db_path or "")) if conversation_db_path else "",
                "shop_id_hash": _short_hash(conversation_shop_id or rag_release_shop_id),
                "limit": conversation_limit,
                "answerable": answerable_conversation_replay or answerable_replay_real,
                "selector_audit": answerable_replay_selector_audit or answerable_replay_selector_audit_only,
                "answerable_domain": answerable_replay_domain,
                "answerable_max_per_domain": answerable_replay_max_per_domain,
                "require_min_shops": answerable_replay_require_min_shops,
                "require_min_domains": answerable_replay_require_min_domains,
            },
        },
        "constraints": _constraints(),
    }


def run_acceptance(
    *,
    sop_file: Path,
    artifact_dir: Path | None = None,
    no_write: bool = False,
    command: Sequence[str] | None = None,
    conversation_db_path: Path | None = None,
    require_conversation_db: bool = False,
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
    fake_answer_dangerous: bool = False,
    expect_guardrail_status: str = "",
    rag_domain: str = "logistics_policy",
    rag_version: str = "",
    rag_query: str = "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
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
    product_db_path: Path | None = None,
    product_coverage_shop_id: str = "",
    product_version: str = "real-product-v1",
    product_domain: str = "product_catalog",
    product_coverage_limit: int = 50,
    product_coverage_min_hit_rate: float = 0.9,
    product_coverage_min_field_rate: float = 0.8,
    conversation_replay: bool = False,
    conversation_replay_real: bool = False,
    conversation_shop_id: str = "",
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
    artifact_result = build_artifacts(
        output_dir=artifact_dir,
        command=command,
        no_write=no_write,
        sop_file=sop_file,
        conversation_db_path=conversation_db_path,
        use_fake_answer_generator=use_fake_answer_generator,
        rag_smoke=rag_smoke,
        rag_smoke_real=rag_smoke_real,
        rag_engine_real=rag_engine_real,
        rag_e2e_profile=rag_e2e_profile,
        require_rag_hit=require_rag_hit,
        expect_rag_domain=expect_rag_domain,
        expect_rag_version=expect_rag_version,
        require_rag_version=require_rag_version,
        expect_rag_source_type=expect_rag_source_type,
        expect_answer_generator=expect_answer_generator,
        fake_answer_dangerous=fake_answer_dangerous,
        expect_guardrail_status=expect_guardrail_status,
        rag_engine_domain=rag_domain,
        rag_version=rag_version,
        rag_engine_query=rag_query,
        pg_dsn=pg_dsn,
        ollama_base_url=ollama_base_url,
        embedding_model=embedding_model,
        rag_retrieval_qa=rag_retrieval_qa,
        rag_retrieval_qa_real=rag_retrieval_qa_real,
        rag_qa_version=rag_qa_version,
        rag_qa_domain=rag_qa_domain,
        rag_qa_case_id=rag_qa_case_id,
        rag_release_gate=rag_release_gate,
        rag_release_real=rag_release_real,
        rag_release_version=rag_release_version,
        rag_release_shop_id=product_coverage_shop_id or rag_release_shop_id,
        rag_release_min_hit_rate=rag_release_min_hit_rate,
        rag_release_min_domain_match_rate=rag_release_min_domain_match_rate,
        rag_release_require_version_match=rag_release_require_version_match,
        rag_release_require_no_cross_shop=rag_release_require_no_cross_shop,
        rag_release_require_no_cross_domain=rag_release_require_no_cross_domain,
        rag_release_run_pollution_tests=rag_release_run_pollution_tests,
        cleanup_rag_pollution_before=cleanup_rag_pollution_before,
        cleanup_rag_pollution_after=cleanup_rag_pollution_after,
        rag_cleanup_dry_run=rag_cleanup_dry_run,
        rag_cleanup_source_type_prefix=rag_cleanup_source_type_prefix,
        rag_cleanup_namespace=rag_cleanup_namespace,
        audit_rag_legacy_pollution=audit_rag_legacy_pollution,
        require_no_rag_legacy_pollution=require_no_rag_legacy_pollution,
        cleanup_rag_legacy_pollution_before=cleanup_rag_legacy_pollution_before,
        cleanup_rag_legacy_pollution_after=cleanup_rag_legacy_pollution_after,
        legacy_cleanup_confirm_delete=legacy_cleanup_confirm_delete,
        legacy_cleanup_version=legacy_cleanup_version,
        legacy_cleanup_shop_id=legacy_cleanup_shop_id,
        legacy_cleanup_domain=legacy_cleanup_domain,
        llm_answer_real=llm_answer_real,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key_env=llm_api_key_env,
        llm_timeout_seconds=llm_timeout_seconds,
        require_answer_generated=require_answer_generated,
        answer_quality_qa=answer_quality_qa,
        answer_quality_real=answer_quality_real,
        answer_quality_domain=answer_quality_domain,
        answer_quality_case_id=answer_quality_case_id,
        answer_quality_max_cases=answer_quality_max_cases,
        answer_quality_profile=answer_quality_profile,
        answer_quality_product_version=answer_quality_product_version,
        answer_quality_min_pass_rate=answer_quality_min_pass_rate,
        answer_quality_require_no_p0_failures=answer_quality_require_no_p0_failures,
        answer_quality_require_no_forbidden=answer_quality_require_no_forbidden,
        answer_quality_require_source_type_match=answer_quality_require_source_type_match,
        product_coverage_qa=product_coverage_qa,
        product_coverage_real=product_coverage_real,
        product_db_path=product_db_path,
        product_version=product_version,
        product_domain=product_domain,
        product_coverage_limit=product_coverage_limit,
        product_coverage_min_hit_rate=product_coverage_min_hit_rate,
        product_coverage_min_field_rate=product_coverage_min_field_rate,
        conversation_replay=conversation_replay,
        conversation_replay_real=conversation_replay_real,
        conversation_shop_id=conversation_shop_id,
        conversation_buyer_id=conversation_buyer_id,
        conversation_session_id=conversation_session_id,
        conversation_limit=conversation_limit,
        conversation_min_pass_rate=conversation_min_pass_rate,
        conversation_max_failures=conversation_max_failures,
        conversation_allow_unclear_rate=conversation_allow_unclear_rate,
        answerable_conversation_replay=answerable_conversation_replay,
        answerable_replay_real=answerable_replay_real,
        answerable_replay_domain=answerable_replay_domain,
        answerable_replay_max_per_domain=answerable_replay_max_per_domain,
        answerable_replay_min_pass_rate=answerable_replay_min_pass_rate,
        answerable_replay_max_unclear_rate=answerable_replay_max_unclear_rate,
        answerable_replay_require_no_failures=answerable_replay_require_no_failures,
        answerable_replay_require_rag_hit=answerable_replay_require_rag_hit,
        answerable_replay_require_answer_generated=answerable_replay_require_answer_generated,
        answerable_replay_selector_audit=answerable_replay_selector_audit,
        answerable_replay_selector_audit_only=answerable_replay_selector_audit_only,
        answerable_replay_require_min_shops=answerable_replay_require_min_shops,
        answerable_replay_require_min_domains=answerable_replay_require_min_domains,
        answerable_replay_require_domain_coverage=answerable_replay_require_domain_coverage,
        answerable_replay_per_shop_limit=answerable_replay_per_shop_limit,
        answerable_replay_per_domain_limit=answerable_replay_per_domain_limit,
        answerable_replay_allow_empty_shop=answerable_replay_allow_empty_shop,
        replay_candidate_pool=replay_candidate_pool,
        replay_candidate_output=replay_candidate_output,
        replay_benchmark_file=replay_benchmark_file,
        replay_benchmark=replay_benchmark,
        replay_benchmark_real=replay_benchmark_real,
        replay_benchmark_min_pass_rate=replay_benchmark_min_pass_rate,
        replay_benchmark_max_unclear_rate=replay_benchmark_max_unclear_rate,
        pending_human_audit=pending_human_audit,
        manual_labeling_pack=manual_labeling_pack,
        manual_labeling_output_dir=manual_labeling_output_dir,
        manual_labeling_profile=manual_labeling_profile,
        replay_label_benchmark=replay_label_benchmark,
        label_input=label_input,
        label_benchmark_output=label_benchmark_output,
    )
    artifacts = artifact_result["artifacts"]
    schema_errors = artifact_result.get("schema_errors") or {}
    summary = dict(artifacts["summary.json"])
    summary["artifact_dir"] = "" if no_write else artifact_result["output_dir"]
    if require_conversation_db and summary.get("conversation_schema_status") == "missing":
        summary["failed"] = int(summary.get("failed", 0)) + 1

    return {
        "runner": "internal_engine_acceptance",
        "dry_run": False,
        "summary": {
            "passed": int(summary.get("passed", 0)),
            "failed": int(summary.get("failed", 0)) + _schema_error_count(schema_errors),
            "unclear": int(summary.get("unclear", 0)),
            "artifact_dir": summary["artifact_dir"],
            "no_send": True,
            "calls_fastgpt": False,
            "calls_llm": bool(summary.get("calls_llm", False)),
            "sends_pdd": False,
            "conversation_smoke_status": summary.get("conversation_smoke_status", "skipped"),
            "conversation_schema_status": summary.get("conversation_schema_status", "skipped"),
            "history_message_count": int(summary.get("history_message_count", 0)),
            "history_window_size": int(summary.get("history_window_size", 0)),
            "pending_human": bool(summary.get("pending_human", False)),
            "rag_status": summary.get("rag_status", "skipped"),
            "vector_store": summary.get("vector_store", ""),
            "embedding_model": summary.get("embedding_model", ""),
            "chunk_count": int(summary.get("chunk_count", 0)),
            "retrieval_hit_count": int(summary.get("retrieval_hit_count", 0)),
            "calls_ollama": bool(summary.get("calls_ollama", False)),
            "connects_pgvector": bool(summary.get("connects_pgvector", False)),
            "rag_real_status": summary.get("rag_real_status", "not_run"),
            "ollama_status": summary.get("ollama_status", "not_run"),
            "pgvector_status": summary.get("pgvector_status", "not_run"),
            "rag_engine_status": summary.get("rag_engine_status", ""),
            "rag_engine_hit_count": int(summary.get("rag_engine_hit_count", 0)),
            "rag_engine_real": bool(summary.get("rag_engine_real", False)),
            "rag_e2e_status": summary.get("rag_e2e_status", ""),
            "rag_requirement_status": summary.get("rag_requirement_status", ""),
            "rag_version_status": summary.get("rag_version_status", ""),
            "rag_expected_version": summary.get("rag_expected_version", ""),
            "rag_hit_versions": summary.get("rag_hit_versions", []),
            "rag_source_type_status": summary.get("rag_source_type_status", ""),
            "answer_generation_status": summary.get("answer_generation_status", ""),
            "guardrail_requirement_status": summary.get("guardrail_requirement_status", ""),
            "rag_engine_domain": summary.get("rag_engine_domain", ""),
            "rag_qa_status": summary.get("rag_qa_status", "skipped"),
            "rag_qa_total": int(summary.get("rag_qa_total", 0)),
            "rag_qa_passed": int(summary.get("rag_qa_passed", 0)),
            "rag_qa_failed": int(summary.get("rag_qa_failed", 0)),
            "rag_qa_hit_rate": summary.get("rag_qa_hit_rate", 0.0),
            "rag_qa_domain_match_rate": summary.get("rag_qa_domain_match_rate", 0.0),
            "rag_qa_version_match_rate": summary.get("rag_qa_version_match_rate", 0.0),
            "rag_release_status": summary.get("rag_release_status", "skipped"),
            "rag_release_real": bool(summary.get("rag_release_real", False)),
            "rag_release_version": summary.get("rag_release_version", ""),
            "rag_release_shop_id_hash": summary.get("rag_release_shop_id_hash", ""),
            "rag_release_total": int(summary.get("rag_release_total", 0)),
            "rag_release_passed": int(summary.get("rag_release_passed", 0)),
            "rag_release_failed": int(summary.get("rag_release_failed", 0)),
            "rag_release_hit_rate": summary.get("rag_release_hit_rate", 0.0),
            "rag_release_domain_match_rate": summary.get("rag_release_domain_match_rate", 0.0),
            "rag_release_version_match_rate": summary.get("rag_release_version_match_rate", 0.0),
            "rag_release_cross_shop_failures": int(summary.get("rag_release_cross_shop_failures", 0)),
            "rag_release_cross_domain_failures": int(summary.get("rag_release_cross_domain_failures", 0)),
            "rag_release_wrong_version_failures": int(summary.get("rag_release_wrong_version_failures", 0)),
            "rag_release_pollution_status": summary.get("rag_release_pollution_status", "not_run"),
            "rag_cleanup_before_status": summary.get("rag_cleanup_before_status", "skipped"),
            "rag_cleanup_after_status": summary.get("rag_cleanup_after_status", "skipped"),
            "rag_cleanup_deleted_count": int(summary.get("rag_cleanup_deleted_count", 0)),
            "rag_cleanup_dry_run": bool(summary.get("rag_cleanup_dry_run", True)),
            "rag_legacy_audit_status": summary.get("rag_legacy_audit_status", "skipped"),
            "rag_legacy_candidate_count": int(summary.get("rag_legacy_candidate_count", 0)),
            "rag_legacy_cleanup_status": summary.get("rag_legacy_cleanup_status", "skipped"),
            "rag_legacy_cleanup_deleted_count": int(summary.get("rag_legacy_cleanup_deleted_count", 0)),
            "rag_legacy_cleanup_dry_run": bool(summary.get("rag_legacy_cleanup_dry_run", True)),
            "answer_generator": summary.get("answer_generator", ""),
            "guardrail_status": summary.get("guardrail_status", ""),
            "llm_answer_status": summary.get("llm_answer_status", "not_run"),
            "llm_answer_generator": summary.get("llm_answer_generator", ""),
            "llm_answer_length": int(summary.get("llm_answer_length", 0)),
            "llm_answer_hash": summary.get("llm_answer_hash", ""),
            "llm_answer_preview_truncated": summary.get("llm_answer_preview_truncated", ""),
            "llm_guardrail_status": summary.get("llm_guardrail_status", ""),
            "answer_quality_status": summary.get("answer_quality_status", "skipped"),
            "answer_quality_total": int(summary.get("answer_quality_total", 0)),
            "answer_quality_passed": int(summary.get("answer_quality_passed", 0)),
            "answer_quality_failed": int(summary.get("answer_quality_failed", 0)),
            "answer_quality_pass_rate": summary.get("answer_quality_pass_rate", 0.0),
            "answer_quality_p0_failures": int(summary.get("answer_quality_p0_failures", 0)),
            "answer_quality_forbidden_phrase_failures": int(summary.get("answer_quality_forbidden_phrase_failures", 0)),
            "answer_quality_negated_forbidden_phrase_count": int(summary.get("answer_quality_negated_forbidden_phrase_count", 0)),
            "answer_quality_guardrail_blocked_count": int(summary.get("answer_quality_guardrail_blocked_count", 0)),
            "answer_quality_action_match_rate": summary.get("answer_quality_action_match_rate", 0.0),
            "answer_quality_domain_match_rate": summary.get("answer_quality_domain_match_rate", 0.0),
            "answer_quality_source_type_match_rate": summary.get("answer_quality_source_type_match_rate", 0.0),
            "answer_quality_version_match_rate": summary.get("answer_quality_version_match_rate", 0.0),
            "answer_quality_profile": summary.get("answer_quality_profile", "skipped"),
            "answer_quality_release_status": summary.get("answer_quality_release_status", "skipped"),
            "answer_quality_release_min_pass_rate": summary.get("answer_quality_release_min_pass_rate", 0.0),
            "answer_quality_product_source_type_match_rate": summary.get("answer_quality_product_source_type_match_rate", 0.0),
            "product_coverage_status": summary.get("product_coverage_status", "skipped"),
            "product_coverage_total": int(summary.get("product_coverage_total", 0)),
            "product_coverage_passed": int(summary.get("product_coverage_passed", 0)),
            "product_coverage_failed": int(summary.get("product_coverage_failed", 0)),
            "product_coverage_hit_rate": summary.get("product_coverage_hit_rate", 0.0),
            "product_coverage_field_rate": summary.get("product_coverage_field_rate", 0.0),
            "product_coverage_source_type_match_rate": summary.get("product_coverage_source_type_match_rate", 0.0),
            "product_coverage_version_match_rate": summary.get("product_coverage_version_match_rate", 0.0),
            "conversation_replay_status": summary.get("conversation_replay_status", "skipped"),
            "conversation_replay_total": int(summary.get("conversation_replay_total", 0)),
            "conversation_replay_passed": int(summary.get("conversation_replay_passed", 0)),
            "conversation_replay_failed": int(summary.get("conversation_replay_failed", 0)),
            "conversation_replay_unclear": int(summary.get("conversation_replay_unclear", 0)),
            "conversation_replay_pass_rate": summary.get("conversation_replay_pass_rate", 0.0),
            "conversation_replay_rag_hit_rate": summary.get("conversation_replay_rag_hit_rate", 0.0),
            "conversation_replay_guardrail_blocked_count": int(summary.get("conversation_replay_guardrail_blocked_count", 0)),
            "conversation_replay_transfer_human_count": int(summary.get("conversation_replay_transfer_human_count", 0)),
            "answerable_replay_status": summary.get("answerable_replay_status", "skipped"),
            "answerable_replay_total": int(summary.get("answerable_replay_total", 0)),
            "answerable_replay_passed": int(summary.get("answerable_replay_passed", 0)),
            "answerable_replay_failed": int(summary.get("answerable_replay_failed", 0)),
            "answerable_replay_unclear": int(summary.get("answerable_replay_unclear", 0)),
            "answerable_replay_pass_rate": summary.get("answerable_replay_pass_rate", 0.0),
            "answerable_replay_rag_hit_rate": summary.get("answerable_replay_rag_hit_rate", 0.0),
            "answerable_replay_answer_generated_rate": summary.get("answerable_replay_answer_generated_rate", 0.0),
            "answerable_selector_scanned_total": int(summary.get("answerable_selector_scanned_total", 0)),
            "answerable_selector_candidate_total": int(summary.get("answerable_selector_candidate_total", 0)),
            "answerable_selector_selected_total": int(summary.get("answerable_selector_selected_total", 0)),
            "answerable_selector_excluded_by_reason": summary.get("answerable_selector_excluded_by_reason", {}),
            "answerable_selector_selected_by_domain": summary.get("answerable_selector_selected_by_domain", {}),
            "answerable_replay_shops_total": int(summary.get("answerable_replay_shops_total", 0)),
            "answerable_replay_shops_with_candidates": int(summary.get("answerable_replay_shops_with_candidates", 0)),
            "answerable_replay_domain_coverage_status": summary.get("answerable_replay_domain_coverage_status", "skipped"),
            "answerable_replay_domains_missing": summary.get("answerable_replay_domains_missing", []),
            "answerable_replay_unclear_reason_counts": summary.get("answerable_replay_unclear_reason_counts", {}),
            "answerable_replay_rag_miss_reason_counts": summary.get("answerable_replay_rag_miss_reason_counts", {}),
            "replay_candidate_total": int(summary.get("replay_candidate_total", 0)),
            "replay_candidate_selected_by_domain": summary.get("replay_candidate_selected_by_domain", {}),
            "replay_candidate_excluded_by_reason": summary.get("replay_candidate_excluded_by_reason", {}),
            "replay_benchmark_case_count": int(summary.get("replay_benchmark_case_count", 0)),
            "replay_benchmark_pass_rate": summary.get("replay_benchmark_pass_rate", 0.0),
            "replay_benchmark_unclear_rate": summary.get("replay_benchmark_unclear_rate", 0.0),
            "pending_human_answerable_candidates": int(summary.get("pending_human_answerable_candidates", 0)),
            "manual_labeling_candidate_count": int(summary.get("manual_labeling_candidate_count", 0)),
            "manual_labeling_selected_by_domain": summary.get("manual_labeling_selected_by_domain", {}),
            "label_benchmark_case_count": int(summary.get("label_benchmark_case_count", 0)),
        },
        "schema": {
            "schema_version": artifacts["synthetic_report.json"]["schema_version"],
            "validation": schema_errors,
            "valid": all(not errors for errors in schema_errors.values()),
        },
        "artifacts": {} if no_write else artifact_result["files"],
        "constraints": _constraints(),
        "no_write": no_write,
    }


def write_report_and_exit(report: Mapping[str, Any], *, json_only: bool) -> int:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
    else:
        summary = report["summary"]
        print(
            "internal_engine_acceptance: "
            f"passed={summary['passed']} failed={summary['failed']} unclear={summary['unclear']} "
            f"artifact_dir={summary['artifact_dir'] or '<none>'} no_send={summary['no_send']}"
        )
        print(rendered)
    return 1 if int(report["summary"]["failed"]) > 0 else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    _apply_answer_quality_profile(args)
    if args.dry_run:
        report = dry_run_plan(
            sop_file=args.sop_file,
            artifact_dir=args.artifact_dir,
            no_write=args.no_write,
            conversation_db_path=None if args.skip_conversation_smoke else args.conversation_db_path,
            use_fake_answer_generator=args.use_fake_answer_generator,
            rag_smoke=not args.skip_rag_smoke,
            rag_smoke_real=args.rag_smoke_real,
            rag_engine_real=args.rag_engine_real,
            rag_e2e_profile=args.rag_e2e_profile,
            require_rag_hit=args.require_rag_hit,
            expect_rag_domain=args.expect_rag_domain,
            expect_rag_version=args.expect_rag_version,
            require_rag_version=args.require_rag_version,
            expect_rag_source_type=args.expect_rag_source_type,
            expect_answer_generator=args.expect_answer_generator,
            fake_answer_dangerous=args.fake_answer_dangerous,
            expect_guardrail_status=args.expect_guardrail_status or ("blocked" if args.expect_guardrail_blocked else ""),
            rag_domain=args.rag_domain,
            rag_version=args.rag_version,
            rag_query=args.rag_query,
            pg_dsn=args.pg_dsn,
            ollama_base_url=args.ollama_base_url,
            embedding_model=args.embedding_model,
            rag_retrieval_qa=args.rag_retrieval_qa,
            rag_retrieval_qa_real=args.rag_retrieval_qa_real,
            rag_qa_version=args.rag_qa_version,
            rag_qa_domain=args.rag_qa_domain,
            rag_qa_case_id=args.rag_qa_case_id,
            rag_release_gate=args.rag_release_gate,
            rag_release_real=args.rag_release_real,
            rag_release_version=args.rag_release_version,
            rag_release_shop_id=args.rag_release_shop_id,
            rag_release_min_hit_rate=args.rag_release_min_hit_rate,
            rag_release_min_domain_match_rate=args.rag_release_min_domain_match_rate,
            rag_release_require_version_match=args.rag_release_require_version_match,
            rag_release_require_no_cross_shop=args.rag_release_require_no_cross_shop,
            rag_release_require_no_cross_domain=args.rag_release_require_no_cross_domain,
            rag_release_run_pollution_tests=args.rag_release_run_pollution_tests,
            cleanup_rag_pollution_before=args.cleanup_rag_pollution_before,
            cleanup_rag_pollution_after=args.cleanup_rag_pollution_after,
            rag_cleanup_dry_run=args.rag_cleanup_dry_run,
            rag_cleanup_source_type_prefix=args.rag_cleanup_source_type_prefix,
            rag_cleanup_namespace=args.rag_cleanup_namespace,
            audit_rag_legacy_pollution=args.audit_rag_legacy_pollution,
            require_no_rag_legacy_pollution=args.require_no_rag_legacy_pollution,
            cleanup_rag_legacy_pollution_before=args.cleanup_rag_legacy_pollution_before,
            cleanup_rag_legacy_pollution_after=args.cleanup_rag_legacy_pollution_after,
            legacy_cleanup_confirm_delete=args.legacy_cleanup_confirm_delete,
            legacy_cleanup_version=args.legacy_cleanup_version,
            legacy_cleanup_shop_id=args.legacy_cleanup_shop_id,
            legacy_cleanup_domain=args.legacy_cleanup_domain,
            llm_answer_real=args.llm_answer_real,
            llm_base_url=args.llm_base_url,
            llm_model=args.llm_model,
            llm_api_key_env=args.llm_api_key_env,
            llm_timeout_seconds=args.llm_timeout_seconds,
            require_answer_generated=args.require_answer_generated,
            answer_quality_qa=args.answer_quality_qa,
            answer_quality_real=args.answer_quality_real,
            answer_quality_domain=args.answer_quality_domain,
            answer_quality_case_id=args.answer_quality_case_id,
            answer_quality_max_cases=args.answer_quality_max_cases,
            answer_quality_profile=args.answer_quality_profile,
            answer_quality_product_version=args.answer_quality_product_version,
            answer_quality_min_pass_rate=args.answer_quality_min_pass_rate,
            answer_quality_require_no_p0_failures=args.answer_quality_require_no_p0_failures,
            answer_quality_require_no_forbidden=args.answer_quality_release_require_no_forbidden,
            answer_quality_require_source_type_match=args.answer_quality_release_require_source_type_match,
            product_coverage_qa=args.product_coverage_qa,
            product_coverage_real=args.product_coverage_real,
            product_db_path=args.product_db_path,
            product_coverage_shop_id=args.shop_id,
            product_version=args.product_version,
            product_domain=args.product_domain,
            product_coverage_limit=args.product_coverage_limit,
            product_coverage_min_hit_rate=args.product_coverage_min_hit_rate,
            product_coverage_min_field_rate=args.product_coverage_min_field_rate,
            conversation_replay=args.conversation_replay,
            conversation_replay_real=args.conversation_replay_real,
            conversation_shop_id=args.conversation_shop_id,
            conversation_buyer_id=args.conversation_buyer_id,
            conversation_session_id=args.conversation_session_id,
            conversation_limit=args.conversation_limit,
            conversation_min_pass_rate=args.conversation_min_pass_rate,
            conversation_max_failures=args.conversation_max_failures,
            conversation_allow_unclear_rate=args.conversation_allow_unclear_rate,
            answerable_conversation_replay=args.answerable_conversation_replay,
            answerable_replay_real=args.answerable_replay_real,
            answerable_replay_domain=args.answerable_replay_domain,
            answerable_replay_max_per_domain=args.answerable_replay_max_per_domain,
            answerable_replay_min_pass_rate=args.answerable_replay_min_pass_rate,
            answerable_replay_max_unclear_rate=args.answerable_replay_max_unclear_rate,
            answerable_replay_require_no_failures=args.answerable_replay_require_no_failures,
            answerable_replay_require_rag_hit=args.answerable_replay_require_rag_hit,
            answerable_replay_require_answer_generated=args.answerable_replay_require_answer_generated,
            answerable_replay_selector_audit=args.answerable_replay_selector_audit,
            answerable_replay_selector_audit_only=args.answerable_replay_selector_audit_only,
            answerable_replay_require_min_shops=args.answerable_replay_require_min_shops,
            answerable_replay_require_min_domains=args.answerable_replay_require_min_domains,
            answerable_replay_require_domain_coverage=args.answerable_replay_require_domain_coverage,
            answerable_replay_per_shop_limit=args.answerable_replay_per_shop_limit,
            answerable_replay_per_domain_limit=args.answerable_replay_per_domain_limit,
            answerable_replay_allow_empty_shop=args.answerable_replay_allow_empty_shop,
            replay_candidate_pool=args.replay_candidate_pool,
            replay_candidate_output=args.replay_candidate_output,
            replay_benchmark_file=args.replay_benchmark_file,
            replay_benchmark=args.replay_benchmark,
            replay_benchmark_real=args.replay_benchmark_real,
            replay_benchmark_min_pass_rate=args.replay_benchmark_min_pass_rate,
            replay_benchmark_max_unclear_rate=args.replay_benchmark_max_unclear_rate,
            pending_human_audit=args.pending_human_audit,
            manual_labeling_pack=args.manual_labeling_pack,
            manual_labeling_output_dir=args.manual_labeling_output_dir,
            manual_labeling_profile=args.manual_labeling_profile,
            replay_label_benchmark=args.replay_label_benchmark,
            label_input=args.label_input,
            label_benchmark_output=args.label_benchmark_output,
        )
    else:
        command = [Path(sys.argv[0]).name, *(argv if argv is not None else sys.argv[1:])]
        report = run_acceptance(
            sop_file=args.sop_file,
            artifact_dir=args.artifact_dir,
            no_write=args.no_write,
            command=command,
            conversation_db_path=None if args.skip_conversation_smoke else args.conversation_db_path,
            require_conversation_db=args.require_conversation_db,
            use_fake_answer_generator=args.use_fake_answer_generator,
            rag_smoke=not args.skip_rag_smoke,
            rag_smoke_real=args.rag_smoke_real,
            rag_engine_real=args.rag_engine_real,
            rag_e2e_profile=args.rag_e2e_profile,
            require_rag_hit=args.require_rag_hit,
            expect_rag_domain=args.expect_rag_domain,
            expect_rag_version=args.expect_rag_version,
            require_rag_version=args.require_rag_version,
            expect_rag_source_type=args.expect_rag_source_type,
            expect_answer_generator=args.expect_answer_generator,
            fake_answer_dangerous=args.fake_answer_dangerous,
            expect_guardrail_status=args.expect_guardrail_status or ("blocked" if args.expect_guardrail_blocked else ""),
            rag_domain=args.rag_domain,
            rag_version=args.rag_version,
            rag_query=args.rag_query,
            pg_dsn=args.pg_dsn,
            ollama_base_url=args.ollama_base_url,
            embedding_model=args.embedding_model,
            rag_retrieval_qa=args.rag_retrieval_qa,
            rag_retrieval_qa_real=args.rag_retrieval_qa_real,
            rag_qa_version=args.rag_qa_version,
            rag_qa_domain=args.rag_qa_domain,
            rag_qa_case_id=args.rag_qa_case_id,
            rag_release_gate=args.rag_release_gate,
            rag_release_real=args.rag_release_real,
            rag_release_version=args.rag_release_version,
            rag_release_shop_id=args.rag_release_shop_id,
            rag_release_min_hit_rate=args.rag_release_min_hit_rate,
            rag_release_min_domain_match_rate=args.rag_release_min_domain_match_rate,
            rag_release_require_version_match=args.rag_release_require_version_match,
            rag_release_require_no_cross_shop=args.rag_release_require_no_cross_shop,
            rag_release_require_no_cross_domain=args.rag_release_require_no_cross_domain,
            rag_release_run_pollution_tests=args.rag_release_run_pollution_tests,
            cleanup_rag_pollution_before=args.cleanup_rag_pollution_before,
            cleanup_rag_pollution_after=args.cleanup_rag_pollution_after,
            rag_cleanup_dry_run=args.rag_cleanup_dry_run,
            rag_cleanup_source_type_prefix=args.rag_cleanup_source_type_prefix,
            rag_cleanup_namespace=args.rag_cleanup_namespace,
            audit_rag_legacy_pollution=args.audit_rag_legacy_pollution,
            require_no_rag_legacy_pollution=args.require_no_rag_legacy_pollution,
            cleanup_rag_legacy_pollution_before=args.cleanup_rag_legacy_pollution_before,
            cleanup_rag_legacy_pollution_after=args.cleanup_rag_legacy_pollution_after,
            legacy_cleanup_confirm_delete=args.legacy_cleanup_confirm_delete,
            legacy_cleanup_version=args.legacy_cleanup_version,
            legacy_cleanup_shop_id=args.legacy_cleanup_shop_id,
            legacy_cleanup_domain=args.legacy_cleanup_domain,
            llm_answer_real=args.llm_answer_real,
            llm_base_url=args.llm_base_url,
            llm_model=args.llm_model,
            llm_api_key_env=args.llm_api_key_env,
            llm_timeout_seconds=args.llm_timeout_seconds,
            require_answer_generated=args.require_answer_generated,
            answer_quality_qa=args.answer_quality_qa,
            answer_quality_real=args.answer_quality_real,
            answer_quality_domain=args.answer_quality_domain,
            answer_quality_case_id=args.answer_quality_case_id,
            answer_quality_max_cases=args.answer_quality_max_cases,
            answer_quality_profile=args.answer_quality_profile,
            answer_quality_product_version=args.answer_quality_product_version,
            answer_quality_min_pass_rate=args.answer_quality_min_pass_rate,
            answer_quality_require_no_p0_failures=args.answer_quality_require_no_p0_failures,
            answer_quality_require_no_forbidden=args.answer_quality_release_require_no_forbidden,
            answer_quality_require_source_type_match=args.answer_quality_release_require_source_type_match,
            product_coverage_qa=args.product_coverage_qa,
            product_coverage_real=args.product_coverage_real,
            product_db_path=args.product_db_path,
            product_coverage_shop_id=args.shop_id,
            product_version=args.product_version,
            product_domain=args.product_domain,
            product_coverage_limit=args.product_coverage_limit,
            product_coverage_min_hit_rate=args.product_coverage_min_hit_rate,
            product_coverage_min_field_rate=args.product_coverage_min_field_rate,
            conversation_replay=args.conversation_replay,
            conversation_replay_real=args.conversation_replay_real,
            conversation_shop_id=args.conversation_shop_id,
            conversation_buyer_id=args.conversation_buyer_id,
            conversation_session_id=args.conversation_session_id,
            conversation_limit=args.conversation_limit,
            conversation_min_pass_rate=args.conversation_min_pass_rate,
            conversation_max_failures=args.conversation_max_failures,
            conversation_allow_unclear_rate=args.conversation_allow_unclear_rate,
            answerable_conversation_replay=args.answerable_conversation_replay,
            answerable_replay_real=args.answerable_replay_real,
            answerable_replay_domain=args.answerable_replay_domain,
            answerable_replay_max_per_domain=args.answerable_replay_max_per_domain,
            answerable_replay_min_pass_rate=args.answerable_replay_min_pass_rate,
            answerable_replay_max_unclear_rate=args.answerable_replay_max_unclear_rate,
            answerable_replay_require_no_failures=args.answerable_replay_require_no_failures,
            answerable_replay_require_rag_hit=args.answerable_replay_require_rag_hit,
            answerable_replay_require_answer_generated=args.answerable_replay_require_answer_generated,
            answerable_replay_selector_audit=args.answerable_replay_selector_audit,
            answerable_replay_selector_audit_only=args.answerable_replay_selector_audit_only,
            answerable_replay_require_min_shops=args.answerable_replay_require_min_shops,
            answerable_replay_require_min_domains=args.answerable_replay_require_min_domains,
            answerable_replay_require_domain_coverage=args.answerable_replay_require_domain_coverage,
            answerable_replay_per_shop_limit=args.answerable_replay_per_shop_limit,
            answerable_replay_per_domain_limit=args.answerable_replay_per_domain_limit,
            answerable_replay_allow_empty_shop=args.answerable_replay_allow_empty_shop,
            replay_candidate_pool=args.replay_candidate_pool,
            replay_candidate_output=args.replay_candidate_output,
            replay_benchmark_file=args.replay_benchmark_file,
            replay_benchmark=args.replay_benchmark,
            replay_benchmark_real=args.replay_benchmark_real,
            replay_benchmark_min_pass_rate=args.replay_benchmark_min_pass_rate,
            replay_benchmark_max_unclear_rate=args.replay_benchmark_max_unclear_rate,
            pending_human_audit=args.pending_human_audit,
            manual_labeling_pack=args.manual_labeling_pack,
            manual_labeling_output_dir=args.manual_labeling_output_dir,
            manual_labeling_profile=args.manual_labeling_profile,
            replay_label_benchmark=args.replay_label_benchmark,
            label_input=args.label_input,
            label_benchmark_output=args.label_benchmark_output,
        )
    return write_report_and_exit(report, json_only=args.json_only)


def _schema_error_count(schema_errors: Mapping[str, Sequence[str]]) -> int:
    return sum(1 for errors in schema_errors.values() if errors)


def _constraints() -> dict[str, bool]:
    return {
        "no_send": True,
        "uses_synthetic_data_only": True,
        "calls_fastgpt": False,
        "calls_llm": False,
        "calls_pdd": False,
        "sends_pdd": False,
        "writes_db": False,
        "outputs_full_buyer_content": False,
        "outputs_full_reply": False,
        "outputs_full_sop_body": False,
        "outputs_secrets": False,
    }


def _apply_answer_quality_profile(args: argparse.Namespace) -> None:
    profile = str(getattr(args, "answer_quality_profile", "") or "")
    if getattr(args, "answer_quality_real_full", False):
        profile = "real_full"
    elif getattr(args, "answer_quality_real_smoke", False):
        profile = "real_smoke"
    if not profile:
        return
    args.answer_quality_profile = profile
    args.answer_quality_qa = True
    if profile in {"real_smoke", "real_full"}:
        args.answer_quality_real = True
    if profile == "real_smoke" and not int(getattr(args, "answer_quality_max_cases", 0) or 0):
        args.answer_quality_max_cases = int(getattr(args, "answer_quality_smoke_max_cases", 10) or 10)
    if profile == "real_full":
        args.answer_quality_max_cases = 0
        args.answer_quality_min_pass_rate = float(getattr(args, "answer_quality_release_min_pass_rate", 0.9) or 0.9)
        args.answer_quality_require_no_p0_failures = True
        args.answer_quality_release_require_no_forbidden = True
        args.answer_quality_release_require_source_type_match = True
    if getattr(args, "answer_quality_release_require_no_p0", False):
        args.answer_quality_require_no_p0_failures = True


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    raise SystemExit(main())
