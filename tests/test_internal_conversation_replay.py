import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_conversation_replay.py"


def _run_replay(*args, expected_returncode=0):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    return json.loads(completed.stdout)


def _create_conversation_db(path: Path, *, pending_human: bool = False) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                pending_human INTEGER DEFAULT 0,
                status TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO conversations (id, shop_id, buyer_id, session_id, pending_human, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "conv-1",
                "synthetic-shop-1",
                "buyer-1",
                "session-1",
                1 if pending_human else 0,
                "pending_human" if pending_human else "active",
                "2026-05-21T10:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, shop_id, buyer_id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "msg-buyer-1",
                "conv-1",
                "synthetic-shop-1",
                "buyer-1",
                "session-1",
                "buyer",
                "PRIVATE_BUYER_MESSAGE_SHOULD_NOT_LEAK",
                "2026-05-21T10:01:00",
            ),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, shop_id, buyer_id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "msg-seller-1",
                "conv-1",
                "synthetic-shop-1",
                "buyer-1",
                "session-1",
                "seller",
                "PRIVATE_SELLER_MESSAGE_SHOULD_NOT_LEAK",
                "2026-05-21T10:02:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_missing_db_returns_missing_without_crash(tmp_path):
    payload = _run_replay(
        "--conversation-db-path",
        str(tmp_path / "missing.db"),
        "--shop-id",
        "synthetic-shop-1",
        "--json-only",
    )

    assert payload["status"] == "missing"
    assert payload["no_send"] is True
    assert payload["calls_fastgpt"] is False
    assert payload["sends_pdd"] is False


def test_empty_shop_id_is_rejected():
    payload = _run_replay("--shop-id", "", "--json-only", expected_returncode=1)

    assert payload["status"] == "error"
    assert payload["error_type"] == "missing_shop_id"
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_fake_sqlite_replay_only_buyer_messages_and_sanitizes(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_conversation_db(db_path)

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "synthetic-shop-1",
        "--buyer-id",
        "buyer-1",
        "--session-id",
        "session-1",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] in {"passed", "completed"}
    assert payload["total"] == 1
    assert payload["replayed"] == 1
    assert payload["no_send"] is True
    assert "PRIVATE_BUYER_MESSAGE_SHOULD_NOT_LEAK" not in rendered
    assert "PRIVATE_SELLER_MESSAGE_SHOULD_NOT_LEAK" not in rendered
    assert payload["results"][0]["message_hash"]
    assert "message" not in payload["results"][0]


def test_pending_human_replay_transfers(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_conversation_db(db_path, pending_human=True)

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "synthetic-shop-1",
        "--buyer-id",
        "buyer-1",
        "--session-id",
        "session-1",
        "--json-only",
    )

    assert payload["pending_human_count"] == 1
    assert payload["transfer_human_count"] == 1
    assert payload["results"][0]["action"] == "transfer_human"
    assert payload["results"][0]["verdict"] == "passed"


def test_agent_messages_schema_replay_is_shop_scoped(tmp_path):
    db_path = tmp_path / "conversation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE conversations (id TEXT, session_id TEXT, shop_id TEXT, buyer_id TEXT, user_id TEXT, status TEXT, created_at TEXT)"
        )
        conn.execute("CREATE TABLE agent_messages (id TEXT, session_id TEXT, role TEXT, content TEXT, timestamp TEXT)")
        conn.execute(
            "INSERT INTO conversations (id, session_id, shop_id, buyer_id, user_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("conv-1", "session-1", "synthetic-shop-1", "buyer-1", "", "active", "2026-05-21T10:00:00"),
        )
        conn.execute(
            "INSERT INTO conversations (id, session_id, shop_id, buyer_id, user_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("conv-2", "session-2", "other-shop", "buyer-2", "", "active", "2026-05-21T10:00:00"),
        )
        conn.execute(
            "INSERT INTO agent_messages (id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("msg-1", "session-1", "user", "SHOP_SCOPED_MESSAGE_SHOULD_NOT_LEAK", "2026-05-21T10:01:00"),
        )
        conn.execute(
            "INSERT INTO agent_messages (id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("msg-2", "session-2", "user", "OTHER_SHOP_MESSAGE_SHOULD_NOT_LEAK", "2026-05-21T10:01:00"),
        )
        conn.commit()
    finally:
        conn.close()

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "synthetic-shop-1",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["total"] == 1
    assert payload["results"][0]["session_id_hash"]
    assert "SHOP_SCOPED_MESSAGE_SHOULD_NOT_LEAK" not in rendered
    assert "OTHER_SHOP_MESSAGE_SHOULD_NOT_LEAK" not in rendered


def test_answerable_selector_filters_and_classifies_without_leaking(tmp_path):
    db_path = tmp_path / "conversation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                pending_human INTEGER DEFAULT 0,
                status TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO conversations (id, shop_id, buyer_id, session_id, pending_human, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("conv-1", "synthetic-shop-1", "buyer-1", "session-1", 0, "active"),
        )
        rows = [
            ("msg-1", "\u55ef"),
            ("msg-2", "[\u56fe\u7247]"),
            ("msg-3", "PRIVATE_LOGISTICS_MESSAGE_SHOULD_NOT_LEAK \u4ec0\u4e48\u65f6\u5019\u53d1\u8d27"),
            ("msg-4", "PRIVATE_AFTER_SALES_MESSAGE_SHOULD_NOT_LEAK \u6536\u5230\u7834\u635f\u4e86"),
            ("msg-5", "PRIVATE_PROMOTION_MESSAGE_SHOULD_NOT_LEAK \u80fd\u4e0d\u80fd\u4f18\u60e0"),
            ("msg-6", "PRIVATE_SECOND_LOGISTICS_MESSAGE_SHOULD_NOT_LEAK \u5feb\u9012\u6ca1\u66f4\u65b0"),
        ]
        for message_id, content in rows:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, shop_id, buyer_id, session_id, role, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, "conv-1", "synthetic-shop-1", "buyer-1", "session-1", "buyer", content),
            )
        conn.commit()
    finally:
        conn.close()

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "synthetic-shop-1",
        "--answerable-only",
        "--answerable-max-per-domain",
        "1",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["answerable_total"] == 3
    assert payload["selected_total"] == 3
    assert payload["skipped_short_ack"] == 1
    assert payload["skipped_media_only"] == 1
    assert payload["selected_by_domain"]["logistics_policy"] == 1
    assert payload["selected_by_domain"]["after_sales_evidence"] == 1
    assert payload["selected_by_domain"]["promotion_policy"] == 1
    assert "PRIVATE_LOGISTICS_MESSAGE_SHOULD_NOT_LEAK" not in rendered
    assert "PRIVATE_AFTER_SALES_MESSAGE_SHOULD_NOT_LEAK" not in rendered
    assert "PRIVATE_PROMOTION_MESSAGE_SHOULD_NOT_LEAK" not in rendered
    assert all(row["answerable_domain"] for row in payload["results"])


def test_answerable_replay_requires_rag_hit_when_configured():
    payload = _run_replay(
        "--answerable-only",
        "--require-answerable-rag-hit",
        "--json-only",
        expected_returncode=1,
    )

    assert payload["answerable_total"] == 1
    assert payload["answerable_failed"] == 1
    assert payload["results"][0]["answerable_verdict"] == "failed"
    assert "answerable_rag_miss" in payload["results"][0]["answerable_errors"]


def test_answerable_redline_transfer_and_after_sales_request_evidence_pass(tmp_path):
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
            "INSERT INTO conversations (id, shop_id, buyer_id, session_id, pending_human, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("conv-1", "synthetic-shop-1", "buyer-1", "session-1", 0, "active"),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, shop_id, buyer_id, session_id, role, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("msg-redline", "conv-1", "synthetic-shop-1", "buyer-1", "session-1", "buyer", "\u6211\u8981\u6295\u8bc9\u4f60\u4eec\u662f\u5047\u8d27"),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, shop_id, buyer_id, session_id, role, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("msg-after-sales", "conv-1", "synthetic-shop-1", "buyer-1", "session-1", "buyer", "\u6536\u5230\u7834\u635f\u4e86\u600e\u4e48\u529e"),
        )
        conn.commit()
    finally:
        conn.close()

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "synthetic-shop-1",
        "--answerable-only",
        "--include-redline",
        "--json-only",
    )
    rows = {row["answerable_domain"]: row for row in payload["results"]}

    assert rows["redline_escalation"]["answerable_verdict"] == "passed"
    assert rows["redline_escalation"]["action"] == "transfer_human"
    assert rows["after_sales_evidence"]["answerable_verdict"] == "passed"
    assert rows["after_sales_evidence"]["action"] in {"request_evidence", "reply"}


def test_real_mode_requires_explicit_external_config_without_calls(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_conversation_db(db_path)

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "synthetic-shop-1",
        "--real-rag",
        "--real-llm",
        "--json-only",
        expected_returncode=1,
    )

    assert payload["status"] == "error"
    assert payload["error_type"].startswith("missing_")
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_selector_audit_only_counts_reasons_without_engine_calls(tmp_path):
    db_path = tmp_path / "conversation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)")
        conn.execute("CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT)")
        conn.execute(
            "INSERT INTO conversations (id, shop_id, buyer_id, session_id, pending_human, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("conv-1", "synthetic-shop-1", "buyer-1", "session-1", 1, "pending_human"),
        )
        rows = [
            ("msg-1", "\u55ef"),
            ("msg-2", "[\u56fe\u7247]"),
            ("msg-3", "\u600e\u4e48\u7528"),
            ("msg-4", "NO_PRIVATE_TEXT_SHOULD_NOT_LEAK"),
        ]
        for message_id, content in rows:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, shop_id, buyer_id, session_id, role, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, "conv-1", "synthetic-shop-1", "buyer-1", "session-1", "buyer", content),
            )
        conn.commit()
    finally:
        conn.close()

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "synthetic-shop-1",
        "--selector-audit-only",
        "--selector-audit-output-samples",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "completed"
    assert payload["total"] == 0
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    assert payload["pending_human_count"] == 4
    assert payload["excluded_by_reason"]["pending_human_excluded"] == 4
    assert "NO_PRIVATE_TEXT_SHOULD_NOT_LEAK" not in rendered


def test_multi_shop_answerable_summary_is_shop_scoped(tmp_path):
    db_path = tmp_path / "conversation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)")
        conn.execute("CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT)")
        for shop_id, conv_id, session_id, content in [
            ("shop-a", "conv-a", "session-a", "\u600e\u4e48\u7528"),
            ("shop-b", "conv-b", "session-b", "\u4ec0\u4e48\u65f6\u5019\u53d1\u8d27"),
        ]:
            conn.execute(
                "INSERT INTO conversations (id, shop_id, buyer_id, session_id, pending_human, status) VALUES (?, ?, ?, ?, ?, ?)",
                (conv_id, shop_id, "buyer-1", session_id, 0, "active"),
            )
            conn.execute(
                "INSERT INTO messages (id, conversation_id, shop_id, buyer_id, session_id, role, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"msg-{shop_id}", conv_id, shop_id, "buyer-1", session_id, "buyer", content),
            )
        conn.commit()
    finally:
        conn.close()

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--shop-id",
        "shop-b",
        "--answerable-only",
        "--allow-empty-shop",
        "--json-only",
        expected_returncode=1,
    )

    assert payload["shops_total"] == 2
    assert payload["shops_with_candidates"] == 2
    assert payload["answerable_total"] == 2
    assert set(payload["per_shop_domain_counts"].keys())


def test_domain_coverage_requirement_can_fail():
    payload = _run_replay(
        "--answerable-only",
        "--baseline-domains",
        "product_basic,logistics_policy",
        "--require-domain-coverage",
        "--json-only",
        expected_returncode=1,
    )

    assert payload["domain_coverage_status"] == "failed"
    assert "product_basic" in payload["domains_missing"]


def test_candidate_pool_generation_writes_hash_only_pool(tmp_path):
    db_path = tmp_path / "conversation.db"
    out_path = tmp_path / "candidates.json"
    secret_message = "NO_RAW_BUYER_TEXT_SHOULD_NOT_LEAK 怎么用"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)")
        conn.execute("CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT)")
        conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)", ("conv-1", "shop-a", "buyer-1", "session-1", 0, "active"))
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("msg-1", "conv-1", "shop-a", "buyer-1", "session-1", "buyer", secret_message),
        )
        conn.commit()
    finally:
        conn.close()

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--generate-candidate-pool",
        "--candidate-output",
        str(out_path),
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False) + out_path.read_text(encoding="utf-8")

    assert payload["status"] == "completed"
    assert payload["selected_total"] == 1
    assert payload["candidate_pool_written"] is True
    assert "NO_RAW_BUYER_TEXT_SHOULD_NOT_LEAK" not in rendered


def test_candidate_recall_profile_broad_recalls_after_sales_synonym(tmp_path):
    db_path = tmp_path / "conversation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)")
        conn.execute("CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT)")
        conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)", ("conv-1", "shop-a", "buyer-1", "session-1", 0, "active"))
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("msg-1", "conv-1", "shop-a", "buyer-1", "session-1", "buyer", "\u788e\u4e86\u600e\u4e48\u529e"),
        )
        conn.commit()
    finally:
        conn.close()

    conservative = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--answerable-only",
        "--selector-audit-only",
        "--json-only",
    )
    broad = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--answerable-only",
        "--selector-audit-only",
        "--candidate-recall-profile",
        "broad",
        "--json-only",
    )

    assert conservative["selected_total"] == 0
    assert broad["selected_by_domain"]["after_sales_evidence"] == 1
    assert broad["selector_profile"] == "broad"


def test_benchmark_replay_reports_message_not_found(tmp_path):
    benchmark = {
        "benchmark_version": "test-v1",
        "cases": [
            {
                "case_id": "case-missing",
                "candidate_id": "candidate-missing",
                "message_hash": "does-not-exist",
                "expected_domain": "product_basic",
                "expected_action_family": "reply",
                "requires_rag": False,
                "requires_answer": False,
            }
        ],
    }
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    payload = _run_replay("--benchmark-file", str(benchmark_path), "--json-only")

    assert payload["benchmark_case_count"] == 1
    assert payload["benchmark_message_not_found_count"] == 1
    assert payload["benchmark_unclear"] == 1


def test_benchmark_replay_resolves_private_locator_without_raw_locator_output(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_conversation_db(db_path)
    message_hash = "37873089597b6fc6d8a4af53ee8cbd2470ec308e0d6f3fb4c6ffce819cdf8485"
    benchmark = {
        "benchmark_version": "test-v1",
        "cases": [
            {
                "case_id": "case-locator",
                "message_hash": message_hash,
                "expected_domain": "product_basic",
                "expected_action_family": "reply",
                "requires_rag": False,
                "requires_answer": False,
                "replay_locator": {
                    "source_table": "messages",
                    "message_pk": "msg-buyer-1",
                    "shop_id": "synthetic-shop-1",
                    "buyer_id": "buyer-1",
                    "session_id": "session-1",
                },
            }
        ],
    }
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--benchmark-file",
        str(benchmark_path),
        "--json-only",
        expected_returncode=1,
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["locator_case_count"] == 1
    assert payload["locator_resolved_count"] == 1
    assert payload["benchmark_message_not_found_count"] == 0
    assert "msg-buyer-1" not in rendered
    assert "PRIVATE_BUYER_MESSAGE_SHOULD_NOT_LEAK" not in rendered


def test_benchmark_replay_locator_hash_mismatch_is_unclear(tmp_path):
    db_path = tmp_path / "conversation.db"
    _create_conversation_db(db_path)
    benchmark = {
        "cases": [
            {
                "case_id": "case-bad-locator",
                "message_hash": "wrong-hash",
                "expected_domain": "product_basic",
                "expected_action_family": "reply",
                "requires_rag": False,
                "requires_answer": False,
                "replay_locator": {"source_table": "messages", "message_pk": "msg-buyer-1"},
            }
        ]
    }
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--benchmark-file",
        str(benchmark_path),
        "--json-only",
    )

    assert payload["locator_hash_mismatch_count"] == 1
    assert payload["benchmark_unclear"] == 1


def test_benchmark_oracle_routing_uses_expected_domain_without_raw_text(tmp_path):
    db_path = tmp_path / "conversation.db"
    content = "NO_ORACLE_RAW_TEXT_SHOULD_NOT_LEAK"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)")
        conn.execute("CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT)")
        conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)", ("conv-1", "shop-a", "buyer-1", "session-1", 0, "active"))
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("msg-1", "conv-1", "shop-a", "buyer-1", "session-1", "buyer", content),
        )
        conn.commit()
    finally:
        conn.close()
    import hashlib

    benchmark = {
        "cases": [
            {
                "case_id": "case-oracle",
                "message_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "expected_domain": "logistics_policy",
                "expected_action_family": "reply",
                "requires_rag": False,
                "requires_answer": False,
                "replay_locator": {"source_table": "messages", "message_pk": "msg-1"},
            }
        ]
    }
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    production = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--benchmark-file",
        str(benchmark_path),
        "--json-only",
        expected_returncode=1,
    )
    oracle = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--benchmark-file",
        str(benchmark_path),
        "--oracle-routing",
        "--json-only",
    )
    rendered = json.dumps(oracle, ensure_ascii=False)

    assert production["results"][0]["routing_mode"] == "production"
    assert production["results"][0]["verdict"] == "failed"
    assert oracle["results"][0]["routing_mode"] == "oracle"
    assert oracle["results"][0]["oracle_domain_used"] is True
    assert oracle["results"][0]["verdict"] == "passed"
    assert oracle["results"][0]["action"] == "reply"
    assert "NO_ORACLE_RAW_TEXT_SHOULD_NOT_LEAK" not in rendered


def test_pending_human_audit_only_counts_answerable_without_engine(tmp_path):
    db_path = tmp_path / "conversation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE conversations (id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER, status TEXT)")
        conn.execute("CREATE TABLE messages (id TEXT, conversation_id TEXT, shop_id TEXT, buyer_id TEXT, session_id TEXT, role TEXT, content TEXT)")
        conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)", ("conv-1", "shop-a", "buyer-1", "session-1", 1, "pending"))
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("msg-1", "conv-1", "shop-a", "buyer-1", "session-1", "buyer", "\u4ec0\u4e48\u65f6\u5019\u53d1\u8d27"),
        )
        conn.commit()
    finally:
        conn.close()

    payload = _run_replay(
        "--conversation-db-path",
        str(db_path),
        "--shop-id",
        "shop-a",
        "--pending-human-audit-only",
        "--json-only",
    )

    assert payload["status"] == "completed"
    assert payload["total"] == 0
    assert payload["pending_human_scanned"] == 1
    assert payload["pending_human_answerable_candidates"] == 1
    assert payload["calls_llm"] is False
