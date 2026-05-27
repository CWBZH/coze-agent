import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_manual_labeling_pack.py"


def _run_pack(*args, expected_returncode=0):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    return json.loads(completed.stdout)


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)")
        conn.execute("CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT, created_at TEXT)")
        rows = [
            ("m1", "c1", "shop-a", "buyer-1", "s1", "buyer", "NO_FULL_TEXT_SHOULD_NOT_LEAK 什么时候发货", "2026-05-01"),
            ("m2", "c2", "shop-a", "buyer-2", "s2", "buyer", "碎了怎么办", "2026-05-02"),
            ("m3", "c3", "shop-a", "buyer-3", "s3", "buyer", "好的", "2026-05-03"),
        ]
        for row in rows:
            pending = 1 if row[0] == "m2" else 0
            conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)", (row[1], row[2], row[3], row[4], pending, "active"))
            conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
        conn.commit()
    finally:
        conn.close()


def test_manual_labeling_pack_writes_private_files_and_truncated_preview(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_db(db_path)
    output_dir = REPO_ROOT / "temp" / "manual_labeling" / "pytest-pack"

    payload = _run_pack(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--output-dir",
        str(output_dir),
        "--include-pending-human",
        "--manual-labeling-profile",
        "broad",
        "--preview-max-chars",
        "8",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "passed"
    assert payload["candidate_count"] >= 2
    assert (output_dir / "labeling_candidates.csv").exists()
    assert (output_dir / "label_schema.json").exists()
    assert "NO_FULL_TEXT_SHOULD_NOT_LEAK" not in rendered
    with (output_dir / "labeling_candidates.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(len(row["message_preview_truncated"]) <= 8 for row in rows)


def test_manual_labeling_pack_rejects_non_temp_output(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_db(db_path)

    payload = _run_pack(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--output-dir",
        str(tmp_path / "outside"),
        "--json-only",
        expected_returncode=1,
    )

    assert payload["status"] == "failed"
    assert payload["error_type"] == "unsafe_output_dir"


def test_manual_labeling_broad_profile_recalls_after_sales(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_db(db_path)

    payload = _run_pack(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--output-dir",
        str(REPO_ROOT / "temp" / "manual_labeling" / "pytest-broad"),
        "--include-pending-human",
        "--manual-labeling-profile",
        "broad",
        "--json-only",
    )

    assert payload["selector_profile"] == "broad"
    assert payload["selected_by_domain"].get("after_sales_evidence", 0) >= 1


def test_manual_labeling_private_locator_is_private_json_only(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_db(db_path)
    output_dir = REPO_ROOT / "temp" / "manual_labeling" / "pytest-private-locator"

    payload = _run_pack(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--output-dir",
        str(output_dir),
        "--include-pending-human",
        "--manual-labeling-profile",
        "broad",
        "--include-private-locator",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)
    csv_text = (output_dir / "labeling_candidates.csv").read_text(encoding="utf-8-sig")
    private_payload = json.loads((output_dir / "labeling_candidates_private.json").read_text(encoding="utf-8"))

    assert payload["private_locator_count"] >= 1
    assert "replay_locator" not in csv_text
    assert private_payload["candidates"][0]["replay_locator"]
    assert private_payload["candidates"][0]["replay_locator_hash"]
    assert "NO_FULL_TEXT_SHOULD_NOT_LEAK" not in rendered
