"""Local no-send gate for InternalWorkflowEngine changes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.acceptance import internal_engine_acceptance
from scripts.acceptance.internal_acceptance_artifacts import scan_artifact_for_forbidden_fields


DEFAULT_SOP_FILE = Path("docs/acceptance/fixtures/internal_sop_example.md")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local no-send InternalWorkflowEngine gate.")
    parser.add_argument("--sop-file", type=Path, default=DEFAULT_SOP_FILE)
    parser.add_argument("--output-dir", type=Path, help="Artifact directory override.")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--conversation-db-path", type=Path, help="Optional read-only conversation DB smoke path.")
    parser.add_argument("--skip-conversation-smoke", action="store_true", help="Skip optional conversation DB smoke.")
    parser.add_argument("--require-conversation-db", action="store_true", help="Fail when supplied conversation DB is missing.")
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
    parser.add_argument("--rag-release-shop-id", default="synthetic-shop-1")
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
    parser.add_argument("--answer-quality-qa", action="store_true")
    parser.add_argument("--answer-quality-real", action="store_true")
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
    parser.add_argument("--product-coverage-qa", action="store_true")
    parser.add_argument("--product-coverage-real", action="store_true")
    parser.add_argument("--product-db-path", type=Path, default=Path("temp/missing.db"))
    parser.add_argument("--shop-id", default="")
    parser.add_argument("--product-version", default="real-product-v1")
    parser.add_argument("--product-domain", default="product_catalog")
    parser.add_argument("--product-coverage-limit", type=int, default=50)
    parser.add_argument("--product-coverage-min-hit-rate", type=float, default=0.9)
    parser.add_argument("--product-coverage-min-field-rate", type=float, default=0.8)
    parser.add_argument("--conversation-replay", action="store_true")
    parser.add_argument("--conversation-replay-real", action="store_true")
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


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    _apply_answer_quality_profile(args)
    synthetic_fake_answer_generator = not args.llm_answer_real
    if args.dry_run:
        report = internal_engine_acceptance.dry_run_plan(
            sop_file=args.sop_file,
            artifact_dir=args.output_dir,
            no_write=args.no_write,
            conversation_db_path=None if args.skip_conversation_smoke else args.conversation_db_path,
            use_fake_answer_generator=synthetic_fake_answer_generator,
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
        return _gate_summary(report, schema_valid=True, artifact_errors=[], dry_run=True)

    report = internal_engine_acceptance.run_acceptance(
        sop_file=args.sop_file,
        artifact_dir=args.output_dir,
        no_write=args.no_write,
        command=["run_internal_engine_gate.py"],
        conversation_db_path=None if args.skip_conversation_smoke else args.conversation_db_path,
        require_conversation_db=args.require_conversation_db,
        use_fake_answer_generator=synthetic_fake_answer_generator,
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
    schema_valid = bool(report.get("schema", {}).get("valid"))
    artifact_dir = str(report.get("summary", {}).get("artifact_dir") or "")
    artifact_errors = [] if args.no_write or not artifact_dir else scan_artifact_for_forbidden_fields(artifact_dir)
    return _gate_summary(
        report,
        schema_valid=schema_valid,
        artifact_errors=artifact_errors,
        dry_run=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_gate(args)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json_only:
        print(rendered)
    else:
        print(
            "internal_engine_gate: "
            f"status={summary['status']} passed={summary['passed']} failed={summary['failed']} "
            f"artifact_dir={summary['artifact_dir'] or '<none>'}"
        )
        print(rendered)
    return 0 if summary["status"] == "passed" else 1


def _gate_summary(
    report: Mapping[str, Any],
    *,
    schema_valid: bool,
    artifact_errors: Sequence[str],
    dry_run: bool,
) -> dict[str, Any]:
    base = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    failed = _int(base.get("failed")) + (0 if schema_valid else 1) + (1 if artifact_errors else 0)
    status = "passed" if failed == 0 else "failed"
    return {
        "status": status,
        "passed": _int(base.get("passed")),
        "failed": failed,
        "unclear": _int(base.get("unclear")),
        "artifact_dir": str(base.get("artifact_dir") or ""),
        "schema_version": str(report.get("schema", {}).get("schema_version") or "internal-report-v1"),
        "schema_valid": schema_valid,
        "artifact_scan_passed": not artifact_errors,
        "artifact_scan_errors": list(artifact_errors),
        "conversation_smoke_status": str(base.get("conversation_smoke_status") or "skipped"),
        "conversation_schema_status": str(base.get("conversation_schema_status") or "skipped"),
        "history_message_count": _int(base.get("history_message_count")),
        "history_window_size": _int(base.get("history_window_size")),
        "pending_human": bool(base.get("pending_human", False)),
        "rag_status": str(base.get("rag_status") or "skipped"),
        "vector_store": str(base.get("vector_store") or ""),
        "embedding_model": str(base.get("embedding_model") or ""),
        "chunk_count": _int(base.get("chunk_count")),
        "retrieval_hit_count": _int(base.get("retrieval_hit_count")),
        "calls_ollama": bool(base.get("calls_ollama", False)),
        "connects_pgvector": bool(base.get("connects_pgvector", False)),
        "rag_real_status": str(base.get("rag_real_status") or "not_run"),
        "ollama_status": str(base.get("ollama_status") or "not_run"),
        "pgvector_status": str(base.get("pgvector_status") or "not_run"),
        "rag_engine_status": str(base.get("rag_engine_status") or ""),
        "rag_engine_hit_count": _int(base.get("rag_engine_hit_count")),
        "rag_engine_real": bool(base.get("rag_engine_real", False)),
        "rag_e2e_status": str(base.get("rag_e2e_status") or ""),
        "rag_requirement_status": str(base.get("rag_requirement_status") or ""),
        "rag_version_status": str(base.get("rag_version_status") or ""),
        "rag_expected_version": str(base.get("rag_expected_version") or ""),
        "rag_hit_versions": list(base.get("rag_hit_versions") or []),
        "rag_source_type_status": str(base.get("rag_source_type_status") or ""),
        "rag_qa_status": str(base.get("rag_qa_status") or "skipped"),
        "rag_qa_total": _int(base.get("rag_qa_total")),
        "rag_qa_passed": _int(base.get("rag_qa_passed")),
        "rag_qa_failed": _int(base.get("rag_qa_failed")),
        "rag_qa_hit_rate": base.get("rag_qa_hit_rate", 0.0),
        "rag_qa_domain_match_rate": base.get("rag_qa_domain_match_rate", 0.0),
        "rag_qa_version_match_rate": base.get("rag_qa_version_match_rate", 0.0),
        "rag_release_status": str(base.get("rag_release_status") or "skipped"),
        "rag_release_real": bool(base.get("rag_release_real", False)),
        "rag_release_version": str(base.get("rag_release_version") or ""),
        "rag_release_shop_id_hash": str(base.get("rag_release_shop_id_hash") or ""),
        "rag_release_total": _int(base.get("rag_release_total")),
        "rag_release_passed": _int(base.get("rag_release_passed")),
        "rag_release_failed": _int(base.get("rag_release_failed")),
        "rag_release_hit_rate": base.get("rag_release_hit_rate", 0.0),
        "rag_release_domain_match_rate": base.get("rag_release_domain_match_rate", 0.0),
        "rag_release_version_match_rate": base.get("rag_release_version_match_rate", 0.0),
        "rag_release_cross_shop_failures": _int(base.get("rag_release_cross_shop_failures")),
        "rag_release_cross_domain_failures": _int(base.get("rag_release_cross_domain_failures")),
        "rag_release_wrong_version_failures": _int(base.get("rag_release_wrong_version_failures")),
        "rag_release_pollution_status": str(base.get("rag_release_pollution_status") or "not_run"),
        "rag_cleanup_before_status": str(base.get("rag_cleanup_before_status") or "skipped"),
        "rag_cleanup_after_status": str(base.get("rag_cleanup_after_status") or "skipped"),
        "rag_cleanup_deleted_count": _int(base.get("rag_cleanup_deleted_count")),
        "rag_cleanup_dry_run": bool(base.get("rag_cleanup_dry_run", True)),
        "rag_legacy_audit_status": str(base.get("rag_legacy_audit_status") or "skipped"),
        "rag_legacy_candidate_count": _int(base.get("rag_legacy_candidate_count")),
        "rag_legacy_cleanup_status": str(base.get("rag_legacy_cleanup_status") or "skipped"),
        "rag_legacy_cleanup_deleted_count": _int(base.get("rag_legacy_cleanup_deleted_count")),
        "rag_legacy_cleanup_dry_run": bool(base.get("rag_legacy_cleanup_dry_run", True)),
        "answer_generation_status": str(base.get("answer_generation_status") or ""),
        "guardrail_requirement_status": str(base.get("guardrail_requirement_status") or ""),
        "rag_engine_domain": str(base.get("rag_engine_domain") or ""),
        "answer_generator": str(base.get("answer_generator") or ""),
        "guardrail_status": str(base.get("guardrail_status") or ""),
        "llm_answer_status": str(base.get("llm_answer_status") or "not_run"),
        "llm_answer_generator": str(base.get("llm_answer_generator") or ""),
        "llm_answer_length": _int(base.get("llm_answer_length")),
        "llm_answer_hash": str(base.get("llm_answer_hash") or ""),
        "llm_answer_preview_truncated": str(base.get("llm_answer_preview_truncated") or ""),
        "llm_guardrail_status": str(base.get("llm_guardrail_status") or ""),
        "answer_quality_status": str(base.get("answer_quality_status") or "skipped"),
        "answer_quality_total": _int(base.get("answer_quality_total")),
        "answer_quality_passed": _int(base.get("answer_quality_passed")),
        "answer_quality_failed": _int(base.get("answer_quality_failed")),
        "answer_quality_pass_rate": base.get("answer_quality_pass_rate", 0.0),
        "answer_quality_p0_failures": _int(base.get("answer_quality_p0_failures")),
        "answer_quality_forbidden_phrase_failures": _int(base.get("answer_quality_forbidden_phrase_failures")),
        "answer_quality_negated_forbidden_phrase_count": _int(base.get("answer_quality_negated_forbidden_phrase_count")),
        "answer_quality_guardrail_blocked_count": _int(base.get("answer_quality_guardrail_blocked_count")),
        "answer_quality_action_match_rate": base.get("answer_quality_action_match_rate", 0.0),
        "answer_quality_domain_match_rate": base.get("answer_quality_domain_match_rate", 0.0),
        "answer_quality_source_type_match_rate": base.get("answer_quality_source_type_match_rate", 0.0),
        "answer_quality_version_match_rate": base.get("answer_quality_version_match_rate", 0.0),
        "answer_quality_profile": str(base.get("answer_quality_profile") or "skipped"),
        "answer_quality_release_status": str(base.get("answer_quality_release_status") or "skipped"),
        "answer_quality_release_min_pass_rate": base.get("answer_quality_release_min_pass_rate", 0.0),
        "answer_quality_product_source_type_match_rate": base.get("answer_quality_product_source_type_match_rate", 0.0),
        "product_coverage_status": str(base.get("product_coverage_status") or "skipped"),
        "product_coverage_total": _int(base.get("product_coverage_total")),
        "product_coverage_passed": _int(base.get("product_coverage_passed")),
        "product_coverage_failed": _int(base.get("product_coverage_failed")),
        "product_coverage_hit_rate": base.get("product_coverage_hit_rate", 0.0),
        "product_coverage_field_rate": base.get("product_coverage_field_rate", 0.0),
        "product_coverage_source_type_match_rate": base.get("product_coverage_source_type_match_rate", 0.0),
        "product_coverage_version_match_rate": base.get("product_coverage_version_match_rate", 0.0),
        "conversation_replay_status": str(base.get("conversation_replay_status") or "skipped"),
        "conversation_replay_total": _int(base.get("conversation_replay_total")),
        "conversation_replay_passed": _int(base.get("conversation_replay_passed")),
        "conversation_replay_failed": _int(base.get("conversation_replay_failed")),
        "conversation_replay_unclear": _int(base.get("conversation_replay_unclear")),
        "conversation_replay_pass_rate": base.get("conversation_replay_pass_rate", 0.0),
        "conversation_replay_rag_hit_rate": base.get("conversation_replay_rag_hit_rate", 0.0),
        "conversation_replay_guardrail_blocked_count": _int(base.get("conversation_replay_guardrail_blocked_count")),
        "conversation_replay_transfer_human_count": _int(base.get("conversation_replay_transfer_human_count")),
        "answerable_replay_status": str(base.get("answerable_replay_status") or "skipped"),
        "answerable_replay_total": _int(base.get("answerable_replay_total")),
        "answerable_replay_passed": _int(base.get("answerable_replay_passed")),
        "answerable_replay_failed": _int(base.get("answerable_replay_failed")),
        "answerable_replay_unclear": _int(base.get("answerable_replay_unclear")),
        "answerable_replay_pass_rate": base.get("answerable_replay_pass_rate", 0.0),
        "answerable_replay_rag_hit_rate": base.get("answerable_replay_rag_hit_rate", 0.0),
        "answerable_replay_answer_generated_rate": base.get("answerable_replay_answer_generated_rate", 0.0),
        "answerable_selector_scanned_total": _int(base.get("answerable_selector_scanned_total")),
        "answerable_selector_candidate_total": _int(base.get("answerable_selector_candidate_total")),
        "answerable_selector_selected_total": _int(base.get("answerable_selector_selected_total")),
        "answerable_selector_excluded_by_reason": dict(base.get("answerable_selector_excluded_by_reason") or {}),
        "answerable_selector_selected_by_domain": dict(base.get("answerable_selector_selected_by_domain") or {}),
        "answerable_replay_shops_total": _int(base.get("answerable_replay_shops_total")),
        "answerable_replay_shops_with_candidates": _int(base.get("answerable_replay_shops_with_candidates")),
        "answerable_replay_domain_coverage_status": str(base.get("answerable_replay_domain_coverage_status") or "skipped"),
        "answerable_replay_domains_missing": list(base.get("answerable_replay_domains_missing") or []),
        "answerable_replay_unclear_reason_counts": dict(base.get("answerable_replay_unclear_reason_counts") or {}),
        "answerable_replay_rag_miss_reason_counts": dict(base.get("answerable_replay_rag_miss_reason_counts") or {}),
        "replay_candidate_total": _int(base.get("replay_candidate_total")),
        "replay_candidate_selected_by_domain": dict(base.get("replay_candidate_selected_by_domain") or {}),
        "replay_candidate_excluded_by_reason": dict(base.get("replay_candidate_excluded_by_reason") or {}),
        "replay_benchmark_case_count": _int(base.get("replay_benchmark_case_count")),
        "replay_benchmark_pass_rate": base.get("replay_benchmark_pass_rate", 0.0),
        "replay_benchmark_unclear_rate": base.get("replay_benchmark_unclear_rate", 0.0),
        "manual_labeling_candidate_count": _int(base.get("manual_labeling_candidate_count")),
        "manual_labeling_selected_by_domain": dict(base.get("manual_labeling_selected_by_domain") or {}),
        "label_benchmark_case_count": _int(base.get("label_benchmark_case_count")),
        "pending_human_answerable_candidates": _int(base.get("pending_human_answerable_candidates")),
        "dry_run": dry_run,
        "no_send": True,
        "calls_fastgpt": False,
        "calls_llm": bool(base.get("calls_llm", False)),
        "sends_pdd": False,
    }


def _int(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
