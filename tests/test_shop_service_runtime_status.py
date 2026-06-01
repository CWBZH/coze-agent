import json
import sqlite3
import time
from pathlib import Path

from web_api.services.shop_service import ShopService
from web_api.services.sqlite_readonly import ReadOnlySqlite


def _create_shop_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL,
                archived_at TEXT
            );
            CREATE TABLE shop_auth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                auth_status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                status INTEGER
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                updated_at TEXT
            );
            CREATE TABLE shop_ai_settings (
                shop_id TEXT PRIMARY KEY,
                ai_enabled INTEGER NOT NULL
            );
            CREATE TABLE knowledge_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT,
                source_type TEXT,
                domain TEXT,
                is_active INTEGER,
                activated_at TEXT
            );
            CREATE TABLE pdd_inbound_message_queue (
                id TEXT PRIMARY KEY,
                shop_id TEXT,
                updated_at REAL
            );
            CREATE TABLE pdd_reply_outbox (
                id TEXT PRIMARY KEY,
                shop_id TEXT,
                updated_at REAL
            );
            INSERT INTO channels (id, channel_name) VALUES (1, 'pinduoduo');
            INSERT INTO shops (id, channel_id, shop_id, shop_name) VALUES (1, 1, '565617', 'Test Shop');
            INSERT INTO shop_auth (shop_id, platform, auth_status, updated_at)
                VALUES ('565617', 'pdd', 'valid', '2026-06-01T00:00:00+00:00');
            INSERT INTO accounts (shop_id, status) VALUES (1, 1);
            INSERT INTO conversations (shop_id, updated_at) VALUES (1, '2026-06-01T01:00:00+00:00');
            INSERT INTO shop_ai_settings (shop_id, ai_enabled) VALUES ('565617', 1);
            INSERT INTO knowledge_versions (shop_id, source_type, domain, is_active, activated_at)
                VALUES ('565617', 'product', 'product_catalog', 1, '2026-06-01T02:00:00+00:00');
            """
        )
        now = time.time()
        conn.execute("INSERT INTO pdd_inbound_message_queue (id, shop_id, updated_at) VALUES ('in-1', '565617', ?)", (now - 10,))
        conn.execute("INSERT INTO pdd_reply_outbox (id, shop_id, updated_at) VALUES ('out-1', '565617', ?)", (now,))
        conn.commit()
    finally:
        conn.close()


def test_shop_summary_uses_real_ai_provider_worker_and_sending_state(tmp_path, monkeypatch):
    db_path = tmp_path / "shops.db"
    status_path = tmp_path / "runtime" / "worker_status.json"
    status_path.parent.mkdir()
    _create_shop_db(db_path)
    status_path.write_text(
        json.dumps(
            {
                "worker_state": "running",
                "updated_at": time.time(),
                "accounts": [{"shop_id": "565617", "user_id": "713439", "state": "running"}],
                "connections": [{"shop_id": "565617", "user_id": "713439", "state": "connected"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKER_STATUS_PATH", str(status_path))
    monkeypatch.setenv("PDD_SENDING_ENABLED", "true")
    monkeypatch.setenv("AI_WORKFLOW_PGVECTOR_DSN", "postgresql://user:pass@127.0.0.1:5432/customer_agent")
    monkeypatch.setenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_EMBEDDING_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    monkeypatch.setenv("DOUBAO_EMBEDDING_MODEL", "doubao-embedding-vision-test")
    monkeypatch.setenv("DOUBAO_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("AI_WORKFLOW_LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    monkeypatch.setenv("AI_WORKFLOW_LLM_MODEL", "doubao-test")
    monkeypatch.setenv("AI_WORKFLOW_LLM_API_KEY", "test-key")

    shops, warning = ShopService(ReadOnlySqlite(db_path)).list_shops()

    assert warning is None
    assert len(shops) == 1
    shop = shops[0]
    assert shop.internal_enabled is True
    assert shop.rag_enabled is True
    assert shop.llm_enabled is True
    assert shop.intent_classifier_enabled is True
    assert shop.answer_generator_enabled is True
    assert shop.websocket_status == "connected"
    assert shop.no_send is False
    assert shop.last_activity is not None


def test_shop_summary_reports_stopped_when_worker_has_no_shop_account(tmp_path, monkeypatch):
    db_path = tmp_path / "shops.db"
    status_path = tmp_path / "runtime" / "worker_status.json"
    status_path.parent.mkdir()
    _create_shop_db(db_path)
    status_path.write_text(
        json.dumps(
            {
                "worker_state": "running",
                "updated_at": time.time(),
                "accounts": [{"shop_id": "other-shop", "user_id": "x", "state": "running"}],
                "connections": [{"shop_id": "other-shop", "user_id": "x", "state": "connected"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKER_STATUS_PATH", str(status_path))
    monkeypatch.delenv("PDD_SENDING_ENABLED", raising=False)

    shops, _ = ShopService(ReadOnlySqlite(db_path)).list_shops()

    assert shops[0].websocket_status == "unknown"
    assert shops[0].no_send is True
