"""Create a local, private manual-labeling pack for replay benchmark curation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.acceptance import internal_conversation_replay as replay


OUTPUT_ROOT = REPO_ROOT / "temp" / "manual_labeling"
CSV_FIELDS = [
    "label_id",
    "shop_id_hash",
    "buyer_id_hash",
    "session_id_hash",
    "message_id_hash",
    "message_hash",
    "message_preview_truncated",
    "message_length",
    "created_at_bucket",
    "pending_human",
    "selector_predicted_domain",
    "selector_score",
    "exclusion_reason",
    "human_expected_domain",
    "human_expected_action_family",
    "requires_rag",
    "requires_answer",
    "allow_transfer_human",
    "allow_request_evidence",
    "allow_guardrail_blocked",
    "priority",
    "label_status",
    "label_notes",
]

BROAD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "after_sales_evidence": (
        "\u574f\u4e86",
        "\u7834\u4e86",
        "\u788e\u4e86",
        "\u6f0f\u4e86",
        "\u6f0f\u6db2",
        "\u5c11\u4e86",
        "\u5c11\u53d1",
        "\u6ca1\u6536\u5230",
        "\u53d1\u9519",
        "\u9519\u53d1",
        "\u62cd\u7167",
        "\u9000\u6362",
        "\u552e\u540e",
    ),
    "promotion_policy": (
        "\u4fbf\u5b9c",
        "\u4f18\u60e0",
        "\u4f18\u60e0\u5238",
        "\u6d3b\u52a8",
        "\u8d60\u54c1",
        "\u793c\u54c1",
        "\u8fd4\u5dee\u4ef7",
        "\u5dee\u4ef7",
        "\u7acb\u51cf",
        "\u6ee1\u51cf",
        "\u79c1\u4e0b",
    ),
    "redline_escalation": (
        "\u5047\u8d27",
        "\u6295\u8bc9",
        "12315",
        "\u8d54\u507f",
        "\u66dd\u5149",
        "\u5e73\u53f0\u4ecb\u5165",
        "\u7ef4\u6743",
        "\u4e3e\u62a5",
        "\u5de5\u5546",
    ),
    "sensitive_user_safety": (
        "\u5b55\u5987",
        "\u5b9d\u5b9d",
        "\u5c0f\u5b69",
        "\u513f\u7ae5",
        "\u8fc7\u654f",
        "\u654f\u611f\u808c",
        "\u75d8",
        "\u6cbb\u75d8",
        "\u533b\u751f",
        "\u6fc0\u7d20",
        "\u5b89\u5168\u5417",
    ),
    "logistics_policy": (
        "\u5feb\u9012",
        "\u7269\u6d41",
        "\u53d1\u8d27",
        "\u5230\u54ea\u4e86",
        "\u6ca1\u66f4\u65b0",
        "\u4ec0\u4e48\u65f6\u5019\u5230",
        "\u6d3e\u9001",
        "\u63fd\u6536",
    ),
    "product_basic": (
        "\u89c4\u683c",
        "\u6210\u5206",
        "\u600e\u4e48\u7528",
        "\u7528\u6cd5",
        "\u4fdd\u8d28\u671f",
        "\u591a\u5c11\u94b1",
        "\u4ef7\u683c",
        "\u9002\u5408",
        "\u6548\u679c",
    ),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export metadata-safe manual labeling files under temp/manual_labeling.")
    parser.add_argument("--conversation-db-path", type=Path)
    parser.add_argument("--shop-id", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--allow-custom-output-dir", action="store_true")
    parser.add_argument("--max-scan", type=int, default=1000)
    parser.add_argument("--max-per-domain", type=int, default=50)
    parser.add_argument("--include-pending-human", action="store_true")
    parser.add_argument("--include-unclassified", action="store_true")
    parser.add_argument("--preview-max-chars", type=int, default=80)
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--manual-labeling-profile", choices=("conservative", "balanced", "broad"), default="balanced")
    parser.add_argument("--include-private-locator", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(getattr(args, "output_dir", OUTPUT_ROOT))
    if not _safe_output_dir(output_dir) and not bool(getattr(args, "allow_custom_output_dir", False)):
        return _error("unsafe_output_dir")

    shop_ids = [str(item).strip() for item in getattr(args, "shop_id", []) if str(item or "").strip()]
    if not shop_ids:
        shop_ids = [replay.DEFAULT_SHOP_ID]
    messages = _load_messages(args, shop_ids)
    rows, summary = _candidate_rows(messages, args)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_name = "labeling_candidates.csv"
    json_name = "labeling_candidates.json"
    if bool(getattr(args, "include_private_locator", False)) and (output_dir / csv_name).exists():
        csv_name = "labeling_candidates_regenerated.csv"
        json_name = "labeling_candidates_regenerated.json"
    _write_csv(output_dir / csv_name, rows)
    _write_json(output_dir / json_name, {"candidates": [dict(row) for row in rows]})
    files_written = 4
    if bool(getattr(args, "include_private_locator", False)):
        private_payload = _private_candidate_payload(messages, rows, summary)
        _write_json(output_dir / "labeling_candidates_private.json", private_payload)
        summary = {**summary, **private_payload.get("summary", {})}
        files_written += 1
    _write_json(output_dir / "labeling_summary.json", summary)
    _write_json(output_dir / "label_schema.json", _label_schema())
    return {
        **summary,
        "status": "passed",
        "output_dir_hash": stable_hash(str(output_dir)),
        "files_written": files_written,
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
        "no_send": True,
        "calls_fastgpt": False,
        "sends_pdd": False,
    }


def _load_messages(args: argparse.Namespace, shop_ids: list[str]) -> list[replay.ReplayMessage]:
    path = getattr(args, "conversation_db_path", None)
    if not path:
        return replay._synthetic_messages(shop_ids[0])
    messages: list[replay.ReplayMessage] = []
    limit = max(1, int(getattr(args, "max_scan", 1000) or 1000))
    for shop_id in shop_ids:
        loaded, status = replay._load_replay_messages(
            Path(path),
            shop_id=shop_id,
            buyer_id="",
            session_id="",
            limit=limit,
            since="",
            until="",
            include_pending_human=bool(getattr(args, "include_pending_human", False)),
        )
        if status == "ok":
            messages.extend(loaded)
    return messages


def _candidate_rows(messages: list[replay.ReplayMessage], args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    max_per_domain = max(1, int(getattr(args, "max_per_domain", 50) or 50))
    preview_max = max(0, int(getattr(args, "preview_max_chars", 80) or 80))
    wanted_domains = {str(item) for item in getattr(args, "domain", []) if str(item or "").strip()}
    counts: dict[str, int] = {}
    excluded: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for message in messages:
        domain = _classify(message.content, str(getattr(args, "manual_labeling_profile", "balanced") or "balanced"))
        reason = ""
        if not domain:
            reason = "selector_unclassified"
            if not bool(getattr(args, "include_unclassified", False)):
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
        if wanted_domains and domain not in wanted_domains:
            excluded["domain_filtered"] = excluded.get("domain_filtered", 0) + 1
            continue
        if domain and counts.get(domain, 0) >= max_per_domain:
            excluded["domain_limit"] = excluded.get("domain_limit", 0) + 1
            continue
        if domain:
            counts[domain] = counts.get(domain, 0) + 1
        rows.append(_row(message, domain, reason, preview_max))
    return rows, {
        "selector_profile": str(getattr(args, "manual_labeling_profile", "balanced") or "balanced"),
        "scanned_total": len(messages),
        "candidate_count": len(rows),
        "selected_by_domain": counts,
        "excluded_by_reason": excluded,
        "pending_human_candidate_count": sum(1 for row in rows if row["pending_human"] == "true"),
        "unclassified_count": sum(1 for row in rows if not row["selector_predicted_domain"]),
    }


def _row(message: replay.ReplayMessage, domain: str, reason: str, preview_max: int) -> dict[str, Any]:
    label_id = "label-" + stable_hash("|".join([message.shop_id, message.session_id, stable_hash(message.content)]))[:16]
    return {
        "label_id": label_id,
        "shop_id_hash": stable_hash(message.shop_id),
        "buyer_id_hash": stable_hash(message.buyer_id),
        "session_id_hash": stable_hash(message.session_id),
        "message_id_hash": stable_hash(message.replay_id),
        "message_hash": stable_hash(message.content),
        "message_preview_truncated": message.content[:preview_max],
        "message_length": len(message.content),
        "created_at_bucket": str(message.created_at or "")[:10],
        "pending_human": "true" if message.pending_human else "false",
        "selector_predicted_domain": domain,
        "selector_score": "1.0" if domain else "0.0",
        "exclusion_reason": reason,
        "human_expected_domain": "",
        "human_expected_action_family": "",
        "requires_rag": "",
        "requires_answer": "",
        "allow_transfer_human": "",
        "allow_request_evidence": "",
        "allow_guardrail_blocked": "",
        "priority": "p2",
        "label_status": "draft",
        "label_notes": "",
    }


def _private_candidate_payload(
    messages: list[replay.ReplayMessage],
    rows: list[dict[str, Any]],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    by_label = {str(row.get("label_id") or ""): row for row in rows}
    candidates: list[dict[str, Any]] = []
    locator_count = 0
    missing_count = 0
    for message in messages:
        domain = _classify(message.content, str(summary.get("selector_profile") or "balanced"))
        label_id = "label-" + stable_hash("|".join([message.shop_id, message.session_id, stable_hash(message.content)]))[:16]
        if label_id not in by_label:
            continue
        locator = {
            "source_table": message.source_table,
            "message_pk": message.message_pk,
            "conversation_pk": message.conversation_pk,
            "session_id": message.session_id,
            "shop_id": message.shop_id,
            "buyer_id": message.buyer_id,
            "created_at": message.created_at,
        }
        has_locator = bool(message.source_table and message.message_pk)
        locator_count += 1 if has_locator else 0
        missing_count += 0 if has_locator else 1
        candidates.append(
            {
                **{key: value for key, value in by_label[label_id].items() if key != "message_preview_truncated"},
                "candidate_id": label_id.replace("label-", "cand-", 1),
                "predicted_domain": domain,
                "replay_locator": locator if has_locator else {},
                "replay_locator_hash": stable_hash(json.dumps(locator, ensure_ascii=False, sort_keys=True)) if has_locator else "",
                "locator_version": "replay-locator-v1",
            }
        )
    return {
        "summary": {
            "private_locator_count": locator_count,
            "private_locator_missing_count": missing_count,
            "selected_by_domain": dict(summary.get("selected_by_domain") or {}),
            "contains_raw_message": False,
        },
        "candidates": candidates,
    }


def _classify(content: str, profile: str) -> str:
    if profile == "conservative":
        return replay._classify_answerable_domain(content)
    base = replay._classify_answerable_domain(content)
    if base:
        return base
    for domain, keywords in BROAD_KEYWORDS.items():
        if any(keyword in content for keyword in keywords):
            return domain
    return ""


def _safe_output_dir(path: Path) -> bool:
    try:
        resolved = path.resolve()
        root = OUTPUT_ROOT.resolve()
        return resolved == root or root in resolved.parents
    except OSError:
        return False


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _label_schema() -> dict[str, Any]:
    return {
        "fields": CSV_FIELDS,
        "allowed_label_status": ["approved", "rejected", "draft"],
        "allowed_domains": sorted(replay.ANSWERABLE_DOMAINS),
        "contains_raw_message": False,
    }


def _error(error_type: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "error_type": error_type,
        "candidate_count": 0,
        "selected_by_domain": {},
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
        "no_send": True,
        "calls_fastgpt": False,
        "sends_pdd": False,
    }


def stable_hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    payload = run(parse_args(argv))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
