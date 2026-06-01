import sqlite3
from pathlib import Path
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from web_api.deps import get_dashboard_service, get_shop_service
from web_api.main import app
from web_api.services.dashboard_service import DashboardService
from web_api.services.shop_service import ShopService
from web_api.services.sqlite_readonly import ReadOnlySqlite


def _create_dashboard_db(path: Path) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            f"""
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT NOT NULL UNIQUE,
                description TEXT
            );
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL,
                created_at TEXT,
                archived_at TEXT
            );
            CREATE TABLE shop_auth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                auth_status TEXT NOT NULL,
                safe_display TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                status INTEGER,
                password TEXT,
                cookies TEXT
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                session_id TEXT,
                buyer_id TEXT,
                updated_at TEXT
            );
            CREATE TABLE product_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT,
                goods_id TEXT,
                goods_name TEXT
            );
            CREATE TABLE shop_ai_settings (
                shop_id TEXT PRIMARY KEY,
                ai_enabled INTEGER NOT NULL
            );
            CREATE TABLE knowledge_index_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_run_id TEXT,
                shop_id TEXT,
                source_type TEXT,
                source_id TEXT,
                domain TEXT,
                version TEXT,
                status TEXT,
                chunk_count INTEGER,
                embedded_count INTEGER,
                indexed_count INTEGER,
                created_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                error_summary TEXT
            );
            CREATE TABLE product_sync_jobs (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT,
                answer_status TEXT,
                guardrail_status TEXT,
                rag_hit_count INTEGER,
                created_at TEXT
            );
            INSERT INTO channels (id, channel_name, description) VALUES (1, 'pinduoduo', 'PDD');
            INSERT INTO shops (id, channel_id, shop_id, shop_name, created_at) VALUES
                (1, 1, '565617', '真实店铺', '2026-05-29T00:00:00+00:00'),
                (2, 1, 'remote-session-id', '临时会话', '2026-05-29T00:00:00+00:00');
            INSERT INTO shop_auth (shop_id, platform, auth_status, safe_display, updated_at)
                VALUES ('565617', 'pdd', 'valid', '135***888', '2026-05-29T00:00:00+00:00');
            INSERT INTO accounts (shop_id, status, password, cookies) VALUES (1, 1, 'DO_NOT_RETURN_PASSWORD', 'DO_NOT_RETURN_COOKIE');
            INSERT INTO conversations (shop_id, session_id, buyer_id, updated_at) VALUES (1, 's1', 'b1', '{now_iso}');
            INSERT INTO product_knowledge (shop_id, goods_id, goods_name) VALUES ('565617', '931798442189', '真实商品');
            INSERT INTO shop_ai_settings (shop_id, ai_enabled) VALUES ('565617', 1);
            INSERT INTO knowledge_index_jobs
                (index_run_id, shop_id, source_type, source_id, domain, version, status, chunk_count, embedded_count, indexed_count, created_at, started_at, finished_at)
                VALUES ('idx-real', '565617', 'product', '931798442189', 'product_catalog', 'v1', 'succeeded', 1, 1, 1, '2026-05-29T08:00:00+00:00', '2026-05-29T08:00:00+00:00', '2026-05-29T08:01:00+00:00');
            INSERT INTO product_sync_jobs (id, shop_id, status, updated_at) VALUES ('sync-real', '565617', 'succeeded', '2026-05-29T08:02:00+00:00');
            INSERT INTO traces (shop_id, answer_status, guardrail_status, rag_hit_count, created_at) VALUES
                ('565617', 'succeeded', 'safe', 1, '2026-05-29T08:03:00+00:00'),
                ('565617', 'failed', 'blocked', 0, '2026-05-29T08:04:00+00:00');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _client_for_dashboard(db_path: Path) -> TestClient:
    os.environ.setdefault("WEB_ADMIN_PASSWORD", "test-admin-password")
    app.dependency_overrides[get_shop_service] = lambda: ShopService(ReadOnlySqlite(db_path))
    app.dependency_overrides[get_dashboard_service] = lambda: DashboardService(ReadOnlySqlite(db_path), db_path=db_path)
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": os.environ["WEB_ADMIN_PASSWORD"]},
    )
    assert response.status_code == 200
    return client


def test_dashboard_summary_uses_real_runtime_tables_and_excludes_secrets(tmp_path):
    db_path = tmp_path / "dashboard.db"
    _create_dashboard_db(db_path)
    client = _client_for_dashboard(db_path)
    try:
        response = client.get("/api/dashboard/summary")
        assert response.status_code == 200
        payload = response.json()
        metrics = {item["key"]: item["value"] for item in payload["metrics"]}
        assert metrics["shop_count"] == 1
        assert metrics["ai_enabled_count"] == 1
        assert metrics["messages_24h"] == 1
        assert metrics["rag_hit_rate"] == "50%"
        assert metrics["llm_error_count"] == 1
        assert metrics["guardrail_count"] == 1
        assert metrics["rag_index_health"] == "正常"
        text = response.text
        assert "remote-session-id" not in text
        assert "DO_NOT_RETURN_PASSWORD" not in text
        assert "DO_NOT_RETURN_COOKIE" not in text
    finally:
        app.dependency_overrides.clear()


def test_shops_dropdown_source_backfills_from_valid_auth_when_shops_empty(tmp_path):
    db_path = tmp_path / "auth_only.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_name TEXT NOT NULL UNIQUE);
            CREATE TABLE shops (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, shop_id TEXT, shop_name TEXT);
            CREATE TABLE shop_auth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                auth_status TEXT NOT NULL,
                safe_display TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT INTO channels (channel_name) VALUES ('pinduoduo');
            INSERT INTO shop_auth (shop_id, platform, auth_status, safe_display, updated_at)
                VALUES ('565617', 'pdd', 'valid', '135***888', '2026-05-29T00:00:00+00:00');
            """
        )
        conn.commit()
    finally:
        conn.close()

    client = _client_for_dashboard(db_path)
    try:
        response = client.get("/api/shops")
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["shop_id"] == "565617"
        assert payload["items"][0]["shop_name"] == "135***888"
    finally:
        app.dependency_overrides.clear()
