import copy
import importlib.util
from pathlib import Path


SCHEMA_PATH = Path("scripts/acceptance/internal_report_schema.py")


def _load_schema():
    spec = importlib.util.spec_from_file_location("internal_report_schema", SCHEMA_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _base_result(**overrides):
    result = {
        "case_id": "case-1",
        "category": "product-basic",
        "priority": "p0",
        "action": "reply",
        "intent": "product_basic",
        "reason": "matched_product_question",
        "risk_flags": [],
        "knowledge_source": "repository",
        "knowledge_hit_count": 1,
        "sop_domain": "",
        "sop_version": "sop-test-v1",
        "knowledge_version": "product_repository",
        "workflow_version": "internal-v1",
        "guardrail_status": "passed",
        "verdict": "passed",
        "errors": [],
    }
    result.update(overrides)
    return result


def _base_report(report_type="synthetic", **overrides):
    report = {
        "report_type": report_type,
        "schema_version": "internal-report-v1",
        "generated_at": "2026-05-21T00:00:00Z",
        "backend": "internal",
        "workflow_version": "internal-v1",
        "sop_version": "sop-test-v1",
        "knowledge_version": "product_repository",
        "shop_id_hash": "abc123",
        "case_count": 1,
        "passed": 1,
        "failed": 0,
        "unclear": 0,
        "results": [_base_result()],
    }
    report.update(overrides)
    return report


def test_valid_synthetic_report_passes():
    schema = _load_schema()

    assert schema.validate_report_schema(_base_report("synthetic")) == []


def test_valid_report_allows_answer_generation_metadata():
    schema = _load_schema()
    report = _base_report("synthetic")
    report["results"][0].update(
        {
            "answer_generator": "fake",
            "answer_generation_source": "fake",
            "answer_generation_status": "ok",
            "answer_confidence": 0.82,
            "answer_length": 42,
            "answer_hash": "abc123",
            "answer_preview_truncated": "short preview",
            "used_history_count": 1,
            "used_rag_hit_count": 1,
            "prompt_hash": "abc123",
            "calls_llm": False,
        }
    )

    assert schema.validate_report_schema(report) == []


def test_valid_report_allows_rag_smoke_metadata():
    schema = _load_schema()
    report = _base_report("synthetic")
    report.update(
        {
            "rag_status": "ok",
            "vector_store": "in_memory",
            "embedding_model": "bge-m3",
            "chunk_count": 6,
            "retrieval_hit_count": 1,
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    )
    report["results"][0].update(
        {
            "rag_status": "ok",
            "vector_store": "in_memory",
            "embedding_model": "bge-m3",
            "chunk_count": 6,
            "retrieval_hit_count": 1,
        }
    )

    assert schema.validate_report_schema(report) == []


def test_valid_report_allows_rag_e2e_metadata():
    schema = _load_schema()
    report = _base_report("dry-run")
    report["results"][0].update(
        {
            "rag_e2e_profile": True,
            "rag_e2e_status": "ok",
            "rag_required": True,
            "rag_requirement_status": "passed",
            "answer_generator_required": "fake",
            "answer_generation_status": "ok",
            "guardrail_required": False,
            "guardrail_requirement_status": "not_required",
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    )

    assert schema.validate_report_schema(report) == []


def test_valid_report_allows_rag_version_pinning_metadata():
    schema = _load_schema()
    report = _base_report("dry-run")
    report["results"][0].update(
        {
            "rag_version_pinned": True,
            "rag_expected_version": "sop-test-v1",
            "rag_hit_versions": ["sop-test-v1"],
            "rag_version_status": "passed",
            "rag_shop_status": "passed",
            "rag_source_type_status": "passed",
            "rag_hit_content_hashes": ["abc123"],
            "rag_hit_source_types": ["sop"],
            "rag_hit_source_ids_hash": ["def456"],
        }
    )

    assert schema.validate_report_schema(report) == []


def test_valid_dry_run_report_passes():
    schema = _load_schema()
    report = _base_report(
        "dry-run",
        backend="internal",
        passed=0,
        results=[
            _base_result(
                action="dry_run",
                intent="",
                reason="engine_not_executed",
                knowledge_source="not_executed",
                knowledge_hit_count=0,
                guardrail_status="not_executed",
                verdict="unclear",
            )
        ],
    )

    assert schema.validate_report_schema(report) == []


def test_valid_comparison_report_passes():
    schema = _load_schema()
    report = _base_report(
        "comparison",
        backend="internal_vs_fastgpt_report",
        results=[
            _base_result(
                action="reply",
                intent="product_basic",
                reason="internal_and_fastgpt_match",
                knowledge_source="comparison_report",
                guardrail_status="matched",
                verdict="passed",
            )
        ],
    )

    assert schema.validate_report_schema(report) == []


def test_missing_required_field_fails():
    schema = _load_schema()
    report = _base_report()
    del report["backend"]

    errors = schema.validate_report_schema(report)

    assert any("backend" in error for error in errors)


def test_forbidden_raw_field_fails():
    schema = _load_schema()
    report = _base_report()
    report["results"][0]["reply_text"] = "FULL_REPLY_SHOULD_NOT_BE_ALLOWED"

    errors = schema.validate_report_schema(report)

    assert any("reply_text" in error for error in errors)


def test_forbidden_rag_raw_fields_fail():
    schema = _load_schema()
    report = _base_report()
    report["results"][0]["raw_chunk"] = "private chunk"
    report["results"][0]["full_chunk_content"] = "private chunk"
    report["results"][0]["full_answer"] = "private answer"
    report["results"][0]["raw_vector"] = [0.1, 0.2]
    report["results"][0]["pg_dsn"] = "masked"

    errors = schema.validate_report_schema(report)

    assert any("raw_chunk" in error for error in errors)
    assert any("full_chunk_content" in error for error in errors)
    assert any("full_answer" in error for error in errors)
    assert any("raw_vector" in error for error in errors)
    assert any("pg_dsn" in error for error in errors)


def test_schema_version_exists():
    schema = _load_schema()

    assert schema.SCHEMA_VERSION
    assert "schema_version" in schema.REQUIRED_TOP_LEVEL_FIELDS


def test_no_raw_content_fields():
    schema = _load_schema()
    report = _base_report()
    report["metadata"] = {
        "nested": {
            "content": "FULL_BUYER_MESSAGE_SHOULD_NOT_BE_ALLOWED",
        }
    }

    errors = schema.validate_report_schema(report)

    assert any("content" in error for error in errors)


def test_valid_report_is_not_mutated():
    schema = _load_schema()
    report = _base_report()
    original = copy.deepcopy(report)

    schema.validate_report_schema(report)

    assert report == original
