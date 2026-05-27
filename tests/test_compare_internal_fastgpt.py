import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "compare_internal_fastgpt.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("compare_internal_fastgpt", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


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


def test_internal_only_outputs_baseline(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "cases": [
                {
                    "case_id": "case-1",
                    "actual_action": "reply",
                    "actual_intent": "product_basic",
                    "status": "passed",
                    "reply_text": "FULL_INTERNAL_REPLY_SHOULD_NOT_LEAK",
                }
            ]
        },
    )

    output = json.loads(
        _run_cli("--internal-report", str(internal), "--internal-only", "--json-only")
    )

    assert output["summary"] == {"total": 1, "pass": 1, "fail": 0, "unclear": 0}
    assert output["cases"][0] == {
        "case_id": "case-1",
        "internal_action": "reply",
        "internal_intent": "product_basic",
        "answer_generator": "",
        "generation_status": "missing",
        "guardrail_status": "",
        "history_usage_status": "missing",
        "workflow_version": "",
        "sop_version": "",
        "knowledge_version": "",
        "sop_domain": "",
        "sop_domains": [],
        "knowledge_source": "",
        "version_status": "missing",
        "fastgpt_status": "",
        "fastgpt_label": "",
        "intent_match": "pass",
        "action_match": "pass",
        "risk_status": "pass",
        "knowledge_status": "pass",
        "verdict": "pass",
    }


def test_comparison_preserves_answer_generation_fields(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "cases": [
                {
                    "case_id": "case-1",
                    "action": "reply",
                    "intent": "product_basic",
                    "status": "passed",
                    "answer_generator": "fake",
                    "guardrail_status": "passed",
                    "used_history_count": 1,
                }
            ]
        },
    )

    output = json.loads(
        _run_cli("--internal-report", str(internal), "--internal-only", "--json-only")
    )

    assert output["cases"][0]["answer_generator"] == "fake"
    assert output["cases"][0]["generation_status"] == "generated"
    assert output["cases"][0]["guardrail_status"] == "passed"
    assert output["cases"][0]["history_usage_status"] == "used"


def test_internal_and_fake_fastgpt_report_compare(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "runner": "internal_engine_synthetic_qa",
            "cases": [
                {
                    "case_id": "case-1",
                    "action": "transfer_human",
                    "intent": "human_escalation_redline",
                    "status": "passed",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                },
                {
                    "case_id": "case-2",
                    "action": "reply",
                    "intent": "product_basic",
                    "status": "passed",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                },
            ],
        },
    )
    fastgpt = _write_json(
        tmp_path / "fastgpt.json",
        {
            "cases": [
                {
                    "case_id": "case-1",
                    "status": "passed",
                    "label": "transfer_human",
                    "intent": "human_escalation_redline",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                    "actual_reply": "FULL_FASTGPT_REPLY_SHOULD_NOT_LEAK",
                },
                {
                    "case_id": "case-2",
                    "status": "passed",
                    "label": "needs_dataset_update",
                    "intent": "product_basic",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                },
            ]
        },
    )

    output = json.loads(
        _run_cli(
            "--internal-report",
            str(internal),
            "--fastgpt-report",
            str(fastgpt),
            "--json-only",
        )
    )

    assert output["summary"] == {"total": 2, "pass": 1, "fail": 1, "unclear": 0}
    assert output["cases"][0]["verdict"] == "pass"
    assert output["cases"][0]["intent_match"] == "pass"
    assert output["cases"][0]["action_match"] == "pass"
    assert output["cases"][0]["risk_status"] == "pass"
    assert output["cases"][0]["knowledge_status"] == "pass"
    assert output["cases"][1]["verdict"] == "fail"
    assert "FULL_FASTGPT_REPLY_SHOULD_NOT_LEAK" not in json.dumps(output)


def test_missing_fastgpt_report_does_not_crash(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {"cases": [{"case_id": "case-1", "action": "reply", "intent": "product_basic"}]},
    )

    output = json.loads(
        _run_cli(
            "--internal-report",
            str(internal),
            "--fastgpt-report",
            str(tmp_path / "missing.json"),
            "--json-only",
        )
    )

    assert output["summary"] == {"total": 1, "pass": 0, "fail": 0, "unclear": 1}
    assert output["cases"][0]["verdict"] == "unclear"


def test_single_internal_summary_json_is_supported(tmp_path):
    internal = _write_json(
        tmp_path / "single.json",
        {
            "action": "reply",
            "intent": "logistics_order_status",
            "case_id": "single-case",
            "reply_text": "FULL_INTERNAL_REPLY_SHOULD_NOT_LEAK",
        },
    )

    output = json.loads(
        _run_cli("--internal-report", str(internal), "--internal-only", "--json-only")
    )

    assert output["cases"][0]["case_id"] == "single-case"
    assert output["cases"][0]["internal_action"] == "reply"
    assert output["cases"][0]["internal_intent"] == "logistics_order_status"


def test_json_output_is_parseable_and_omits_full_reply_text(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "cases": [
                {
                    "case_id": "case-secret",
                    "action": "reply",
                    "intent": "product_basic",
                    "reply": "FULL_INTERNAL_REPLY_SHOULD_NOT_LEAK",
                    "actual_reply": "FULL_INTERNAL_ACTUAL_REPLY_SHOULD_NOT_LEAK",
                    "content": "FULL_BUYER_MESSAGE_SHOULD_NOT_LEAK",
                }
            ]
        },
    )

    stdout = _run_cli("--internal-report", str(internal), "--internal-only", "--json-only")
    parsed = json.loads(stdout)

    assert parsed["cases"][0]["case_id"] == "case-secret"
    assert "FULL_INTERNAL_REPLY_SHOULD_NOT_LEAK" not in stdout
    assert "FULL_INTERNAL_ACTUAL_REPLY_SHOULD_NOT_LEAK" not in stdout
    assert "FULL_BUYER_MESSAGE_SHOULD_NOT_LEAK" not in stdout
    assert all("reply" not in row for row in parsed["cases"])
    assert all("actual_reply" not in row for row in parsed["cases"])
    assert all("content" not in row for row in parsed["cases"])


def test_sop_fields_are_preserved_without_reply_text(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "cases": [
                {
                    "case_id": "case-sop",
                    "action": "reply",
                    "intent": "product_basic",
                    "status": "passed",
                    "sop_version": "2026.05",
                    "sop_domains": ["product", "risk"],
                    "knowledge_source": "internal_sop",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                    "reply_text": "FULL_INTERNAL_REPLY_SHOULD_NOT_LEAK",
                }
            ]
        },
    )
    fastgpt = _write_json(
        tmp_path / "fastgpt.json",
        {
            "cases": [
                {
                    "case_id": "case-sop",
                    "label": "reply",
                    "intent": "product_basic",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                    "reply": "FULL_FASTGPT_REPLY_SHOULD_NOT_LEAK",
                }
            ]
        },
    )

    stdout = _run_cli(
        "--internal-report",
        str(internal),
        "--fastgpt-report",
        str(fastgpt),
        "--json-only",
    )
    output = json.loads(stdout)

    assert output["cases"][0]["sop_version"] == "2026.05"
    assert output["cases"][0]["sop_domains"] == ["product", "risk"]
    assert output["cases"][0]["knowledge_source"] == "internal_sop"
    assert output["cases"][0]["knowledge_status"] == "pass"
    assert "FULL_INTERNAL_REPLY_SHOULD_NOT_LEAK" not in stdout
    assert "FULL_FASTGPT_REPLY_SHOULD_NOT_LEAK" not in stdout


def test_versioned_internal_report_fields_are_preserved(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "cases": [
                {
                    "case_id": "case-versioned",
                    "action": "reply",
                    "intent": "product_basic",
                    "workflow_version": "wf-2026.05.21",
                    "sop_version": "sop-2026.05",
                    "knowledge_version": "kb-42",
                    "sop_domain": "product",
                    "knowledge_source": "internal_kb",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                }
            ]
        },
    )

    output = json.loads(
        _run_cli("--internal-report", str(internal), "--internal-only", "--json-only")
    )

    row = output["cases"][0]
    assert row["workflow_version"] == "wf-2026.05.21"
    assert row["sop_version"] == "sop-2026.05"
    assert row["knowledge_version"] == "kb-42"
    assert row["sop_domain"] == "product"
    assert row["knowledge_source"] == "internal_kb"
    assert row["version_status"] == "pass"
    assert row["intent_match"] == "pass"
    assert row["action_match"] == "pass"
    assert row["risk_status"] == "pass"
    assert row["knowledge_status"] == "pass"


def test_missing_version_fields_are_marked_missing_without_crashing(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "cases": [
                {
                    "case_id": "case-missing-version",
                    "action": "reply",
                    "intent": "product_basic",
                    "risk_status": "safe",
                    "knowledge_status": "supported",
                }
            ]
        },
    )

    output = json.loads(
        _run_cli("--internal-report", str(internal), "--internal-only", "--json-only")
    )

    row = output["cases"][0]
    assert row["workflow_version"] == ""
    assert row["sop_version"] == ""
    assert row["knowledge_version"] == ""
    assert row["sop_domain"] == ""
    assert row["knowledge_source"] == ""
    assert row["version_status"] == "missing"
    assert row["verdict"] == "pass"


def test_min_pass_rate_returns_non_zero_when_below_threshold(tmp_path):
    internal = _write_json(
        tmp_path / "internal.json",
        {
            "cases": [
                {"case_id": "case-1", "action": "reply", "intent": "product_basic"},
                {"case_id": "case-2", "action": "reply", "intent": "product_basic"},
            ]
        },
    )
    fastgpt = _write_json(
        tmp_path / "fastgpt.json",
        {
            "cases": [
                {"case_id": "case-1", "label": "reply", "intent": "product_basic"},
                {"case_id": "case-2", "label": "needs_dataset_update", "intent": "product_basic"},
            ]
        },
    )

    stdout = _run_cli(
        "--internal-report",
        str(internal),
        "--fastgpt-report",
        str(fastgpt),
        "--min-pass-rate",
        "0.75",
        "--json-only",
        expected_returncode=1,
    )
    output = json.loads(stdout)

    assert output["summary"]["pass_rate"] == 0.5
    assert output["summary"]["min_pass_rate"] == 0.75
    assert output["summary"]["pass_rate_met"] is False


def test_module_never_imports_fastgpt_or_buyer_data_paths():
    module = _load_script_module()
    source = SCRIPT.read_text(encoding="utf-8")

    assert not hasattr(module, "FastGPTHandler")
    assert "FastGPTHandler" not in source
    assert "Message.handlers.fastgpt_handler" not in source
    assert "buyer_data." not in source.lower()
    assert "buyer_data/" not in source.lower()
    assert "buyer_data\\" not in source.lower()
