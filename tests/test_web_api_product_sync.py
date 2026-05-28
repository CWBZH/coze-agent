import json

from fastapi.testclient import TestClient

from web_api.deps import get_product_sync_service
from web_api.main import app
from web_api.services.product_sync_service import ProductSyncService


class FakeAuthResolver:
    def __init__(self, ok=True):
        self.ok = ok

    def get_cookies(self, shop_id, platform="pdd", user_id=None):
        status = "ok" if self.ok else "missing"
        cookies = {"session": "fake-cookie"} if self.ok else {}
        return type("Auth", (), {"status": status, "cookies": cookies, "user_id": "user-1"})()


class FakeProductManager:
    def __init__(self, fail=False):
        self.fail = fail

    def get_product_list(self, page=1, size=50):
        return {
            "success": True,
            "total": 1,
            "products": [{"goods_id": "goods-1", "goods_name": "商品一", "price": "19.70"}],
        } if page == 1 else {"success": True, "total": 1, "products": []}

    def get_product_detail(self, goods_id):
        if self.fail:
            return {"success": False, "error_msg": "detail_failed"}
        return {"success": True, "product_info": {"goods_id": goods_id, "goods_name": "商品一", "specifications": ["一瓶"]}}


def _client(tmp_path, *, auth_ok=True, fail=False):
    service = ProductSyncService(
        db_path=tmp_path / "sync.db",
        auth_resolver=FakeAuthResolver(ok=auth_ok),
        product_manager_factory=lambda shop_id, user_id, cookies: FakeProductManager(fail=fail),
    )
    service.init_schema()
    app.dependency_overrides[get_product_sync_service] = lambda: service
    return TestClient(app)


def _clear():
    app.dependency_overrides.clear()


def test_create_sync_job_requires_auth(tmp_path):
    client = _client(tmp_path, auth_ok=False)
    try:
        response = client.post("/api/shops/565617/product-sync/jobs", json={"limit": 1})
        assert response.status_code == 409
        assert response.json()["error_type"] == "AUTH_REQUIRED"
    finally:
        _clear()


def test_create_sync_job_writes_product_knowledge_and_does_not_expose_cookie(tmp_path):
    client = _client(tmp_path)
    try:
        response = client.post("/api/shops/565617/product-sync/jobs", json={"limit": 1})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["succeeded_count"] == 1
        assert "fake-cookie" not in response.text

        coverage = client.get("/api/shops/565617/product-sync/coverage")
        assert coverage.status_code == 200
        assert coverage.json()["total"] == 1
        assert coverage.json()["has_price"] == 1
    finally:
        _clear()


def test_sync_item_failure_is_partial_and_retryable(tmp_path):
    client = _client(tmp_path, fail=True)
    try:
        response = client.post("/api/shops/565617/product-sync/jobs", json={"limit": 1})
        assert response.status_code == 200
        job = response.json()
        assert job["status"] == "failed"
        assert job["failed_count"] == 1
    finally:
        _clear()

    retry_client = _client(tmp_path, fail=False)
    try:
        retry = retry_client.post(f"/api/shops/565617/product-sync/jobs/{job['id']}/retry")
        assert retry.status_code == 200
        assert retry.json()["status"] == "succeeded"
    finally:
        _clear()


def test_product_sync_shop_id_isolated(tmp_path):
    client = _client(tmp_path)
    try:
        assert client.post("/api/shops/shop-a/product-sync/jobs", json={"limit": 1}).status_code == 200
        assert client.get("/api/shops/shop-b/product-sync/coverage").json()["total"] == 0
        assert client.get("/api/shops/shop-a/product-sync/coverage").json()["total"] == 1
    finally:
        _clear()
