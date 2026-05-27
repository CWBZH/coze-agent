"""Offline comparison harness for InternalWorkflowEngine and FastGPT reports.

This script compares pre-existing JSON reports only. It never calls FastGPT,
opens buyer data, imports channel senders, or sends messages.
"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PASS = "pass"
FAIL = "fail"
UNCLEAR = "unclear"

TRANSFER_LABELS = {
    "transfer",
    "transfer_human",
    "human",
    "manual",
    "manual_transfer",
    "needs_human",
    "human_escalation",
}
REPLY_LABELS = {
    "reply",
    "auto_reply",
    "answered",
    "safe_reply",
    "ok_reply",
}
SKIP_LABELS = {
    "skip",
    "block",
    "blocked",
    "fallback",
    "needs_dataset_update",
}


@dataclass(frozen=True)
class InternalCase:
    case_id: str
    action: str
    intent: str
    status: str
    workflow_version: str
    sop_version: str
    knowledge_version: str
    sop_domain: str
    sop_domains: tuple[str, ...]
    knowledge_source: str
    risk_status: str
    knowledge_status: str
    answer_generator: str
    guardrail_status: str
    used_history_count: int | None


@dataclass(frozen=True)
class FastGPTCase:
    case_id: str
    status: str
    label: str
    intent: str
    risk_status: str
    knowledge_status: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare an internal JSON report with an existing FastGPT JSON report."
    )
    parser.add_argument("--internal-report", type=Path, required=True, help="Internal JSON report path.")
    parser.add_argument("--fastgpt-report", type=Path, help="Existing FastGPT JSON report path.")
    parser.add_argument(
        "--internal-only",
        action="store_true",
        help="Emit an internal baseline when no FastGPT report is available.",
    )
    parser.add_argument("--output", type=Path, help="Write comparison JSON to this path.")
    parser.add_argument("--json-only", action="store_true", help="Print only comparison JSON.")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        help="Minimum required pass rate from 0.0 to 1.0. Exits non-zero when unmet.",
    )
    args = parser.parse_args(argv)
    if args.min_pass_rate is not None and not 0.0 <= args.min_pass_rate <= 1.0:
        parser.error("--min-pass-rate must be between 0.0 and 1.0")
    return args


def load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"{path} must contain a JSON object or list")
    return payload


def load_optional_json(path: Path | None) -> dict[str, Any] | list[Any] | None:
    if path is None or not path.exists():
        return None
    return load_json(path)


def extract_internal_cases(payload: dict[str, Any] | list[Any]) -> list[InternalCase]:
    rows = _extract_rows(payload)
    return [_internal_case(row, index) for index, row in enumerate(rows, start=1)]


def extract_fastgpt_cases(payload: dict[str, Any] | list[Any] | None) -> dict[str, FastGPTCase]:
    if payload is None:
        return {}
    rows = _extract_rows(payload)
    cases = [_fastgpt_case(row, index) for index, row in enumerate(rows, start=1)]
    return {case.case_id: case for case in cases}


def build_comparison(
    internal_payload: dict[str, Any] | list[Any],
    fastgpt_payload: dict[str, Any] | list[Any] | None,
    *,
    internal_only: bool,
    min_pass_rate: float | None = None,
) -> dict[str, Any]:
    internal_cases = extract_internal_cases(internal_payload)
    fastgpt_cases = extract_fastgpt_cases(fastgpt_payload)
    rows = []

    for internal in internal_cases:
        fastgpt = fastgpt_cases.get(internal.case_id)
        dimensions = compare_case(internal, fastgpt, internal_only=internal_only)
        verdict = _overall_verdict(dimensions)
        rows.append(
            {
                "case_id": internal.case_id,
                "internal_action": internal.action,
                "internal_intent": internal.intent,
                "workflow_version": internal.workflow_version,
                "sop_version": internal.sop_version,
                "knowledge_version": internal.knowledge_version,
                "sop_domain": internal.sop_domain,
                "sop_domains": list(internal.sop_domains),
                "knowledge_source": internal.knowledge_source,
                "answer_generator": internal.answer_generator,
                "generation_status": _generation_status(internal),
                "guardrail_status": internal.guardrail_status,
                "history_usage_status": _history_usage_status(internal),
                "version_status": _version_status(internal),
                "fastgpt_status": fastgpt.status if fastgpt else "",
                "fastgpt_label": fastgpt.label if fastgpt else "",
                "intent_match": dimensions["intent_match"],
                "action_match": dimensions["action_match"],
                "risk_status": dimensions["risk_status"],
                "knowledge_status": dimensions["knowledge_status"],
                "verdict": verdict,
            }
        )

    pass_count = sum(1 for row in rows if row["verdict"] == PASS)
    summary: dict[str, Any] = {
        "total": len(rows),
        PASS: pass_count,
        FAIL: sum(1 for row in rows if row["verdict"] == FAIL),
        UNCLEAR: sum(1 for row in rows if row["verdict"] == UNCLEAR),
    }
    if min_pass_rate is not None:
        pass_rate = pass_count / len(rows) if rows else 0.0
        summary["pass_rate"] = round(pass_rate, 6)
        summary["min_pass_rate"] = min_pass_rate
        summary["pass_rate_met"] = pass_rate >= min_pass_rate

    return {
        "runner": "compare_internal_fastgpt",
        "mode": "internal_only" if internal_only or fastgpt_payload is None else "comparison",
        "summary": summary,
        "constraints": {
            "calls_fastgpt": False,
            "uses_existing_fastgpt_report_only": fastgpt_payload is not None,
            "reads_buyer_data": False,
            "outputs_full_reply_text": False,
        },
        "cases": rows,
    }


def compare_case(
    internal: InternalCase,
    fastgpt: FastGPTCase | None,
    *,
    internal_only: bool,
) -> dict[str, str]:
    internal_status = _normalize_status(internal.status)
    if internal_status == FAIL:
        return _all_dimensions(FAIL)
    if internal_status == UNCLEAR:
        return _all_dimensions(UNCLEAR)

    if fastgpt is None:
        return _all_dimensions(PASS if internal_only else UNCLEAR)

    fastgpt_status = _normalize_status(fastgpt.status)
    if fastgpt_status == FAIL:
        return _all_dimensions(FAIL)
    if fastgpt_status == UNCLEAR and not fastgpt.label:
        return _all_dimensions(UNCLEAR)

    return {
        "intent_match": _compare_text_value(internal.intent, fastgpt.intent),
        "action_match": PASS if _labels_compatible(internal.action, fastgpt.label) else FAIL,
        "risk_status": _compare_status_value(internal.risk_status, fastgpt.risk_status),
        "knowledge_status": _compare_status_value(
            internal.knowledge_status, fastgpt.knowledge_status
        ),
    }


def render_report(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def write_report(report: dict[str, Any], *, output: Path | None, json_only: bool) -> None:
    rendered = render_report(report)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")

    if json_only:
        print(rendered)
        return

    summary = report["summary"]
    print(
        "compare_internal_fastgpt: "
        f"pass={summary[PASS]} fail={summary[FAIL]} unclear={summary[UNCLEAR]} total={summary['total']}"
    )
    if output is not None:
        print(f"report={output}")
    else:
        print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    internal_payload = load_json(args.internal_report)
    fastgpt_payload = load_optional_json(args.fastgpt_report)
    internal_only = bool(args.internal_only)
    report = build_comparison(
        internal_payload,
        fastgpt_payload,
        internal_only=internal_only,
        min_pass_rate=args.min_pass_rate,
    )
    write_report(report, output=args.output, json_only=args.json_only)
    if args.min_pass_rate is not None and not report["summary"]["pass_rate_met"]:
        return 1
    return 0


def _extract_rows(payload: dict[str, Any] | list[Any]) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload.get("cases"), list):
        rows = payload["cases"]
    elif isinstance(payload.get("results"), list):
        rows = payload["results"]
    else:
        rows = [payload]

    return [row for row in rows if isinstance(row, Mapping)]


def _internal_case(row: Mapping[str, Any], index: int) -> InternalCase:
    return InternalCase(
        case_id=_text(row.get("case_id") or row.get("id") or f"case-{index}"),
        action=_text(row.get("actual_action") or row.get("action") or row.get("internal_action")),
        intent=_text(row.get("actual_intent") or row.get("intent") or row.get("internal_intent")),
        status=_text(row.get("status") or row.get("verdict") or PASS),
        workflow_version=_text(row.get("workflow_version")),
        sop_version=_text(row.get("sop_version")),
        knowledge_version=_text(row.get("knowledge_version")),
        sop_domain=_text(row.get("sop_domain") or _first_text(row.get("sop_domains"))),
        sop_domains=tuple(_text_list(row.get("sop_domains"))),
        knowledge_source=_text(row.get("knowledge_source")),
        risk_status=_text(row.get("risk_status") or row.get("risk")),
        knowledge_status=_text(row.get("knowledge_status") or row.get("knowledge")),
        answer_generator=_text(row.get("answer_generator")),
        guardrail_status=_text(row.get("guardrail_status")),
        used_history_count=_optional_int(row.get("used_history_count")),
    )


def _fastgpt_case(row: Mapping[str, Any], index: int) -> FastGPTCase:
    return FastGPTCase(
        case_id=_text(row.get("case_id") or row.get("id") or f"case-{index}"),
        status=_text(row.get("status") or row.get("verdict")),
        label=_text(
            row.get("label")
            or row.get("fastgpt_label")
            or row.get("classification")
            or row.get("action")
        ),
        intent=_text(row.get("actual_intent") or row.get("intent") or row.get("fastgpt_intent")),
        risk_status=_text(row.get("risk_status") or row.get("risk")),
        knowledge_status=_text(row.get("knowledge_status") or row.get("knowledge")),
    )


def _normalize_status(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"", "passed", "pass", "ok", "success", "succeeded"}:
        return PASS
    if normalized in {"failed", "fail", "error", "timeout", "crash"}:
        return FAIL
    return UNCLEAR


def _labels_compatible(internal_action: str, fastgpt_label: str) -> bool:
    action = internal_action.strip().lower()
    label = fastgpt_label.strip().lower()

    if action == label:
        return True
    if action == "transfer_human":
        return label in TRANSFER_LABELS
    if action == "request_evidence":
        return label in TRANSFER_LABELS or label in REPLY_LABELS
    if action == "reply":
        return label in REPLY_LABELS
    if action in {"fallback", "skip", "block"}:
        return label in SKIP_LABELS
    return False


def _all_dimensions(value: str) -> dict[str, str]:
    return {
        "intent_match": value,
        "action_match": value,
        "risk_status": value,
        "knowledge_status": value,
    }


def _overall_verdict(dimensions: Mapping[str, str]) -> str:
    values = set(dimensions.values())
    if FAIL in values:
        return FAIL
    if UNCLEAR in values:
        return UNCLEAR
    return PASS


def _compare_text_value(left: str, right: str) -> str:
    if not left or not right:
        return UNCLEAR
    return PASS if left.strip().lower() == right.strip().lower() else FAIL


def _compare_status_value(left: str, right: str) -> str:
    left_status = _normalize_dimension_status(left)
    right_status = _normalize_dimension_status(right)
    if left_status == FAIL or right_status == FAIL:
        return FAIL
    if not left_status and not right_status:
        return PASS
    if not left_status or not right_status:
        return UNCLEAR
    return PASS if left_status == right_status else FAIL


def _version_status(internal: InternalCase) -> str:
    if not internal.workflow_version or not internal.sop_version or not internal.knowledge_version:
        return "missing"
    return PASS


def _generation_status(internal: InternalCase) -> str:
    return "generated" if internal.answer_generator else "missing"


def _history_usage_status(internal: InternalCase) -> str:
    if internal.used_history_count is None:
        return "missing"
    return "used" if internal.used_history_count > 0 else "unused"


def _normalize_dimension_status(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return ""
    if normalized in {
        "pass",
        "passed",
        "ok",
        "safe",
        "supported",
        "grounded",
        "matched",
        "success",
    }:
        return PASS
    if normalized in {
        "fail",
        "failed",
        "unsafe",
        "unsupported",
        "hallucinated",
        "missing",
        "error",
    }:
        return FAIL
    return normalized


def _text_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_text(item) for item in value if _text(item)]
    return []


def _first_text(value: object) -> str:
    values = _text_list(value)
    return values[0] if values else ""


def _text(value: object) -> str:
    return str(value or "").strip()


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
