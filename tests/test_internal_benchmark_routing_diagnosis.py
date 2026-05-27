import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_benchmark_routing_diagnosis.py"


def _run_diagnosis(*args, expected_returncode=0):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    return json.loads(completed.stdout)


def _create_db_and_benchmark(tmp_path: Path, *, content: str = "NO_ROUTING_KEYWORD_PRIVATE_TEXT"):
    db_path = tmp_path / "conversation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)"
        )
        conn.execute(
            "CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT)"
        )
        conn.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
            ("conv-1", "shop-a", "buyer-1", "session-1", 0, "active"),
        )
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("msg-1", "conv-1", "shop-a", "buyer-1", "session-1", "buyer", content),
        )
        conn.commit()
    finally:
        conn.close()

    import hashlib

    message_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    benchmark = {
        "benchmark_version": "diagnosis-test-v1",
        "cases": [
            {
                "case_id": "case-routing",
                "message_hash": message_hash,
                "expected_domain": "logistics_policy",
                "expected_action_family": "reply",
                "requires_rag": False,
                "requires_answer": False,
                "replay_locator": {
                    "source_table": "messages",
                    "message_pk": "msg-1",
                    "shop_id": "shop-a",
                    "buyer_id": "buyer-1",
                    "session_id": "session-1",
                },
            }
        ],
    }
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    return db_path, benchmark_path


def test_fake_diagnosis_classifies_production_fail_oracle_pass_as_routing_failure(tmp_path):
    db_path, benchmark_path = _create_db_and_benchmark(tmp_path)

    payload = _run_diagnosis(
        "--conversation-db-path",
        str(db_path),
        "--benchmark-file",
        str(benchmark_path),
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["total"] == 1
    assert payload["production_passed"] == 0
    assert payload["oracle_passed"] == 1
    assert payload["routing_failure_count"] == 1
    assert payload["results"][0]["diagnosis"] == "routing_failure"
    assert payload["results"][0]["production_verdict"] == "failed"
    assert payload["results"][0]["oracle_verdict"] == "passed"
    assert "NO_ROUTING_KEYWORD_PRIVATE_TEXT" not in rendered


def test_diagnosis_writes_private_csv_without_raw_text(tmp_path):
    db_path, benchmark_path = _create_db_and_benchmark(tmp_path)
    out_dir = REPO_ROOT / "temp" / "manual_labeling" / "test-routing-diagnosis"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "routing_diagnosis_test.json"
    csv_path = out_dir / "routing_diagnosis_test.csv"

    payload = _run_diagnosis(
        "--conversation-db-path",
        str(db_path),
        "--benchmark-file",
        str(benchmark_path),
        "--routing-diagnosis-output",
        str(json_path),
        "--routing-diagnosis-csv",
        str(csv_path),
        "--json-only",
    )

    assert payload["diagnosis_output_hash"]
    assert payload["diagnosis_csv_hash"]
    assert json_path.exists()
    assert csv_path.exists()
    assert "NO_ROUTING_KEYWORD_PRIVATE_TEXT" not in json_path.read_text(encoding="utf-8")
    assert "NO_ROUTING_KEYWORD_PRIVATE_TEXT" not in csv_path.read_text(encoding="utf-8")
