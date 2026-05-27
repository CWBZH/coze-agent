import json
import csv
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_replay_benchmark.py"


def _run_benchmark(*args, expected_returncode=0):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    return json.loads(completed.stdout)


def test_build_benchmark_from_candidate_pool_without_raw_message(tmp_path):
    candidate_pool = {
        "summary": {"selected_total": 2},
        "candidates": [
            {
                "candidate_id": "c-1",
                "message_hash": "mh-1",
                "shop_id_hash": "shop-h",
                "session_id_hash": "session-h",
                "buyer_id_hash": "buyer-h",
                "predicted_domain": "product_basic",
                "source": "history",
            },
            {
                "candidate_id": "c-2",
                "message_hash": "mh-2",
                "shop_id_hash": "shop-h",
                "session_id_hash": "session-h",
                "buyer_id_hash": "buyer-h",
                "predicted_domain": "logistics_policy",
                "source": "history",
            },
        ],
    }
    candidate_path = tmp_path / "candidates.json"
    output_path = tmp_path / "benchmark.json"
    candidate_path.write_text(json.dumps(candidate_pool, ensure_ascii=False), encoding="utf-8")

    payload = _run_benchmark(
        "--build-benchmark-from-candidates",
        "--candidate-input",
        str(candidate_path),
        "--benchmark-output",
        str(output_path),
        "--max-per-domain",
        "1",
        "--json-only",
    )

    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["case_count"] == 2
    assert payload["domain_counts"] == {"product_basic": 1, "logistics_policy": 1}
    assert output_path.exists()
    assert "NO_RAW_MESSAGE" not in rendered
    assert all("message" not in case for case in payload["cases"])


def test_build_benchmark_records_missing_domains_and_stable_case_ids(tmp_path):
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "candidate-one",
                        "message_hash": "hash-one",
                        "shop_id_hash": "shop-one",
                        "session_id_hash": "session-one",
                        "buyer_id_hash": "buyer-one",
                        "predicted_domain": "product_basic",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = _run_benchmark(
        "--build-benchmark-from-candidates",
        "--candidate-input",
        str(candidate_path),
        "--include-domain",
        "product_basic",
        "--include-domain",
        "promotion_policy",
        "--allow-missing-domain",
        "--json-only",
    )
    second = _run_benchmark(
        "--build-benchmark-from-candidates",
        "--candidate-input",
        str(candidate_path),
        "--include-domain",
        "product_basic",
        "--include-domain",
        "promotion_policy",
        "--allow-missing-domain",
        "--json-only",
    )

    assert first["missing_domains"] == ["promotion_policy"]
    assert first["cases"][0]["case_id"] == second["cases"][0]["case_id"]


def test_build_benchmark_from_approved_labels_without_preview(tmp_path):
    label_path = tmp_path / "labels.csv"
    output_path = tmp_path / "benchmark.json"
    fields = [
        "label_id",
        "shop_id_hash",
        "buyer_id_hash",
        "session_id_hash",
        "message_hash",
        "message_preview_truncated",
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
    with label_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "label_id": "label-1",
                "shop_id_hash": "shop-h",
                "buyer_id_hash": "buyer-h",
                "session_id_hash": "session-h",
                "message_hash": "message-h",
                "message_preview_truncated": "NO_PREVIEW_IN_BENCHMARK",
                "human_expected_domain": "after_sales_evidence",
                "human_expected_action_family": "request_evidence_or_reply",
                "requires_rag": "true",
                "requires_answer": "false",
                "allow_transfer_human": "true",
                "allow_request_evidence": "true",
                "allow_guardrail_blocked": "false",
                "priority": "p1",
                "label_status": "approved",
                "label_notes": "",
            }
        )
        writer.writerow({"label_id": "label-2", "label_status": "draft"})
        writer.writerow({"label_id": "label-3", "label_status": "approved", "message_hash": "x"})

    payload = _run_benchmark(
        "--build-benchmark-from-labels",
        "--label-input",
        str(label_path),
        "--benchmark-output",
        str(output_path),
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["labels_total"] == 3
    assert payload["approved_count"] == 2
    assert payload["invalid_label_count"] == 1
    assert payload["benchmark_case_count"] == 1
    assert payload["domain_counts"] == {"after_sales_evidence": 1}
    assert "NO_PREVIEW_IN_BENCHMARK" not in rendered
    assert output_path.exists()


def test_build_benchmark_from_labels_attaches_private_locator(tmp_path):
    label_path = tmp_path / "labels.csv"
    private_path = tmp_path / "private.json"
    fields = [
        "label_id",
        "shop_id_hash",
        "buyer_id_hash",
        "session_id_hash",
        "message_hash",
        "message_preview_truncated",
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
    with label_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "label_id": "label-1",
                "shop_id_hash": "shop-h",
                "buyer_id_hash": "buyer-h",
                "session_id_hash": "session-h",
                "message_hash": "message-h",
                "message_preview_truncated": "NO_PREVIEW_IN_BENCHMARK",
                "human_expected_domain": "product_basic",
                "human_expected_action_family": "reply",
                "requires_rag": "true",
                "requires_answer": "true",
                "allow_transfer_human": "false",
                "allow_request_evidence": "false",
                "allow_guardrail_blocked": "false",
                "priority": "p2",
                "label_status": "approved",
                "label_notes": "",
            }
        )
    private_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "label_id": "label-1",
                        "message_hash": "message-h",
                        "session_id_hash": "session-h",
                        "buyer_id_hash": "buyer-h",
                        "replay_locator": {"source_table": "messages", "message_pk": "msg-1"},
                        "replay_locator_hash": "locator-h",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = _run_benchmark(
        "--build-benchmark-from-labels",
        "--label-input",
        str(label_path),
        "--benchmark-output",
        str(tmp_path / "with-locator.json"),
        "--candidate-private-input",
        str(private_path),
        "--include-private-locator",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)
    written = json.loads((tmp_path / "with-locator.json").read_text(encoding="utf-8"))

    assert payload["locator_attached_count"] == 1
    assert payload["locator_missing_count"] == 0
    assert payload["cases"][0]["replay_locator_attached"] is True
    assert written["cases"][0]["replay_locator"]["message_pk"] == "msg-1"
    assert "NO_PREVIEW_IN_BENCHMARK" not in rendered
