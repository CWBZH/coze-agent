import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_product_service, get_shop_service
from web_api.main import app
from web_api.services.product_service import ProductService
from web_api.services.shop_service import ShopService
from web_api.services.sqlite_readonly import ReadOnlySqlite


def _client_for_db(db_path: Path) -> TestClient:
    app.dependency_overrides[get_shop_service] = lambda: ShopService(ReadOnlySqlite(db_path))
    app.dependency_overrides[get_product_service] = lambda: ProductService(ReadOnlySqlite(db_path))
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _create_fake_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE channels (id INTEGER PRIMARY KEY, channel_name TEXT);
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                shop_id TEXT,
                shop_name TEXT
            );
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER,
                user_id TEXT,
                username TEXT,
                password TEXT,
                cookies TEXT,
                status INTEGER
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                shop_id INTEGER,
                buyer_id TEXT,
                updated_at TEXT
            );
            CREATE TABLE product_knowledge (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER,
                goods_id TEXT,
                goods_name TEXT,
                price TEXT,
                price_min INTEGER,
                price_max INTEGER,
                specifications TEXT,
                raw_detail_json TEXT,
                knowledge_status TEXT,
                updated_at TEXT
            );
            """
        )
        conn.execute("INSERT INTO channels (id, channel_name) VALUES (1, 'pinduoduo')")
        conn.execute("INSERT INTO shops (id, channel_id, shop_id, shop_name) VALUES (1, 1, 'shop-real-1', '真实测试店')")
        conn.execute(
            "INSERT INTO accounts (shop_id, user_id, username, password, cookies, status) VALUES (1, 'u1', 'user1', 'DO_NOT_RETURN_PASSWORD', 'DO_NOT_RETURN_COOKIE', 1)"
        )
        conn.execute(
            "INSERT INTO conversations (session_id, shop_id, buyer_id, updated_at) VALUES ('s1', 1, 'b1', '2026-05-25 21:00')"
        )
        raw = {
            "usage": "洁面后取适量涂抹，轻轻推开。",
            "ingredients": "烟酰胺、保湿成分",
            "shelf_life": "三年",
            "warnings": "敏感肌先局部测试",
            "manual_notes": "价格以页面为准",
            "raw_extra": {"debug": True},
        }
        conn.execute(
            """
            INSERT INTO product_knowledge
            (shop_id, goods_id, goods_name, price, specifications, raw_detail_json, knowledge_status, updated_at)
            VALUES (1, 'goods-real-1', '真实商品A', '9.90', ?, ?, 'active', '2026-05-25 21:00')
            """,
            (json.dumps(["规格A", "规格B"], ensure_ascii=False), json.dumps(raw, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def test_shops_api_reads_real_sqlite_without_returning_credentials(tmp_path):
    db_path = tmp_path / "fake.db"
    _create_fake_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/shops")
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["shop_id"] == "shop-real-1"
        assert payload["items"][0]["shop_name"] == "真实测试店"
        assert payload["items"][0]["account_status"] == "active"
        text = response.text
        assert "DO_NOT_RETURN_PASSWORD" not in text
        assert "DO_NOT_RETURN_COOKIE" not in text
    finally:
        _clear_overrides()


def test_shop_detail_counts_real_product_knowledge(tmp_path):
    db_path = tmp_path / "fake.db"
    _create_fake_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/shops/shop-real-1")
        assert response.status_code == 200
        payload = response.json()
        assert payload["shop_id"] == "shop-real-1"
        assert payload["product_knowledge_count"] == 1
        assert payload["sop_coverage"]["product_catalog"] == "available"
        assert payload["sop_coverage"]["logistics_policy"] == "missing"
        assert payload["rag_index_status"]["status"] != "mock_until_pgvector_api"
    finally:
        _clear_overrides()


def test_products_api_reads_real_product_knowledge(tmp_path):
    db_path = tmp_path / "fake.db"
    _create_fake_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/products?shop_id=shop-real-1&q=真实商品")
        assert response.status_code == 200
        product = response.json()["items"][0]
        assert product["goods_id"] == "goods-real-1"
        assert product["goods_name"] == "真实商品A"
        assert product["product_title"] == "真实商品A"
        assert product["price"] == "9.90"
        assert product["specs"] == ["规格A", "规格B"]
        assert product["usage"] == "洁面后取适量涂抹，轻轻推开。"
        assert product["ingredients"] == "烟酰胺、保湿成分"
        assert "masked_goods_id" not in product
    finally:
        _clear_overrides()


def test_product_detail_returns_raw_detail_json_and_empty_chunks(tmp_path):
    db_path = tmp_path / "fake.db"
    _create_fake_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/products/goods-real-1?shop_id=shop-real-1")
        assert response.status_code == 200
        detail = response.json()
        assert detail["raw_detail_json"]["manual_notes"] == "价格以页面为准"
        assert detail["manual_notes"] == "价格以页面为准"
        assert detail["chunks"] == []
    finally:
        _clear_overrides()


def test_product_coverage_counts_real_fields(tmp_path):
    db_path = tmp_path / "fake.db"
    _create_fake_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/products/coverage?shop_id=shop-real-1")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["has_price"] == 1
        assert payload["has_specs"] == 1
        assert payload["has_usage"] == 1
        assert payload["has_ingredients"] == 1
        assert payload["has_shelf_life"] == 1
        assert payload["has_warnings"] == 1
        assert payload["has_manual_notes"] == 1
    finally:
        _clear_overrides()


def test_missing_db_does_not_crash(tmp_path):
    client = _client_for_db(tmp_path / "missing.db")
    try:
        response = client.get("/api/shops")
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["warning"] == "db_missing"
    finally:
        _clear_overrides()


def test_missing_table_does_not_crash(tmp_path):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/products")
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["warning"] == "missing_table:product_knowledge"
    finally:
        _clear_overrides()
