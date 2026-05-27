"""Build metadata-only replay benchmarks from answerable candidate pools."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_DOMAINS = (
    "product_basic",
    "logistics_policy",
    "after_sales_evidence",
    "promotion_policy",
    "redline_escalation",
    "sensitive_user_safety",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build sanitized curated replay benchmark files.")
    parser.add_argument("--build-benchmark-from-candidates", action="store_true")
    parser.add_argument("--build-benchmark-from-labels", action="store_true")
    parser.add_argument("--candidate-input", type=Path)
    parser.add_argument("--candidate-private-input", type=Path)
    parser.add_argument("--label-input", type=Path)
    parser.add_argument("--benchmark-output", type=Path)
    parser.add_argument("--include-domain", action="append", default=[])
    parser.add_argument("--include-status", default="approved")
    parser.add_argument("--max-per-domain", type=int, default=10)
    parser.add_argument("--min-per-domain", type=int, default=0)
    parser.add_argument("--allow-missing-domain", action="store_true")
    parser.add_argument("--include-private-locator", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def build_benchmark_from_labels(args: argparse.Namespace) -> dict[str, Any]:
    rows = _load_label_rows(getattr(args, "label_input", None))
    private_index = _load_private_candidate_index(getattr(args, "candidate_private_input", None))
    include_status = str(getattr(args, "include_status", "approved") or "approved")
    max_per_domain = max(1, int(getattr(args, "max_per_domain", 10) or 10))
    cases: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    approved_count = 0
    invalid_label_count = 0
    for row in rows:
        if str(row.get("label_status") or "").strip() != include_status:
            continue
        approved_count += 1
        domain = str(row.get("human_expected_domain") or "").strip()
        action_family = str(row.get("human_expected_action_family") or "").strip()
        message_hash = str(row.get("message_hash") or "").strip()
        if not domain or not action_family or not message_hash:
            invalid_label_count += 1
            continue
        if counts.get(domain, 0) >= max_per_domain:
            continue
        case = _case_from_label(row, domain, action_family, message_hash)
        if bool(getattr(args, "include_private_locator", False)):
            locator_entry = _match_private_locator(row, message_hash, private_index)
            if locator_entry:
                case["replay_locator"] = dict(locator_entry.get("replay_locator") or {})
                case["replay_locator_hash"] = str(locator_entry.get("replay_locator_hash") or "")
                case["locator_version"] = str(locator_entry.get("locator_version") or "replay-locator-v1")
        cases.append(case)
        counts[domain] = counts.get(domain, 0) + 1

    include_domains = [str(item) for item in (getattr(args, "include_domain", []) or []) if str(item or "").strip()]
    if not include_domains:
        include_domains = list(DEFAULT_DOMAINS)
    missing_domains = [domain for domain in include_domains if counts.get(domain, 0) < int(getattr(args, "min_per_domain", 0) or 0)]
    if not missing_domains:
        missing_domains = [domain for domain in include_domains if counts.get(domain, 0) == 0]
    payload = {
        "status": "passed" if (cases or bool(getattr(args, "allow_missing_domain", False))) else "failed",
        "benchmark_version": "curated-replay-v1",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "labels_total": len(rows),
        "approved_count": approved_count,
        "benchmark_case_count": len(cases),
        "case_count": len(cases),
        "invalid_label_count": invalid_label_count,
        "locator_attached_count": sum(1 for case in cases if isinstance(case.get("replay_locator"), Mapping) and case.get("replay_locator")),
        "locator_missing_count": sum(1 for case in cases if not case.get("replay_locator")),
        "domain_counts": counts,
        "shop_counts": _counts(case.get("shop_id_hash") for case in cases),
        "missing_domains": missing_domains,
        "cases": cases,
    }
    _maybe_write_benchmark(payload, getattr(args, "benchmark_output", None))
    return payload


def build_benchmark_from_candidates(args: argparse.Namespace) -> dict[str, Any]:
    pool = _load_candidate_pool(getattr(args, "candidate_input", None))
    candidates = [candidate for candidate in pool.get("candidates", []) if isinstance(candidate, Mapping)]
    include_domains = [str(item) for item in (getattr(args, "include_domain", []) or []) if str(item or "").strip()]
    if not include_domains:
        include_domains = list(DEFAULT_DOMAINS)
    max_per_domain = max(1, int(getattr(args, "max_per_domain", 10) or 10))

    cases: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for candidate in candidates:
        domain = str(candidate.get("predicted_domain") or "")
        if domain not in include_domains:
            continue
        if counts.get(domain, 0) >= max_per_domain:
            continue
        case = _case_from_candidate(candidate, domain)
        if case:
            cases.append(case)
            counts[domain] = counts.get(domain, 0) + 1

    missing_domains = [domain for domain in include_domains if counts.get(domain, 0) < int(getattr(args, "min_per_domain", 0) or 0)]
    if not missing_domains:
        missing_domains = [domain for domain in include_domains if counts.get(domain, 0) == 0]
    source_hash = _stable_hash(json.dumps(_sanitized_pool_for_hash(pool), sort_keys=True, ensure_ascii=False))
    payload = {
        "status": "passed" if (cases or bool(getattr(args, "allow_missing_domain", False))) else "failed",
        "benchmark_version": "curated-replay-v1",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "case_count": len(cases),
        "domain_counts": counts,
        "shop_counts": _counts(case.get("shop_id_hash") for case in cases),
        "missing_domains": missing_domains,
        "source_candidate_pool_hash": source_hash,
        "cases": cases,
    }
    _maybe_write_benchmark(payload, getattr(args, "benchmark_output", None))
    return payload


def _load_label_rows(path: Path | None) -> list[dict[str, str]]:
    if not path:
        return [
            {
                "label_id": "synthetic-label-1",
                "message_hash": _stable_hash("synthetic-label"),
                "shop_id_hash": _stable_hash("synthetic-shop-1"),
                "session_id_hash": _stable_hash("synthetic-session-1"),
                "buyer_id_hash": _stable_hash("synthetic-buyer-1"),
                "human_expected_domain": "logistics_policy",
                "human_expected_action_family": "reply",
                "requires_rag": "true",
                "requires_answer": "true",
                "allow_transfer_human": "false",
                "allow_request_evidence": "false",
                "allow_guardrail_blocked": "false",
                "priority": "p2",
                "label_status": "approved",
            }
        ]
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_private_candidate_index(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if not path or not Path(path).exists():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        for key in (
            str(candidate.get("label_id") or ""),
            str(candidate.get("candidate_id") or ""),
            str(candidate.get("message_hash") or ""),
            "|".join(
                [
                    str(candidate.get("session_id_hash") or ""),
                    str(candidate.get("buyer_id_hash") or ""),
                    str(candidate.get("message_hash") or ""),
                ]
            ),
        ):
            if key:
                index.setdefault(key, []).append(candidate)
    return index


def _match_private_locator(
    row: Mapping[str, Any],
    message_hash: str,
    private_index: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    keys = [
        str(row.get("label_id") or ""),
        str(row.get("candidate_id") or ""),
        message_hash,
        "|".join(
            [
                str(row.get("session_id_hash") or ""),
                str(row.get("buyer_id_hash") or ""),
                message_hash,
            ]
        ),
    ]
    for key in keys:
        matches = private_index.get(key) or []
        for match in matches:
            if match.get("replay_locator"):
                return match
    return {}


def _case_from_label(row: Mapping[str, Any], domain: str, action_family: str, message_hash: str) -> dict[str, Any]:
    label_id = str(row.get("label_id") or "")
    seed = "|".join([label_id, message_hash, domain, action_family])
    return {
        "case_id": "label-replay-" + _stable_hash(seed)[:16],
        "label_id": label_id,
        "message_hash": message_hash,
        "shop_id_hash": str(row.get("shop_id_hash") or ""),
        "session_id_hash": str(row.get("session_id_hash") or ""),
        "buyer_id_hash": str(row.get("buyer_id_hash") or ""),
        "expected_domain": domain,
        "expected_action_family": action_family,
        "requires_rag": _bool(row.get("requires_rag")),
        "requires_answer": _bool(row.get("requires_answer")),
        "allow_transfer_human": _bool(row.get("allow_transfer_human")),
        "allow_request_evidence": _bool(row.get("allow_request_evidence")),
        "allow_guardrail_blocked": _bool(row.get("allow_guardrail_blocked")),
        "priority": str(row.get("priority") or "p2"),
        "notes": "",
    }


def _maybe_write_benchmark(payload: dict[str, Any], output: Path | None) -> None:
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        payload["benchmark_written"] = True
        payload["benchmark_output_hash"] = _stable_hash(str(path))
    else:
        payload["benchmark_written"] = False


def _load_candidate_pool(path: Path | None) -> dict[str, Any]:
    if not path:
        return {
            "summary": {"selected_total": 1},
            "candidates": [
                {
                    "candidate_id": "synthetic-candidate-1",
                    "message_hash": _stable_hash("synthetic"),
                    "shop_id_hash": _stable_hash("synthetic-shop-1"),
                    "session_id_hash": _stable_hash("synthetic-session-1"),
                    "buyer_id_hash": _stable_hash("synthetic-buyer-1"),
                    "predicted_domain": "logistics_policy",
                    "source": "history",
                }
            ],
        }
    if not Path(path).exists():
        return {"summary": {"status": "missing"}, "candidates": []}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _case_from_candidate(candidate: Mapping[str, Any], domain: str) -> dict[str, Any]:
    message_hash = str(candidate.get("message_hash") or "")
    candidate_id = str(candidate.get("candidate_id") or "")
    if not message_hash:
        return {}
    seed = "|".join([candidate_id, message_hash, domain])
    return {
        "case_id": "replay-" + _stable_hash(seed)[:16],
        "candidate_id": candidate_id,
        "shop_id_hash": str(candidate.get("shop_id_hash") or ""),
        "session_id_hash": str(candidate.get("session_id_hash") or ""),
        "buyer_id_hash": str(candidate.get("buyer_id_hash") or ""),
        "message_hash": message_hash,
        "expected_domain": domain,
        "expected_action_family": _expected_action_family(domain),
        "requires_rag": domain in {"product_basic", "logistics_policy", "promotion_policy"},
        "requires_answer": domain not in {"redline_escalation", "after_sales_evidence"},
        "allow_transfer_human": domain in {"redline_escalation", "sensitive_user_safety"},
        "allow_request_evidence": domain == "after_sales_evidence",
        "allow_guardrail_blocked": domain in {"redline_escalation", "sensitive_user_safety"},
        "priority": "p1" if domain in {"redline_escalation", "after_sales_evidence"} else "p2",
        "notes": "",
    }


def _expected_action_family(domain: str) -> str:
    if domain == "redline_escalation":
        return "transfer_human_or_blocked"
    if domain == "after_sales_evidence":
        return "request_evidence_or_reply"
    if domain == "sensitive_user_safety":
        return "safe_reply_or_transfer"
    return "reply"


def _sanitized_pool_for_hash(pool: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "summary": pool.get("summary", {}),
        "candidates": [
            {
                "candidate_id": candidate.get("candidate_id"),
                "message_hash": candidate.get("message_hash"),
                "predicted_domain": candidate.get("predicted_domain"),
                "shop_id_hash": candidate.get("shop_id_hash"),
            }
            for candidate in pool.get("candidates", [])
            if isinstance(candidate, Mapping)
        ],
    }


def _stable_hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _counts(values: Sequence[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        text = str(value or "")
        if not text:
            continue
        result[text] = result.get(text, 0) + 1
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_benchmark_from_labels(args) if args.build_benchmark_from_labels else build_benchmark_from_candidates(args)
    print(json.dumps(_stdout_payload(payload), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("status") != "failed" else 1


def _stdout_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    safe = dict(payload)
    safe_cases: list[dict[str, Any]] = []
    for case in payload.get("cases", []) or []:
        if not isinstance(case, Mapping):
            continue
        safe_case = {key: value for key, value in case.items() if key != "replay_locator"}
        if case.get("replay_locator"):
            safe_case["replay_locator_attached"] = True
        safe_cases.append(safe_case)
    if safe_cases:
        safe["cases"] = safe_cases
    return safe


if __name__ == "__main__":
    raise SystemExit(main())
