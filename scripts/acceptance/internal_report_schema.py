"""Canonical internal acceptance report schema.

The schema is intentionally metadata-only. It allows synthetic, dry-run, and
comparison acceptance reports to be shared without full buyer text, replies,
SOP bodies, product details, raw prompts/responses, or secrets.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = "internal-report-v1"

SUPPORTED_REPORT_TYPES = frozenset({"synthetic", "dry-run", "comparison"})

REQUIRED_TOP_LEVEL_FIELDS = (
    "report_type",
    "schema_version",
    "generated_at",
    "backend",
    "workflow_version",
    "sop_version",
    "knowledge_version",
    "shop_id_hash",
    "case_count",
    "passed",
    "failed",
    "unclear",
    "results",
)

REQUIRED_RESULT_FIELDS = (
    "case_id",
    "category",
    "priority",
    "action",
    "intent",
    "reason",
    "risk_flags",
    "knowledge_source",
    "knowledge_hit_count",
    "sop_domain",
    "sop_version",
    "knowledge_version",
    "workflow_version",
    "guardrail_status",
    "verdict",
    "errors",
)

FORBIDDEN_FIELDS = frozenset(
    {
        "content",
        "reply_text",
        "raw_prompt",
        "raw_response",
        "raw_chunk",
        "raw_db_row",
        "raw_vector",
        "full_sop",
        "full_product_detail",
        "full_chunk_content",
        "full_answer",
        "pg_dsn",
        "api_key",
        "token",
        "cookie",
        "authorization",
    }
)


def validate_report_schema(report: Any) -> list[str]:
    """Return schema violations for a canonical internal acceptance report."""
    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["report must be a JSON object"]

    _check_forbidden_fields(report, "$", errors)
    _check_required_mapping(report, REQUIRED_TOP_LEVEL_FIELDS, "$", errors)
    _check_supported_report_type(report, errors)
    _check_schema_version(report, errors)
    _check_non_negative_ints(report, ("case_count", "passed", "failed", "unclear"), "$", errors)
    _check_results(report, errors)
    return errors


def scan_json_payload_for_forbidden_fields(payload: Any) -> list[str]:
    """Return forbidden raw-field violations for a JSON-compatible payload."""
    errors: list[str] = []
    _check_forbidden_fields(payload, "$", errors)
    return errors


def _check_required_mapping(
    value: Mapping[str, Any],
    required_fields: tuple[str, ...],
    path: str,
    errors: list[str],
) -> None:
    for field in required_fields:
        if field not in value:
            errors.append(f"{path}.{field} is required")


def _check_supported_report_type(report: Mapping[str, Any], errors: list[str]) -> None:
    report_type = report.get("report_type")
    if report_type not in SUPPORTED_REPORT_TYPES:
        expected = ", ".join(sorted(SUPPORTED_REPORT_TYPES))
        errors.append(f"$.report_type must be one of: {expected}")


def _check_schema_version(report: Mapping[str, Any], errors: list[str]) -> None:
    schema_version = report.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        errors.append(f"$.schema_version must be {SCHEMA_VERSION!r}")


def _check_non_negative_ints(
    value: Mapping[str, Any],
    fields: tuple[str, ...],
    path: str,
    errors: list[str],
) -> None:
    for field in fields:
        if field not in value:
            continue
        field_value = value[field]
        if not isinstance(field_value, int) or isinstance(field_value, bool) or field_value < 0:
            errors.append(f"{path}.{field} must be a non-negative integer")


def _check_results(report: Mapping[str, Any], errors: list[str]) -> None:
    results = report.get("results")
    if not isinstance(results, list):
        errors.append("$.results must be a list")
        return

    case_count = report.get("case_count")
    if isinstance(case_count, int) and not isinstance(case_count, bool) and case_count != len(results):
        errors.append("$.case_count must equal len($.results)")

    for index, result in enumerate(results):
        path = f"$.results[{index}]"
        if not isinstance(result, Mapping):
            errors.append(f"{path} must be a JSON object")
            continue
        _check_required_mapping(result, REQUIRED_RESULT_FIELDS, path, errors)
        _check_non_negative_ints(result, ("knowledge_hit_count",), path, errors)
        if "risk_flags" in result and not isinstance(result["risk_flags"], list):
            errors.append(f"{path}.risk_flags must be a list")
        if "errors" in result and not isinstance(result["errors"], list):
            errors.append(f"{path}.errors must be a list")


def _check_forbidden_fields(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in FORBIDDEN_FIELDS:
                errors.append(f"{child_path} is forbidden")
            _check_forbidden_fields(child, child_path, errors)
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            _check_forbidden_fields(child, f"{path}[{index}]", errors)
