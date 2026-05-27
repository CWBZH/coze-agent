import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "run_internal_engine_gate.py"
SOP_FIXTURE = REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"


def _load_gate():
    spec = importlib.util.spec_from_file_location("run_internal_engine_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_gate_dry_run_json_only_is_parseable():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["no_send"] is True
    assert payload["calls_fastgpt"] is False
    assert payload["calls_llm"] is False
    assert payload["sends_pdd"] is False


def test_gate_no_write_passes_without_artifact():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["artifact_dir"] == ""
    assert payload["schema_valid"] is True
    assert payload["conversation_smoke_status"] == "skipped"
    assert payload["rag_status"] == "ok"
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    assert payload["llm_answer_status"] in {"not_run", "not_required"}


def test_gate_default_does_not_run_conversation_replay():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["conversation_replay_status"] == "skipped"
    assert payload["conversation_replay_total"] == 0
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_fake_conversation_replay_passes():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--conversation-replay", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["conversation_replay_status"] == "passed"
    assert payload["conversation_replay_total"] >= 1
    assert payload["conversation_replay_failed"] == 0
    assert payload["no_send"] is True


def test_gate_fake_answerable_conversation_replay_passes():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--answerable-conversation-replay", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["answerable_replay_status"] == "passed"
    assert payload["answerable_replay_total"] >= 1
    assert payload["answerable_replay_failed"] == 0
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_candidate_pool_is_metadata_only_and_no_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--replay-candidate-pool", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["replay_candidate_total"] >= 1
    assert payload["replay_candidate_selected_by_domain"]
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_pending_human_audit_passes_without_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--pending-human-audit", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["pending_human_answerable_candidates"] == 0
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_manual_labeling_pack_passes_without_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--manual-labeling-pack", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["manual_labeling_candidate_count"] >= 1
    assert payload["manual_labeling_selected_by_domain"]
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_label_benchmark_build_passes_without_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--replay-label-benchmark", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["label_benchmark_case_count"] >= 1
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_real_answerable_replay_missing_config_fails_without_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--answerable-conversation-replay", "--answerable-replay-real", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["answerable_replay_status"] == "error"
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_answerable_threshold_failure_fails():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--answerable-conversation-replay",
            "--answerable-replay-min-pass-rate",
            "1.1",
            "--no-write",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["answerable_replay_status"] == "failed"


def test_gate_real_conversation_replay_missing_config_fails_without_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--conversation-replay", "--conversation-replay-real", "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["conversation_replay_status"] == "error"
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_conversation_replay_threshold_failure_fails():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--conversation-replay",
            "--conversation-min-pass-rate",
            "1.1",
            "--no-write",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["conversation_replay_status"] == "failed"


def test_gate_real_llm_requires_explicit_config_without_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--llm-answer-real", "--require-answer-generated", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["calls_llm"] is False
    assert payload["llm_answer_status"] == "failed_config"


def test_gate_real_rag_requires_pg_dsn():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--rag-smoke-real", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_real_status"] == "missing_pg_dsn"
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_real_rag_engine_requires_pg_dsn():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--rag-engine-real", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_engine_status"].startswith("error")
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_real_rag_engine_requires_ollama_base_url_without_leaking_dsn():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-engine-real",
            "--pg-dsn",
            "pgvector-dsn-private-password",
            "--embedding-model",
            "bge-m3",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "private-password" not in completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_engine_status"].startswith("error")


def test_gate_real_rag_engine_requires_embedding_model_without_leaking_dsn():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-engine-real",
            "--pg-dsn",
            "pgvector-dsn-private-password",
            "--ollama-base-url",
            "http://localhost:11434",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "private-password" not in completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_engine_status"].startswith("error")


def test_gate_fake_rag_e2e_profile_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-rag-domain",
            "logistics_policy",
            "--expect-answer-generator",
            "fake",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["rag_e2e_status"] == "ok"
    assert payload["rag_requirement_status"] == "passed"
    assert payload["answer_generation_status"] == "ok"


def test_gate_fake_rag_e2e_profile_version_pinning_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-rag-domain",
            "logistics_policy",
            "--rag-version",
            "sop-test-v1",
            "--expect-rag-version",
            "sop-test-v1",
            "--require-rag-version",
            "--expect-rag-source-type",
            "synthetic_rag",
            "--expect-answer-generator",
            "fake",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["rag_version_status"] == "passed"
    assert payload["rag_hit_versions"] == ["sop-test-v1"]


def test_gate_fake_rag_e2e_profile_version_mismatch_fails():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-rag-domain",
            "logistics_policy",
            "--rag-version",
            "sop-test-v1",
            "--expect-rag-version",
            "old-version",
            "--require-rag-version",
            "--expect-answer-generator",
            "fake",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_version_status"] == "failed_version_mismatch"


def test_gate_fake_rag_retrieval_qa_passes():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--rag-retrieval-qa", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["rag_qa_status"] == "passed"
    assert payload["rag_qa_failed"] == 0


def test_gate_default_does_not_run_release_gate():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["rag_release_status"] == "skipped"
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_fake_rag_release_gate_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-release-gate",
            "--rag-release-version",
            "sop-test-v1",
            "--rag-release-shop-id",
            "synthetic-shop-1",
            "--rag-release-require-version-match",
            "--rag-release-require-no-cross-shop",
            "--rag-release-require-no-cross-domain",
            "--rag-release-run-pollution-tests",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["rag_release_status"] == "passed"
    assert payload["rag_release_failed"] == 0
    assert payload["rag_release_pollution_status"] == "passed"


def test_gate_fake_rag_release_gate_threshold_failure_exits_nonzero():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-release-gate",
            "--rag-release-min-hit-rate",
            "1.1",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_release_status"] == "failed"


def test_gate_real_rag_release_requires_pg_dsn_without_external_calls():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--rag-release-gate", "--rag-release-real", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_release_status"] == "failed"
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_fake_release_cleanup_after_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-release-gate",
            "--rag-release-run-pollution-tests",
            "--cleanup-rag-pollution-after",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["rag_cleanup_after_status"] == "ok"
    assert payload["rag_cleanup_dry_run"] is True


def test_gate_default_skips_legacy_audit_and_cleanup():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--no-write", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["rag_legacy_audit_status"] == "skipped"
    assert payload["rag_legacy_candidate_count"] == 0
    assert payload["rag_legacy_cleanup_status"] == "skipped"


def test_gate_clean_baseline_requires_no_legacy_pollution():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--audit-rag-legacy-pollution",
            "--require-no-rag-legacy-pollution",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_legacy_audit_status"] == "ok"
    assert payload["rag_legacy_candidate_count"] >= 1


def test_gate_legacy_cleanup_after_confirm_delete_fake_store():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--cleanup-rag-legacy-pollution-after",
            "--legacy-cleanup-confirm-delete",
            "--legacy-cleanup-version",
            "old-version",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["rag_legacy_cleanup_status"] == "ok"
    assert payload["rag_legacy_cleanup_deleted_count"] >= 1


def test_gate_fake_answer_quality_qa_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--answer-quality-qa",
            "--answer-quality-max-cases",
            "6",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["answer_quality_status"] == "passed"
    assert payload["answer_quality_total"] == 6


def test_gate_real_answer_quality_requires_config_without_external_calls():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--answer-quality-real",
            "--answer-quality-max-cases",
            "1",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["answer_quality_status"] == "failed"
    assert payload["calls_llm"] is False


def test_gate_answer_quality_fake_mandatory_profile_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--answer-quality-profile",
            "fake_mandatory",
            "--answer-quality-max-cases",
            "6",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["answer_quality_profile"] == "fake_mandatory"
    assert payload["answer_quality_release_status"] == "passed"
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_answer_quality_real_smoke_requires_explicit_config():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--answer-quality-profile",
            "real_smoke",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["answer_quality_profile"] == "real_smoke"
    assert payload["answer_quality_status"] == "failed"
    assert payload["calls_llm"] is False


def test_gate_fake_product_coverage_qa_passes():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--product-coverage-qa", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["product_coverage_status"] == "passed"
    assert payload["product_coverage_total"] > 0
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    assert payload["calls_llm"] is False


def test_gate_real_product_coverage_requires_explicit_config():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--product-coverage-real", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["product_coverage_status"] == "error"
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_gate_product_coverage_threshold_failure_exits_nonzero():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--product-coverage-qa",
            "--product-coverage-min-hit-rate",
            "1.1",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["product_coverage_status"] == "failed"


def test_gate_fake_rag_e2e_profile_dangerous_guardrail_expected_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-rag-domain",
            "product_catalog",
            "--expect-answer-generator",
            "fake",
            "--fake-answer-dangerous",
            "--expect-guardrail-blocked",
            "--rag-domain",
            "product_catalog",
            "--rag-query",
            "Mini Balm \u591a\u5c11\u94b1",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["guardrail_requirement_status"] == "passed"
    assert payload["guardrail_status"] == "blocked"


def test_gate_guardrail_block_expected_fails_when_safe():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-rag-domain",
            "logistics_policy",
            "--expect-answer-generator",
            "fake",
            "--expect-guardrail-blocked",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["guardrail_requirement_status"] == "failed"


def test_gate_fake_rag_e2e_profile_require_hit_failure_exits_nonzero():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-rag-domain",
            "logistics_policy",
            "--expect-answer-generator",
            "fake",
            "--rag-domain",
            "after_sales_evidence",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert payload["rag_e2e_status"] == "failed"


def test_gate_fails_when_artifact_scan_fails(monkeypatch, tmp_path):
    gate = _load_gate()
    args = gate.parse_args(["--output-dir", str(tmp_path)])

    monkeypatch.setattr(
        gate.internal_engine_acceptance,
        "run_acceptance",
        lambda **kwargs: {
            "summary": {
                "passed": 1,
                "failed": 0,
                "unclear": 0,
                "artifact_dir": str(tmp_path),
            },
            "schema": {"valid": True, "schema_version": "internal-report-v1"},
        },
    )
    monkeypatch.setattr(gate, "scan_artifact_for_forbidden_fields", lambda path: ["bad.json: token is forbidden"])

    result = gate.run_gate(args)

    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert result["artifact_scan_passed"] is False


def test_gate_with_missing_conversation_db_reports_missing_without_failing(tmp_path):
    missing = tmp_path / "missing-conversation.sqlite"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--conversation-db-path", str(missing), "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["conversation_smoke_status"] == "ok"
    assert payload["conversation_schema_status"] == "missing"


def test_gate_with_conversation_db_reports_history_count(tmp_path):
    db_path = tmp_path / "conversation.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, user_id TEXT, buyer_id TEXT, session_id TEXT)")
    conn.execute(
        "CREATE TABLE messages (conversation_id TEXT, shop_id TEXT, user_id TEXT, buyer_id TEXT, session_id TEXT, content TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO conversations (id, shop_id, user_id, buyer_id, session_id) VALUES (?, ?, ?, ?, ?)",
        ("conv-a", "synthetic-shop-1", "", "synthetic-buyer", "synthetic-session"),
    )
    conn.execute(
        "INSERT INTO messages (conversation_id, shop_id, user_id, buyer_id, session_id, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("conv-a", "synthetic-shop-1", "", "synthetic-buyer", "synthetic-session", "PRIVATE_HISTORY", "2026-05-21T01:00:00Z"),
    )
    conn.commit()
    conn.close()

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--conversation-db-path", str(db_path), "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "PRIVATE_HISTORY" not in completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["conversation_schema_status"] == "ok"
    assert payload["history_message_count"] == 1
