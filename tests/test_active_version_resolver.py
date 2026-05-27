import sqlite3

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.active_version import ActiveVersionResolver
from web_api.services.knowledge_center_service import KnowledgeCenterService


def _create_product_table(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE product_knowledge (
                id INTEGER PRIMARY KEY,
                shop_id TEXT NOT NULL,
                goods_id TEXT NOT NULL,
                goods_name TEXT,
                price TEXT,
                specifications TEXT,
                raw_detail_json TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO product_knowledge
            (shop_id, goods_id, goods_name, price, specifications, raw_detail_json, updated_at)
            VALUES ('shop-1', 'goods-1', 'Test Product', '9.90', '1 bottle', '{}', '2026-01-01T00:00:00+00:00')
            """
        )


def test_resolver_returns_active_product_version(tmp_path):
    db_path = tmp_path / "kc.db"
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    _create_product_table(db_path)
    published = service.publish_product("shop-1", "goods-1")
    active = service.activate_version(published["version"]["id"])

    resolved = ActiveVersionResolver(db_path).get_active_version(
        "shop-1",
        source_type="product",
        domain="product_catalog",
        source_id="goods-1",
    )

    assert resolved.resolved is True
    assert resolved.version_id == active["id"]
    assert resolved.source_type == "product"
    assert resolved.source_id == "goods-1"
    assert resolved.filters["version_id"] == str(active["id"])


def test_resolver_returns_latest_active_sop_domain_version(tmp_path):
    db_path = tmp_path / "kc.db"
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    first = service.create_sop("shop-1", "logistics_policy", "Old", "old content")
    first_pub = service.publish_sop("shop-1", first["id"])
    service.activate_version(first_pub["version"]["id"])
    second = service.create_sop("shop-1", "logistics_policy", "New", "new content")
    second_pub = service.publish_sop("shop-1", second["id"])
    active = service.activate_version(second_pub["version"]["id"])

    resolved = ActiveVersionResolver(db_path).get_active_version(
        "shop-1",
        source_type="sop",
        domain="logistics_policy",
    )

    assert resolved.resolved is True
    assert resolved.version_id == active["id"]
    assert resolved.source_type == "sop"
    assert resolved.domain == "logistics_policy"
    assert resolved.filters["version_id"] == str(active["id"])


def test_resolver_missing_active_version_does_not_crash(tmp_path):
    db_path = tmp_path / "kc.db"
    service = KnowledgeCenterService(db_path)
    service.init_schema()

    resolved = ActiveVersionResolver(db_path).get_active_version(
        "shop-1",
        source_type="sop",
        domain="promotion_policy",
    )

    assert resolved.resolved is False
    assert resolved.fallback is True
    assert resolved.missing_reason == "active_version_not_found"
    assert resolved.filters == {}
