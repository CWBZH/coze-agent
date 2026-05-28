import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_knowledge_center_service, get_product_sync_service, get_shop_onboarding_service
from web_api.main import app
from web_api.services.knowledge_center_service import KnowledgeCenterService
from web_api.services.product_sync_service import ProductSyncService
from web_api.services.remote_browser_service import RemoteBrowserCheckResult, RemoteBrowserSession
from web_api.services.shop_onboarding_service import ShopOnboardingService


class FakeRemoteBrowserWithoutMallId:
    def __init__(self) -> None:
        self.closed: list[str] = []

    def create_session(self, login_session_id: str, login_url: str) -> RemoteBrowserSession:
        return RemoteBrowserSession(
            login_session_id=login_session_id,
            status="ready",
            access_token=f"token-{login_session_id}",
            vnc_url=f"http://127.0.0.1:6088/vnc.html?session={login_session_id}&token=token-{login_session_id}",
        )

    def check_login_success(self, login_session_id: str) -> RemoteBrowserCheckResult:
        return RemoteBrowserCheckResult(
            status="succeeded",
            cookie_value="session=DO_NOT_RETURN_COOKIE",
            account_name="seller_account_10000000000",
        )

    def close_session(self, login_session_id: str) -> None:
        self.closed.append(login_session_id)


def _client(db_path: Path, remote_service: FakeRemoteBrowserWithoutMallId | None = None) -> TestClient:
    onboarding = ShopOnboardingService(db_path=db_path, remote_browser_service=remote_service or FakeRemoteBrowserWithoutMallId())
    onboarding.init_schema()
    product_sync = ProductSyncService(db_path=db_path)
    product_sync.init_schema()
    knowledge = KnowledgeCenterService(db_path)
    knowledge.init_schema()
    app.dependency_overrides[get_shop_onboarding_service] = lambda: onboarding
    app.dependency_overrides[get_product_sync_service] = lambda: product_sync
    app.dependency_overrides[get_knowledge_center_service] = lambda: knowledge
    return TestClient(app)


def _clear() -> None:
    app.dependency_overrides.clear()


def test_remote_browser_auth_without_real_mall_id_does_not_create_remote_shop(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    db_path = tmp_path / "prod_identity.db"
    remote = FakeRemoteBrowserWithoutMallId()
    client = _client(db_path, remote)
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "Production Shop",
                "account_name": "seller_account_10000000000",
                "password": "DO_NOT_RETURN_PASSWORD",
                "runner_mode": "remote_browser",
            },
        ).json()

        checked = client.post(f"/api/shops/onboarding/{session['session_id']}/check-login")

        assert checked.status_code == 200
        payload = checked.json()
        assert payload["status"] == "shop_identity_pending"
        assert payload["shop_id"] is None
        assert payload["shop_identity_status"] == "pending_real_shop_id"
        assert payload["real_shop_id_pending"] is True
        assert "DO_NOT_RETURN_COOKIE" not in checked.text
        assert "DO_NOT_RETURN_PASSWORD" not in checked.text
        assert session["session_id"] in remote.closed

        conn = sqlite3.connect(db_path)
        try:
            shop_ids = [row[0] for row in conn.execute("SELECT shop_id FROM shops").fetchall()]
            auth_shop_ids = [row[0] for row in conn.execute("SELECT shop_id FROM shop_auth").fetchall()]
        finally:
            conn.close()
        assert not any(str(shop_id).startswith("remote-") for shop_id in shop_ids)
        assert not any(str(shop_id).startswith("remote-") for shop_id in auth_shop_ids)
    finally:
        _clear()


def test_unbound_remote_shop_id_blocks_product_sync_with_standard_error(tmp_path):
    client = _client(tmp_path / "prod_identity.db")
    try:
        response = client.post("/api/shops/remote-login123/product-sync/jobs", json={"limit": 1})

        assert response.status_code == 409
        payload = response.json()
        assert payload["error_type"] == "SHOP_ID_NOT_BOUND"
        assert payload["retryable"] is False
        assert payload["trace_id"]
        assert "绑定真实店铺" in payload["next_action"]
    finally:
        _clear()


def test_unbound_remote_shop_id_blocks_enable_ai_with_standard_error(tmp_path):
    client = _client(tmp_path / "prod_identity.db")
    try:
        response = client.post(
            "/api/shops/remote-login123/enable-ai",
            json={"operator": "local_admin", "confirm": True, "override": True, "override_reason": "manual"},
        )

        assert response.status_code == 409
        payload = response.json()
        assert payload["error_type"] == "SHOP_ID_NOT_BOUND"
        assert payload["retryable"] is False
        assert payload["trace_id"]
        assert "绑定真实店铺" in payload["next_action"]
    finally:
        _clear()


def test_unbound_remote_shop_id_blocks_knowledge_publish_with_standard_error(tmp_path):
    client = _client(tmp_path / "prod_identity.db")
    try:
        product_publish = client.post("/api/knowledge/products/goods-1/publish?shop_id=remote-login123")
        assert product_publish.status_code == 409
        assert product_publish.json()["error_type"] == "SHOP_ID_NOT_BOUND"

        created = client.post(
            "/api/knowledge/sop",
            json={"shop_id": "remote-login123", "domain": "logistics_policy", "title": "SOP", "content": "content"},
        )
        assert created.status_code == 200
        sop_publish = client.post(f"/api/knowledge/sop/{created.json()['id']}/publish")
        assert sop_publish.status_code == 409
        assert sop_publish.json()["error_type"] == "SHOP_ID_NOT_BOUND"
    finally:
        _clear()
