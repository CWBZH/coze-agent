import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/acceptance/internal_engine_synthetic_qa.py")
SOP_FIXTURE = Path("docs/acceptance/fixtures/internal_sop_example.md")


def _load_runner():
    spec = importlib.util.spec_from_file_location("internal_engine_synthetic_qa", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_executes_synthetic_cases_and_writes_json(tmp_path):
    runner = _load_runner()
    output_path = tmp_path / "internal_engine_report.json"

    exit_code = runner.main(["--output", str(output_path), "--json-only"])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["total"] > 0
    assert report["summary"]["failed"] == 0
    assert report["summary"]["unclear"] == 0
    assert report["summary"]["passed"] == report["summary"]["total"]
    assert report["offline_constraints"]["uses_synthetic_data_only"] is True
    assert report["offline_constraints"]["calls_fastgpt"] is False
    assert report["offline_constraints"]["calls_pdd"] is False
    assert all(row["case_id"].startswith("T100G-") for row in report["cases"])
    assert all("buyer-1" not in json.dumps(row, ensure_ascii=False) for row in report["cases"])
    assert any(row["category"].startswith("product-") and row["knowledge_hit_count"] > 0 for row in report["cases"])
    assert all("knowledge_source" in row for row in report["cases"])
    assert all("intent" in row for row in report["cases"])
    assert all("action" in row for row in report["cases"])


def test_runner_with_sop_file_summarizes_fixture_without_raw_sop(tmp_path):
    runner = _load_runner()
    output_path = tmp_path / "internal_engine_report_with_sop.json"

    exit_code = runner.main(["--sop-file", str(SOP_FIXTURE), "--output", str(output_path), "--json-only"])

    assert exit_code == 0
    rendered = output_path.read_text(encoding="utf-8")
    report = json.loads(rendered)
    assert report["sop_record_count"] == 5
    assert report["sop_version"] == "sop-test-v1"
    assert "redline_escalation" in report["sop_domains"]
    assert report["summary"]["total"] == 23
    assert report["summary"]["failed"] == 0
    assert "Keep the reply neutral and transfer to human support" not in rendered
    assert "sop-redline-001" not in rendered


def test_runner_with_sop_file_executes_sop_domain_cases():
    runner = _load_runner()

    report = runner.run_cases(sop_file=SOP_FIXTURE)
    sop_rows = [row for row in report["cases"] if row["category"] == "sop_domain"]

    assert len(sop_rows) == 10
    assert all(row["status"] == "passed" for row in sop_rows)
    assert all(row["sop_hit"] is True for row in sop_rows)
    assert all(row["knowledge_source"] == "sop" for row in sop_rows)
    assert all(row["knowledge_hit_count"] > 0 for row in sop_rows)
    assert all(row["sop_version"] == "sop-test-v1" for row in sop_rows)
    assert {
        "logistics_policy",
        "after_sales_evidence",
        "promotion_policy",
        "redline_escalation",
        "sensitive_user_safety",
    } <= {row["sop_domain"] for row in sop_rows}


def test_runner_rows_include_stable_sop_and_knowledge_keys():
    runner = _load_runner()

    report = runner.run_cases(sop_file=SOP_FIXTURE)
    stable_keys = {"sop_hit", "sop_domain", "sop_version", "knowledge_source", "knowledge_hit_count"}

    assert all(stable_keys <= row.keys() for row in report["cases"])


def test_runner_limit_reduces_case_count(tmp_path):
    runner = _load_runner()
    output_path = tmp_path / "limited_report.json"

    exit_code = runner.main(["--output", str(output_path), "--limit", "2", "--json-only"])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["total"] == 2
    assert len(report["cases"]) == 2


def test_runner_dry_run_lists_cases_without_engine_execution(tmp_path):
    runner = _load_runner()
    output_path = tmp_path / "dry_run_report.json"
    runner.build_engine = lambda: (_ for _ in ()).throw(AssertionError("engine must not run in dry-run"))

    exit_code = runner.main(["--dry-run", "--output", str(output_path), "--json-only"])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["dry_run"] is True
    assert report["summary"]["total"] == len(runner.default_cases())
    assert report["summary"]["total"] >= 13
    assert report["summary"]["passed"] == 0
    assert report["summary"]["failed"] == 0
    assert all("actual_action" not in row for row in report["cases"])
    assert all("content_hash" in row for row in report["cases"])
    assert all("knowledge_hit_count" not in row for row in report["cases"])


def test_runner_dry_run_with_sop_file_lists_context_without_engine(tmp_path):
    runner = _load_runner()
    output_path = tmp_path / "dry_run_report_with_sop.json"
    runner.build_engine = lambda: (_ for _ in ()).throw(AssertionError("engine must not run in dry-run"))

    exit_code = runner.main(["--dry-run", "--sop-file", str(SOP_FIXTURE), "--output", str(output_path), "--json-only"])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["dry_run"] is True
    assert report["sop_record_count"] == 5
    assert "promotion_policy" in report["sop_domains"]
    assert all("actual_action" not in row for row in report["cases"])


def test_runner_malformed_sop_file_does_not_crash(tmp_path):
    runner = _load_runner()
    malformed = tmp_path / "bad_sop.md"
    malformed.write_text("## Bad SOP\nnot a valid field line\n", encoding="utf-8")

    report = runner.run_cases(limit=1, sop_file=malformed)

    assert report["summary"]["total"] == 1
    assert report["sop_record_count"] == 0
    assert report["sop_domains"] == []
    assert report["sop_error_count"] >= 1


def test_runner_uses_fake_repository_records_instead_of_direct_retriever():
    runner = _load_runner()
    engine = runner.build_engine()

    assert engine.knowledge_repository is not None
    assert engine.knowledge_retriever is None


def test_runner_supports_fake_answer_generator_metadata():
    runner = _load_runner()

    report = runner.run_cases(use_fake_answer_generator=True)

    assert report["offline_constraints"]["calls_llm"] is False
    assert any(row.get("answer_generator") == "fake" for row in report["cases"])
    assert all("reply_text" not in row for row in report["cases"])


def test_runner_supports_fake_rag_metadata():
    runner = _load_runner()

    report = runner.run_cases(use_fake_rag=True)

    assert report["offline_constraints"]["calls_llm"] is False
    assert report["rag_enabled"] is True
    assert any(row.get("rag_hit_count", 0) > 0 for row in report["cases"])
    assert all("rag_status" in row for row in report["cases"])
    assert "synthetic safe RAG content" not in json.dumps(report, ensure_ascii=False)


def test_json_only_stdout_is_parseable_json():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json-only"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    assert completed.stderr == ""
    assert report["dry_run"] is False
    assert report["summary"]["failed"] == 0


def test_json_only_stdout_with_sop_file_is_parseable_json():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--sop-file", str(SOP_FIXTURE), "--json-only"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    assert completed.stderr == ""
    assert report["sop_record_count"] == 5
    assert report["summary"]["failed"] == 0


def test_repository_backed_product_cases_cover_required_questions_and_hide_full_details():
    runner = _load_runner()

    report = runner.run_cases()
    categories = {row["category"]: row for row in report["cases"]}
    required_product_categories = {
        "product-price",
        "product-usage",
        "product-ingredients",
        "product-shelf-life",
    }

    assert required_product_categories <= categories.keys()
    for category in required_product_categories:
        row = categories[category]
        assert row["status"] == "passed"
        assert row["action"] == "reply"
        assert row["intent"] == "product_basic"
        assert row["knowledge_hit_count"] > 0
        assert row["knowledge_source"] == "synthetic_product_record"

    rendered = json.dumps(report, ensure_ascii=False)
    product_records = runner.synthetic_product_records()
    full_record_rendered = json.dumps(product_records[0], ensure_ascii=False, sort_keys=True)
    assert full_record_rendered not in rendered
    for key in ("price", "specifications", "usage_method", "ingredients", "shelf_life", "warnings", "manual_notes"):
        assert product_records[0][key] not in rendered


def test_existing_synthetic_category_regression_coverage():
    runner = _load_runner()

    report = runner.run_cases()
    passed_categories = {row["category"] for row in report["cases"] if row["status"] == "passed"}

    assert {
        "redline",
        "explicit-human",
        "after-sales",
        "logistics",
        "promotion",
        "sensitive-user",
        "fallback",
    } <= passed_categories


def test_failure_case_returns_nonzero_and_failed_count(tmp_path):
    runner = _load_runner()
    output_path = tmp_path / "failure_report.json"
    cases = [
        runner.SyntheticCase(
            case_id="T100G-FAIL-001",
            category="negative-test",
            content="完全无法命中的合成问题",
            expected_action="reply",
            expected_intent="product_basic",
            required=True,
        )
    ]

    report = runner.run_cases(cases)
    exit_code = runner.write_report_and_exit(report, output_path=output_path, json_only=True)

    assert exit_code == 1
    assert report["summary"]["failed"] == 1
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["cases"][0]["status"] == "failed"


def test_runner_source_does_not_import_forbidden_runtime_dependencies():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    forbidden_terms = ("SendMessage", "PDDChannel", "start_account", "FastGPTHandler")
    assert all(term not in source for term in forbidden_terms)
    assert "fastgpt_engine" not in source
    assert "Channel.pinduoduo" not in source
