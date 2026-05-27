import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_engine_acceptance.py"
SOP_FIXTURE = REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"


def _load_runner():
    spec = importlib.util.spec_from_file_location("internal_engine_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _run_cli(*args, expected_returncode=0):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    return completed.stdout


def test_dry_run_lists_plan_without_engine_execution(monkeypatch, capsys):
    runner = _load_runner()

    def bomb_run_cases(*args, **kwargs):
        raise AssertionError("engine must not run for --dry-run")

    monkeypatch.setattr(runner.internal_engine_synthetic_qa, "run_cases", bomb_run_cases)

    exit_code = runner.main(["--dry-run", "--sop-file", str(SOP_FIXTURE), "--json-only"])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["plan"]["synthetic_cases"]["case_count"] == 23
    assert report["plan"]["synthetic_cases"]["engine"] == "not_executed"
    assert report["plan"]["dry_run_example"]["shop_id_hash"]
    assert report["plan"]["dry_run_example"]["message_length"] == len(
        runner.DRY_RUN_EXAMPLE_MESSAGE
    )
    assert report["summary"]["no_send"] is True
    assert report["summary"]["calls_fastgpt"] is False
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["sends_pdd"] is False


def test_json_only_stdout_is_parseable():
    stdout = _run_cli("--sop-file", str(SOP_FIXTURE), "--json-only", "--no-write")

    report = json.loads(stdout)
    assert report["runner"] == "internal_engine_acceptance"
    assert report["dry_run"] is False
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] >= 23
    assert report["schema"]["valid"] is True


def test_no_write_creates_no_artifact(tmp_path):
    artifact_dir = tmp_path / "must_not_exist"
    stdout = _run_cli(
        "--sop-file",
        str(SOP_FIXTURE),
        "--artifact-dir",
        str(artifact_dir),
        "--no-write",
        "--json-only",
    )

    report = json.loads(stdout)
    assert report["summary"]["artifact_dir"] == ""
    assert report["artifacts"] == {}
    assert artifact_dir.exists() is False


def test_no_send_flags_are_correct():
    runner = _load_runner()

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, no_write=True)

    assert report["summary"]["no_send"] is True
    assert report["summary"]["calls_fastgpt"] is False
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["sends_pdd"] is False
    assert report["constraints"]["calls_pdd"] is False
    assert report["constraints"]["writes_db"] is False
    assert report["summary"]["conversation_smoke_status"] == "skipped"
    assert report["summary"]["rag_status"] == "ok"
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False
    assert report["summary"]["llm_answer_status"] in {"not_run", "not_required"}


def test_acceptance_default_does_not_run_conversation_replay():
    runner = _load_runner()

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, no_write=True)

    assert report["summary"]["conversation_replay_status"] == "skipped"
    assert report["summary"]["conversation_replay_total"] == 0
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_fake_conversation_replay_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        conversation_replay=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["conversation_replay_status"] == "passed"
    assert report["summary"]["conversation_replay_total"] >= 1
    assert report["summary"]["conversation_replay_failed"] == 0
    assert report["summary"]["no_send"] is True


def test_acceptance_fake_answerable_conversation_replay_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        answerable_conversation_replay=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["answerable_replay_status"] == "passed"
    assert report["summary"]["answerable_replay_total"] >= 1
    assert report["summary"]["answerable_replay_failed"] == 0
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_candidate_pool_summary_is_available_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        replay_candidate_pool=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["replay_candidate_total"] >= 1
    assert report["summary"]["replay_candidate_selected_by_domain"]
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_manual_labeling_pack_summary_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        manual_labeling_pack=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["manual_labeling_candidate_count"] >= 1
    assert report["summary"]["manual_labeling_selected_by_domain"]
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_label_benchmark_summary_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        replay_label_benchmark=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["label_benchmark_case_count"] >= 1
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_real_answerable_replay_missing_config_fails_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        answerable_conversation_replay=True,
        answerable_replay_real=True,
        conversation_shop_id="synthetic-shop-1",
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["answerable_replay_status"] == "error"
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_answerable_threshold_failure_fails_gate():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        answerable_conversation_replay=True,
        answerable_replay_min_pass_rate=1.1,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["answerable_replay_status"] == "failed"


def test_acceptance_real_conversation_replay_missing_config_fails_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        conversation_replay=True,
        conversation_replay_real=True,
        conversation_shop_id="synthetic-shop-1",
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["conversation_replay_status"] == "error"
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_conversation_replay_threshold_failure_fails_gate():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        conversation_replay=True,
        conversation_min_pass_rate=1.1,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["conversation_replay_status"] == "failed"


def test_real_llm_answer_missing_config_fails_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        llm_answer_real=True,
        require_answer_generated=True,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["llm_answer_status"] == "failed_config"
    assert report["summary"]["llm_answer_hash"] == ""


def test_real_rag_missing_dsn_fails_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, no_write=True, rag_smoke_real=True)

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_real_status"] == "missing_pg_dsn"
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_real_rag_engine_missing_dsn_fails_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, no_write=True, rag_engine_real=True)

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_engine_status"].startswith("error")
    assert report["summary"]["rag_engine_hit_count"] == 0
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_real_rag_engine_missing_ollama_fails_without_leaking_dsn():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_engine_real=True,
        pg_dsn="pgvector-dsn-private-password",
        embedding_model="bge-m3",
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_engine_status"].startswith("error")
    assert "private-password" not in rendered


def test_fake_rag_e2e_profile_acceptance_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_e2e_profile=True,
        require_rag_hit=True,
        expect_rag_domain="logistics_policy",
        expect_answer_generator="fake",
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["rag_e2e_status"] == "ok"
    assert report["summary"]["rag_requirement_status"] == "passed"
    assert report["summary"]["answer_generation_status"] == "ok"
    assert report["summary"]["answer_generator"] == "fake"


def test_fake_rag_e2e_profile_acceptance_version_pinning_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_e2e_profile=True,
        require_rag_hit=True,
        expect_rag_domain="logistics_policy",
        rag_version="sop-test-v1",
        expect_rag_version="sop-test-v1",
        require_rag_version=True,
        expect_rag_source_type="synthetic_rag",
        expect_answer_generator="fake",
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["rag_version_status"] == "passed"
    assert report["summary"]["rag_expected_version"] == "sop-test-v1"
    assert report["summary"]["rag_hit_versions"] == ["sop-test-v1"]
    assert report["summary"]["rag_source_type_status"] == "passed"


def test_fake_rag_e2e_profile_acceptance_version_mismatch_fails():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_e2e_profile=True,
        require_rag_hit=True,
        expect_rag_domain="logistics_policy",
        rag_version="sop-test-v1",
        expect_rag_version="old-version",
        require_rag_version=True,
        expect_answer_generator="fake",
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_version_status"] == "failed_version_mismatch"


def test_acceptance_fake_rag_retrieval_qa_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_retrieval_qa=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["rag_qa_status"] == "passed"
    assert report["summary"]["rag_qa_total"] >= 20
    assert report["summary"]["rag_qa_failed"] == 0


def test_acceptance_fake_rag_release_gate_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_release_gate=True,
        rag_release_version="sop-test-v1",
        rag_release_shop_id="synthetic-shop-1",
        rag_release_require_version_match=True,
        rag_release_require_no_cross_shop=True,
        rag_release_require_no_cross_domain=True,
        rag_release_run_pollution_tests=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["rag_release_status"] == "passed"
    assert report["summary"]["rag_release_total"] >= 20
    assert report["summary"]["rag_release_wrong_version_failures"] == 0
    assert report["summary"]["rag_release_pollution_status"] == "passed"


def test_acceptance_fake_rag_release_gate_wrong_version_fails():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_release_gate=True,
        rag_release_version="old-version",
        rag_release_shop_id="synthetic-shop-1",
        rag_release_require_version_match=True,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_release_status"] == "failed"


def test_acceptance_real_rag_release_requires_pg_dsn_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_release_gate=True,
        rag_release_real=True,
        rag_release_version="sop-test-v1",
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_release_status"] == "failed"
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_cleanup_summary_defaults_to_skipped():
    runner = _load_runner()

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, no_write=True)

    assert report["summary"]["rag_cleanup_before_status"] == "skipped"
    assert report["summary"]["rag_cleanup_after_status"] == "skipped"
    assert report["summary"]["rag_cleanup_deleted_count"] == 0


def test_acceptance_fake_cleanup_after_release_gate_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_release_gate=True,
        rag_release_run_pollution_tests=True,
        cleanup_rag_pollution_after=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["rag_cleanup_after_status"] == "ok"
    assert report["summary"]["rag_cleanup_dry_run"] is True


def test_acceptance_legacy_audit_defaults_to_skipped():
    runner = _load_runner()

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, no_write=True)

    assert report["summary"]["rag_legacy_audit_status"] == "skipped"
    assert report["summary"]["rag_legacy_candidate_count"] == 0
    assert report["summary"]["rag_legacy_cleanup_status"] == "skipped"


def test_acceptance_legacy_audit_require_clean_baseline_fails_on_candidates():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        audit_rag_legacy_pollution=True,
        require_no_rag_legacy_pollution=True,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_legacy_audit_status"] == "ok"
    assert report["summary"]["rag_legacy_candidate_count"] >= 1


def test_acceptance_legacy_cleanup_after_confirm_deletes_fake_candidates():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        cleanup_rag_legacy_pollution_after=True,
        legacy_cleanup_confirm_delete=True,
        legacy_cleanup_version="old-version",
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["rag_legacy_cleanup_status"] == "ok"
    assert report["summary"]["rag_legacy_cleanup_deleted_count"] >= 1
    assert report["summary"]["rag_legacy_cleanup_dry_run"] is False


def test_acceptance_fake_answer_quality_qa_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        answer_quality_qa=True,
        answer_quality_max_cases=6,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["answer_quality_status"] == "passed"
    assert report["summary"]["answer_quality_total"] == 6
    assert report["summary"]["answer_quality_p0_failures"] == 0


def test_acceptance_real_answer_quality_requires_config_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        answer_quality_real=True,
        answer_quality_max_cases=1,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["answer_quality_status"] == "failed"
    assert report["summary"]["calls_llm"] is False
    assert report["summary"]["calls_ollama"] is False


def test_acceptance_answer_quality_fake_mandatory_profile_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        answer_quality_qa=True,
        answer_quality_profile="fake_mandatory",
        answer_quality_max_cases=6,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["answer_quality_profile"] == "fake_mandatory"
    assert report["summary"]["answer_quality_release_status"] == "passed"
    assert report["summary"]["calls_llm"] is False


def test_acceptance_answer_quality_real_smoke_profile_requires_config():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        answer_quality_real=True,
        answer_quality_profile="real_smoke",
        answer_quality_max_cases=1,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["answer_quality_profile"] == "real_smoke"
    assert report["summary"]["answer_quality_status"] == "failed"
    assert report["summary"]["calls_llm"] is False


def test_acceptance_fake_product_coverage_qa_passes():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        product_coverage_qa=True,
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["product_coverage_status"] == "passed"
    assert report["summary"]["product_coverage_total"] > 0
    assert report["summary"]["product_coverage_hit_rate"] >= 0.9
    assert report["summary"]["product_coverage_field_rate"] >= 0.8
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_real_product_coverage_requires_config_without_external_calls():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        product_coverage_real=True,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["product_coverage_status"] == "error"
    assert report["summary"]["calls_ollama"] is False
    assert report["summary"]["connects_pgvector"] is False


def test_acceptance_product_coverage_threshold_failure_fails():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        product_coverage_qa=True,
        product_coverage_min_hit_rate=1.1,
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["product_coverage_status"] == "failed"


def test_fake_rag_e2e_profile_dangerous_guardrail_can_pass_when_expected():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_e2e_profile=True,
        require_rag_hit=True,
        expect_rag_domain="product_catalog",
        expect_answer_generator="fake",
        fake_answer_dangerous=True,
        expect_guardrail_status="blocked",
        rag_domain="product_catalog",
        rag_query="Mini Balm \u591a\u5c11\u94b1",
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["rag_e2e_status"] == "ok"
    assert report["summary"]["guardrail_requirement_status"] == "passed"
    assert report["summary"]["guardrail_status"] == "blocked"


def test_fake_rag_e2e_profile_require_hit_failure_affects_summary():
    runner = _load_runner()

    report = runner.run_acceptance(
        sop_file=SOP_FIXTURE,
        no_write=True,
        rag_e2e_profile=True,
        require_rag_hit=True,
        expect_rag_domain="logistics_policy",
        expect_answer_generator="fake",
        rag_domain="after_sales_evidence",
        rag_query="\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
    )

    assert report["summary"]["failed"] >= 1
    assert report["summary"]["rag_e2e_status"] == "failed"


def test_acceptance_with_conversation_db_adds_summary_fields(tmp_path):
    runner = _load_runner()
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
        ("conv-a", "synthetic-shop-1", "", "synthetic-buyer", "synthetic-session", "PRIVATE_ACCEPTANCE_HISTORY", "2026-05-21T01:00:00Z"),
    )
    conn.commit()
    conn.close()

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, no_write=True, conversation_db_path=db_path)

    assert report["summary"]["conversation_smoke_status"] == "ok"
    assert report["summary"]["conversation_schema_status"] == "ok"
    assert report["summary"]["history_message_count"] == 1
    assert "PRIVATE_ACCEPTANCE_HISTORY" not in json.dumps(report, ensure_ascii=False)


def test_failed_report_returns_nonzero_in_testable_path(monkeypatch, tmp_path):
    runner = _load_runner()

    def fake_build_artifacts(**kwargs):
        return {
            "output_dir": str(tmp_path),
            "files": {},
            "artifacts": {
                "summary.json": {
                    "passed": 0,
                    "failed": 1,
                    "unclear": 0,
                    "artifact_dir": "",
                },
                "synthetic_report.json": {
                    "schema_version": "internal-report-v1",
                },
            },
            "schema_errors": {"synthetic_report.json": []},
        }

    monkeypatch.setattr(runner, "build_artifacts", fake_build_artifacts)

    report = runner.run_acceptance(sop_file=SOP_FIXTURE, artifact_dir=tmp_path, no_write=True)
    exit_code = runner.write_report_and_exit(report, json_only=True)

    assert exit_code == 1
    assert report["summary"]["failed"] == 1


def test_output_omits_full_buyer_original_reply_sop_body_and_product_details():
    runner = _load_runner()
    stdout = _run_cli("--sop-file", str(SOP_FIXTURE), "--json-only", "--no-write")

    json.loads(stdout)
    assert runner.DRY_RUN_EXAMPLE_MESSAGE not in stdout
    assert "reply_text" not in stdout
    assert "Please ask the buyer to provide clear photos" not in stdout
    assert "Do not approve refunds before evidence" not in stdout
    assert "sop-after-sales-001" not in stdout
    assert "synthetic-price-99" not in stdout
    assert "synthetic-ingredient-list" not in stdout
    assert "synthetic record only; page display is authoritative" not in stdout
