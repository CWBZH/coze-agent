import json
import sqlite3
from pathlib import Path

from web_api.services.product_sync_service import ProductSyncService


class FakeAuthResolver:
    def __init__(self, ok=True):
        self.ok = ok

    def get_cookies(self, shop_id, platform="pdd", user_id=None):
        status = "ok" if self.ok else "missing"
        cookies = {"session": "fake"} if self.ok else {}
        return type("Auth", (), {"status": status, "cookies": cookies, "user_id": "user-1"})()


class FakeProductManager:
    def __init__(self, fail_detail=False):
        self.fail_detail = fail_detail

    def get_product_list(self, page=1, size=50):
        if page > 1:
            return {"success": True, "products": [], "total": 2}
        return {
            "success": True,
            "total": 2,
            "products": [
                {"goods_id": "goods-1", "goods_name": "商品一", "price": "19.70"},
                {"goods_id": "goods-2", "goods_name": "商品二", "price": "29.90"},
            ],
        }

    def get_product_detail(self, goods_id):
        if self.fail_detail and goods_id == "goods-2":
            return {"success": False, "error_msg": "detail_failed"}
        return {
            "success": True,
            "product_info": {
                "goods_id": goods_id,
                "goods_name": f"详情 {goods_id}",
                "specifications": ["一瓶"],
                "usage": "按页面说明使用",
            },
        }


def _service(db_path: Path, manager: FakeProductManager | None = None, auth_ok=True):
    return ProductSyncService(
        db_path=db_path,
        auth_resolver=FakeAuthResolver(ok=auth_ok),
        product_manager_factory=lambda shop_id, user_id, cookies: manager or FakeProductManager(),
    )


def test_product_sync_writes_product_knowledge_and_coverage(tmp_path):
    db_path = tmp_path / "sync.db"
    service = _service(db_path)

    job = service.create_job("565617", limit=2)

    assert job["status"] == "succeeded"
    assert job["succeeded_count"] == 2
    coverage = service.coverage("565617")
    assert coverage["total"] == 2
    assert coverage["has_price"] == 2
    assert coverage["has_specs"] == 2
    assert coverage["has_usage"] == 2

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT goods_id, raw_detail_json FROM product_knowledge WHERE goods_id='goods-1'").fetchone()
        assert row is not None
        raw = json.loads(row[1])
        assert raw["list_item"]["goods_id"] == "goods-1"
    finally:
        conn.close()


def test_product_sync_partial_failure_and_retry_failed_items(tmp_path):
    db_path = tmp_path / "sync.db"
    service = _service(db_path, FakeProductManager(fail_detail=True))

    job = service.create_job("565617", limit=2)

    assert job["status"] == "partial_failed"
    assert job["succeeded_count"] == 1
    assert job["failed_count"] == 1
    assert any(item["status"] == "failed" for item in job["items"])

    retry_service = _service(db_path, FakeProductManager(fail_detail=False))
    retried = retry_service.retry_failed_items("565617", job["id"])
    assert retried["status"] == "succeeded"
    assert retry_service.coverage("565617")["total"] == 2


def test_product_sync_requires_auth(tmp_path):
    service = _service(tmp_path / "sync.db", auth_ok=False)

    try:
        service.create_job("565617", limit=1)
    except ValueError as exc:
        assert str(exc) == "auth_required"
    else:
        raise AssertionError("expected auth_required")
