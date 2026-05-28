import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_shop_onboarding_service
from web_api.main import app
from web_api.services.product_sync_service import ProductSyncService
from web_api.services.shop_auth_service import AuthSavePayload
from web_api.services.shop_onboarding_service import ShopOnboardingService


def _client(tmp_path: Path) -> tuple[TestClient, ShopOnboardingService, Path]:
    db_path = tmp_path / "ai_enablement.db"
    service = ShopOnboardingService(db_path=db_path)
    service.init_schema()
    app.dependency_overrides[get_shop_onboarding_service] = lambda: service
    return TestClient(app), service, db_path


def _clear() -> None:
    app.dependency_overrides.clear()


def _save_auth(service: ShopOnboardingService, shop_id: str = "565617") -> None:
    service.auth_service.save_auth(
        AuthSavePayload(
            shop_id=shop_id,
            shop_name="测试店铺",
            platform="pdd",
            account_name="seller_10000000000",
            user_id="seller-user",
            cookie_value="session=fake-auth",
        )
    )


def _seed_product_sync(db_path: Path, shop_id: str = "565617") -> None:
    ProductSyncService(db_path=db_path).init_schema()
    now = "2026-05-28T00:00:00+00:00"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT OR IGNORE INTO channels (channel_name, description) VALUES ('pinduoduo', 'PDD')")
        channel_id = conn.execute("SELECT id FROM channels WHERE channel_name='pinduoduo'").fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO shops (channel_id, shop_id, shop_name, created_at) VALUES (?, ?, ?, ?)",
            (channel_id, shop_id, "测试店铺", now),
        )
        internal_shop_id = conn.execute(
            "SELECT id FROM shops WHERE channel_id=? AND shop_id=?",
            (channel_id, shop_id),
        ).fetchone()[0]
        coverage = {
            "total": 1,
            "has_price": 1,
            "has_specs": 1,
            "has_usage": 0,
            "has_warnings": 0,
        }
        conn.execute(
            """
            INSERT INTO product_sync_jobs
                (id, shop_id, internal_shop_id, status, mode, total_count, succeeded_count, failed_count,
                 skipped_count, coverage_json, created_by, created_at, started_at, finished_at, updated_at)
            VALUES ('psync-ready', ?, ?, 'succeeded', 'full', 1, 1, 0, 0, ?, 'local_admin', ?, ?, ?, ?)
            """,
            (shop_id, internal_shop_id, json.dumps(coverage), now, now, now, now),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO product_knowledge
                (shop_id, goods_id, goods_name, price, specifications, raw_detail_json, knowledge_status, created_at, updated_at)
            VALUES (?, 'goods-1', '商品一', '19.70', '一瓶', '{}', 'synced', ?, ?)
            """,
            (internal_shop_id, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def test_checklist_reports_missing_auth_and_product_sync(tmp_path):
    client, _, _ = _client(tmp_path)
    try:
        response = client.get("/api/shops/565617/onboarding-checklist")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ready_for_ai"] is False
        assert "auth_valid" in payload["blocking_items"]
        assert "product_sync_completed" in payload["blocking_items"]
        items = {item["key"]: item for item in payload["items"]}
        assert items["auth_valid"]["status"] == "failed"
        assert items["product_sync_completed"]["status"] == "failed"
        assert "fake-auth" not in response.text
    finally:
        _clear()


def test_mark_no_send_validation_passed_updates_checklist(tmp_path):
    client, service, db_path = _client(tmp_path)
    try:
        _save_auth(service)
        _seed_product_sync(db_path)

        before = client.get("/api/shops/565617/onboarding-checklist").json()
        assert "no_send_validated" in before["blocking_items"]

        marked = client.post(
            "/api/shops/565617/onboarding-validation/mark-passed",
            json={"operator": "local_admin", "summary": "已完成推荐问题 no-send 验收"},
        )

        assert marked.status_code == 200
        assert marked.json()["status"] == "passed"

        after = client.get("/api/shops/565617/onboarding-checklist").json()
        items = {item["key"]: item for item in after["items"]}
        assert items["no_send_validated"]["status"] == "passed"
    finally:
        _clear()


def test_enable_ai_requires_ready_checklist_without_override(tmp_path):
    client, service, _ = _client(tmp_path)
    try:
        _save_auth(service)

        response = client.post(
            "/api/shops/565617/enable-ai",
            json={"operator": "local_admin", "confirm": True},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "checklist_not_ready"
        assert "product_sync_completed" in response.text
    finally:
        _clear()


def test_enable_ai_with_ready_checklist_and_disable(tmp_path):
    client, service, db_path = _client(tmp_path)
    try:
        _save_auth(service)
        _seed_product_sync(db_path)
        client.post(
            "/api/shops/565617/onboarding-validation/mark-passed",
            json={"operator": "local_admin", "summary": "已完成推荐问题 no-send 验收"},
        )

        enabled = client.post(
            "/api/shops/565617/enable-ai",
            json={"operator": "local_admin", "confirm": True},
        )

        assert enabled.status_code == 200
        assert enabled.json()["ai_enabled"] is True
        assert "fake-auth" not in enabled.text

        status = client.get("/api/shops/565617/ai-status")
        assert status.status_code == 200
        assert status.json()["ai_enabled"] is True

        disabled = client.post(
            "/api/shops/565617/disable-ai",
            json={"operator": "local_admin", "reason": "manual_disable"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["ai_enabled"] is False

        audit_rows = sqlite3.connect(db_path).execute(
            "SELECT action FROM web_admin_audit_log WHERE shop_id=? ORDER BY created_at",
            ("565617",),
        ).fetchall()
        actions = [row[0] for row in audit_rows]
        assert "onboarding_validation_mark_passed" in actions
        assert "enable_ai" in actions
        assert "disable_ai" in actions
    finally:
        _clear()


def test_enable_ai_override_requires_reason_and_records_override(tmp_path):
    client, service, _ = _client(tmp_path)
    try:
        _save_auth(service)

        missing_reason = client.post(
            "/api/shops/565617/enable-ai",
            json={"operator": "local_admin", "confirm": True, "override": True},
        )
        assert missing_reason.status_code == 400
        assert missing_reason.json()["detail"]["error"] == "override_reason_required"

        enabled = client.post(
            "/api/shops/565617/enable-ai",
            json={
                "operator": "local_admin",
                "confirm": True,
                "override": True,
                "override_reason": "灰度人工确认通过",
            },
        )
        assert enabled.status_code == 200
        assert enabled.json()["ai_enabled"] is True
        assert enabled.json()["override_enabled"] is True
    finally:
        _clear()


def test_worker_status_is_safe_readonly_and_shop_isolated(tmp_path):
    client, service, db_path = _client(tmp_path)
    try:
        _save_auth(service, "shop-a")
        _seed_product_sync(db_path, "shop-a")
        client.post(
            "/api/shops/shop-a/onboarding-validation/mark-passed",
            json={"operator": "local_admin", "summary": "shop-a passed"},
        )
        client.post("/api/shops/shop-a/enable-ai", json={"operator": "local_admin", "confirm": True})

        shop_b_status = client.get("/api/shops/shop-b/ai-status").json()
        assert shop_b_status["ai_enabled"] is False

        worker = client.get("/api/shops/shop-a/worker-status")
        assert worker.status_code == 200
        assert worker.json()["status"] == "unknown"
        assert worker.json()["websocket_status"] == "unknown"
        assert "fake-auth" not in worker.text
    finally:
        _clear()
