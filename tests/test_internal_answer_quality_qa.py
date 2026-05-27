import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_answer_quality_qa.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("internal_answer_quality_qa", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_fake_answer_quality_qa_runs():
    runner = _load_runner()

    payload = runner.run_qa(runner.parse_args(["--max-cases", "6"]))

    assert payload["status"] == "passed"
    assert payload["total"] == 6
    assert payload["failed"] == 0
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_case_id_domain_and_max_cases_filters_work():
    runner = _load_runner()

    payload = runner.run_qa(
        runner.parse_args(["--domain", "logistics_policy", "--case-id", "aq-logistics-001", "--max-cases", "1"])
    )

    assert payload["total"] == 1
    assert payload["results"][0]["case_id"] == "aq-logistics-001"
    assert payload["results"][0]["category"] == "logistics_policy"


def test_product_version_override_does_not_affect_sop_cases():
    runner = _load_runner()

    product_payload = runner.run_qa(
        runner.parse_args(["--case-id", "aq-product-001", "--product-version", "real-product-v1"])
    )
    sop_payload = runner.run_qa(
        runner.parse_args(["--case-id", "aq-logistics-001", "--product-version", "real-product-v1"])
    )

    assert product_payload["results"][0]["expected_version"] == "real-product-v1"
    assert product_payload["product_version"] == "real-product-v1"
    assert sop_payload["results"][0]["expected_version"] == "sop-test-v1"
    assert sop_payload["sop_version"] == "sop-test-v1"


def test_real_mode_missing_args_fails_without_external_calls():
    runner = _load_runner()

    payload = runner.run_qa(runner.parse_args(["--real-rag", "--real-llm", "--max-cases", "1"]))

    assert payload["status"] == "error"
    assert payload["failed"] == 1
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_forbidden_phrase_detection_marks_failure():
    runner = _load_runner()
    case = runner._filter_cases(runner.parse_args(["--case-id", "aq-after-sales-001"]))[0]

    errors = runner._evaluate(
        case,
        {
            "action": "request_evidence",
            "intent": "after_sales_evidence_collection",
            "rag_domains": ["after_sales_evidence"],
            "rag_hit_versions": ["sop-test-v1"],
            "rag_hit_source_types": ["sop"],
            "guardrail_status": "safe",
            "answer_length": 20,
        },
        "We approved a refund and replacement.",
    )

    assert "forbidden_phrase_detected" in errors


def test_negated_forbidden_phrase_does_not_fail():
    runner = _load_runner()
    case = runner._filter_cases(runner.parse_args(["--case-id", "aq-promotion-005"]))[0]

    errors = runner._evaluate(
        case,
        {
            "action": "reply",
            "intent": "promotion_policy",
            "rag_domains": ["promotion_policy"],
            "rag_hit_versions": ["sop-test-v1"],
            "rag_hit_source_types": ["sop"],
            "guardrail_status": "safe",
            "answer_length": 20,
        },
        "平台活动以页面为准，不提供私下优惠，也不会赠送赠品。",
    )

    assert "forbidden_phrase_detected" not in errors


def test_neutral_page_rule_for_gift_does_not_fail():
    runner = _load_runner()
    case = runner._filter_cases(runner.parse_args(["--case-id", "aq-promotion-002"]))[0]

    errors = runner._evaluate(
        case,
        {
            "action": "reply",
            "intent": "promotion_policy",
            "rag_domains": ["promotion_policy"],
            "rag_hit_versions": ["sop-test-v1"],
            "rag_hit_source_types": ["sop"],
            "guardrail_status": "safe",
            "answer_length": 20,
        },
        "赠品信息请以商品页面、活动页面或结算页显示规则为准。",
    )

    assert "forbidden_phrase_detected" not in errors


def test_direct_forbidden_commitment_still_fails():
    runner = _load_runner()
    case = runner._filter_cases(runner.parse_args(["--case-id", "aq-after-sales-001"]))[0]

    errors = runner._evaluate(
        case,
        {
            "action": "request_evidence",
            "intent": "after_sales_evidence_collection",
            "rag_domains": ["after_sales_evidence"],
            "rag_hit_versions": ["sop-test-v1"],
            "rag_hit_source_types": ["sop"],
            "guardrail_status": "safe",
            "answer_length": 20,
        },
        "可以补发，也给你赔偿。",
    )

    assert "forbidden_phrase_detected" in errors


def test_source_type_mismatch_fails():
    runner = _load_runner()
    case = runner._filter_cases(runner.parse_args(["--case-id", "aq-product-001"]))[0]

    errors = runner._evaluate(
        case,
        {
            "action": "reply",
            "intent": "product_basic",
            "rag_domains": ["product_catalog"],
            "rag_hit_versions": ["product-test-v1"],
            "rag_hit_source_types": ["sop"],
            "guardrail_status": "safe",
            "answer_length": 20,
        },
        "价格以页面为准。",
    )

    assert "source_type_mismatch" in errors


def test_redline_without_transfer_fails():
    runner = _load_runner()
    case = runner._filter_cases(runner.parse_args(["--case-id", "aq-redline-001"]))[0]

    errors = runner._evaluate(
        case,
        {
            "action": "reply",
            "intent": "human_escalation_redline",
            "rag_domains": [],
            "rag_hit_versions": [],
            "rag_hit_source_types": [],
            "guardrail_status": "safe",
            "answer_length": 10,
        },
        "safe",
    )

    assert "action_mismatch" in errors
    assert "p0_redline_not_transferred" in errors


def test_cli_json_does_not_contain_full_message_or_prompt():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--case-id", "aq-logistics-001", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["total"] == 1
    assert "为什么还没到" not in completed.stdout
    assert "raw_prompt" not in completed.stdout
    assert "raw_response" not in completed.stdout


def test_sensitive_blocked_transfer_is_allowed():
    runner = _load_runner()
    case = runner._filter_cases(runner.parse_args(["--case-id", "aq-sensitive-005"]))[0]

    errors = runner._evaluate(
        case,
        {
            "action": "transfer_human",
            "intent": "sensitive_user_safety",
            "rag_domains": ["sensitive_user_safety"],
            "rag_hit_versions": ["sop-test-v1"],
            "rag_hit_source_types": ["sop"],
            "guardrail_status": "blocked",
            "answer_length": 0,
        },
        "",
    )

    assert "action_mismatch" not in errors
    assert "guardrail_mismatch" not in errors
