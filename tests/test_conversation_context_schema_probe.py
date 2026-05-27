import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "conversation_context_schema_probe.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("conversation_context_schema_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _standard_db(tmp_path, *, alias=False, missing_content=False):
    db_path = tmp_path / "conversation.sqlite"
    conversation_table = "conversation" if alias else "conversations"
    message_table = "conversation_messages" if alias else "messages"
    conn = sqlite3.connect(db_path)
    conn.execute(
        f'CREATE TABLE "{conversation_table}" (id TEXT, shop_id TEXT, user_id TEXT, buyer_id TEXT, session_id TEXT)'
    )
    content_field = "body" if not missing_content else "other"
    conn.execute(
        f'CREATE TABLE "{message_table}" (conversation_id TEXT, shop_id TEXT, user_id TEXT, buyer_id TEXT, session_id TEXT, {content_field} TEXT, created_at TEXT)'
    )
    conn.execute(
        f'INSERT INTO "{conversation_table}" (id, shop_id, user_id, buyer_id, session_id) VALUES (?, ?, ?, ?, ?)',
        ("conv-a", "shop-a", "user-a", "buyer-a", "session-a"),
    )
    conn.execute(
        f'INSERT INTO "{message_table}" (conversation_id, shop_id, user_id, buyer_id, session_id, {content_field}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        ("conv-a", "shop-a", "user-a", "buyer-a", "session-a", "PRIVATE_CONTENT", "2026-05-21T01:00:00Z"),
    )
    conn.commit()
    conn.close()
    return db_path


def test_probe_standard_schema_ok(tmp_path):
    probe = _load_probe()
    db_path = _standard_db(tmp_path)

    result = probe.probe_schema(db_path, shop_id="shop-a", user_id="user-a", buyer_id="buyer-a", session_id="session-a")

    assert result["status"] == "ok"
    assert result["supported_mapping"]["conversation_table"] is True
    assert result["supported_mapping"]["message_table"] is True
    assert result["supported_mapping"]["content"] is True
    assert result["isolation_probe_status"]["status"] == "ok"
    assert result["isolation_probe_status"]["matched_count"] == 1
    assert "PRIVATE_CONTENT" not in json.dumps(result, ensure_ascii=False)


def test_probe_alias_schema_ok(tmp_path):
    probe = _load_probe()
    db_path = _standard_db(tmp_path, alias=True)

    result = probe.probe_schema(db_path)

    assert result["status"] == "ok"
    assert result["candidate_conversation_tables"] == ["conversation"]
    assert result["candidate_message_tables"] == ["conversation_messages"]


def test_probe_missing_db_and_missing_tables_do_not_crash(tmp_path):
    probe = _load_probe()
    missing = tmp_path / "missing.sqlite"

    missing_result = probe.probe_schema(missing)
    assert missing_result["status"] == "missing"

    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()
    empty_result = probe.probe_schema(empty)
    assert empty_result["status"] == "missing_tables"


def test_probe_reports_missing_required_fields(tmp_path):
    probe = _load_probe()
    db_path = _standard_db(tmp_path, missing_content=True)

    result = probe.probe_schema(db_path)

    assert result["status"] == "unsupported_schema"
    assert "content" in result["missing_required_fields"]


def test_probe_cli_json_only_is_parseable(tmp_path):
    db_path = _standard_db(tmp_path)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--db-path", str(db_path), "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert "PRIVATE_CONTENT" not in completed.stdout
