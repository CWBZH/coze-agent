import json
import sqlite3
from pathlib import Path

from web_api.services.knowledge_center_service import (
    KnowledgeCenterRepository,
    KnowledgeCenterService,
    build_chunks_from_version_snapshot,
    init_knowledge_center_schema,
)


def _create_product_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE product_knowledge (
                id INTEGER PRIMARY KEY,
                shop_id TEXT,
                goods_id TEXT,
                goods_name TEXT,
                price TEXT,
                specifications TEXT,
                raw_detail_json TEXT,
                knowledge_status TEXT,
                updated_at TEXT
            );
            """
        )
        raw = {
            "usage": "raw usage",
            "ingredients": "raw ingredients",
            "warnings": "raw warnings",
            "shelf_life": "raw shelf life",
            "manual_notes": "raw notes",
        }
        conn.execute(
            """
            INSERT INTO product_knowledge
            (shop_id, goods_id, goods_name, price, specifications, raw_detail_json, knowledge_status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "shop-1",
                "goods-1",
                "Test Product",
                "9.90",
                json.dumps(["raw spec"], ensure_ascii=False),
                json.dumps(raw, ensure_ascii=False),
                "synced",
                "2026-05-26 10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _create_joined_product_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY,
                shop_id TEXT,
                shop_name TEXT
            );
            CREATE TABLE product_knowledge (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER,
                goods_id TEXT,
                goods_name TEXT,
                price TEXT,
                specifications TEXT,
                raw_detail_json TEXT,
                knowledge_status TEXT,
                updated_at TEXT
            );
            """
        )
        conn.execute("INSERT INTO shops (id, shop_id, shop_name) VALUES (7, 'platform-shop-1', 'Joined Shop')")
        conn.execute(
            """
            INSERT INTO product_knowledge
            (shop_id, goods_id, goods_name, price, specifications, raw_detail_json, knowledge_status, updated_at)
            VALUES (7, 'goods-joined-1', 'Joined Product', '19.90', '[]', '{}', 'synced', '2026-05-26')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_safe_init_schema_can_run_repeatedly(tmp_path):
    db_path = tmp_path / "kc.db"

    init_knowledge_center_schema(db_path)
    init_knowledge_center_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'knowledge_%' OR name='product_manual_overrides'"
            )
        }
    finally:
        conn.close()

    assert "knowledge_sop" in tables
    assert "product_manual_overrides" in tables
    assert "knowledge_versions" in tables
    assert "knowledge_index_jobs" in tables


def test_create_update_list_archive_sop(tmp_path):
    db_path = tmp_path / "kc.db"
    repo = KnowledgeCenterRepository(db_path)
    repo.init_schema()

    sop = repo.create_sop("shop-1", "logistics_policy", "Shipping SOP", "Original content")
    updated = repo.update_sop(sop["id"], title="Shipping SOP v2", content="Updated content")
    records = repo.list_sop(shop_id="shop-1", domain="logistics_policy")
    archived = repo.archive_sop(sop["id"])

    assert updated["title"] == "Shipping SOP v2"
    assert updated["content"] == "Updated content"
    assert len(records) == 1
    assert archived["status"] == "archived"


def test_product_override_upsert_and_effective_view_rules(tmp_path):
    db_path = tmp_path / "kc.db"
    _create_product_db(db_path)
    service = KnowledgeCenterService(db_path)
    service.init_schema()

    service.upsert_override(
        "shop-1",
        "goods-1",
        goods_name="Test Product",
        usage_override="manual usage",
        ingredients_override="",
        warnings_override="manual warnings",
        price_note_override="manual price note only",
    )

    effective = service.build_effective_product_knowledge("shop-1", "goods-1")
    fields = effective["fields"]

    assert fields["usage"]["value"] == "manual usage"
    assert fields["usage"]["source"] == "manual_override"
    assert fields["ingredients"]["value"] == "raw ingredients"
    assert fields["ingredients"]["source"] == "raw"
    assert fields["warnings"]["value"] == "manual warnings"
    assert fields["price"]["value"] == "9.90"
    assert fields["price"]["source"] == "raw"
    assert fields["price_note"]["value"] == "manual price note only"
    assert fields["price_note"]["source"] == "manual_override"


def test_product_version_chunks_keep_field_metadata():
    version = {
        "id": 29,
        "shop_id": "565617",
        "source_type": "product",
        "source_id": "773044930700",
        "domain": "product_catalog",
        "version": "product-773044930700-20260531073301",
        "content_hash": "content-hash",
        "created_by": "local_admin",
        "snapshot_json": json.dumps(
            {
                "domain": "product_catalog",
                "goods_id": "773044930700",
                "goods_name": "YACN牡丹花素颜霜",
                "fields": {
                    "shelf_life": {"source": "manual_override", "value": "3年（开封后建议在12个月内用完）"},
                    "usage": {"source": "manual_override", "value": "取适量涂抹后按摩吸收。"},
                },
            },
            ensure_ascii=False,
        ),
    }

    chunks = build_chunks_from_version_snapshot(version, {"index_run_id": "idx-test"})

    assert chunks
    metadata = chunks[0].metadata
    assert metadata["goods_id"] == "773044930700"
    assert metadata["goods_name"] == "YACN牡丹花素颜霜"
    assert metadata["fields"]["shelf_life"]["source"] == "manual_override"
    assert metadata["fields"]["shelf_life"]["value"] == "3年（开封后建议在12个月内用完）"


def test_publish_sop_creates_immutable_version_and_index_job(tmp_path):
    db_path = tmp_path / "kc.db"
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    sop = service.create_sop("shop-1", "sensitive_user_safety", "Safety SOP", "Version one")

    published = service.publish_sop("shop-1", sop["id"], run_index=False)
    service.update_sop(sop["id"], content="Version two")
    version = service.get_version(published["version"]["id"])
    job = service.get_index_job(published["job"]["id"])
    snapshot = json.loads(version["snapshot_json"])

    assert version["status"] == "pending_index"
    assert job["status"] == "pending"
    assert job["version_id"] == version["id"]
    assert snapshot["content"] == "Version one"
    assert service.get_sop(sop["id"])["content"] == "Version two"


def test_publish_product_creates_effective_snapshot_without_modifying_raw_product(tmp_path):
    db_path = tmp_path / "kc.db"
    _create_product_db(db_path)
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    service.upsert_override("shop-1", "goods-1", usage_override="manual usage")

    published = service.publish_product("shop-1", "goods-1")
    version = service.get_version(published["version"]["id"])
    snapshot = json.loads(version["snapshot_json"])
    job = service.get_index_job(published["job"]["id"])

    assert snapshot["source_type"] == "product"
    assert snapshot["fields"]["usage"]["value"] == "manual usage"
    assert snapshot["fields"]["usage"]["source"] == "manual_override"
    assert snapshot["fields"]["price"]["value"] == "9.90"
    assert job["version_id"] == version["id"]
    conn = sqlite3.connect(db_path)
    try:
        raw_usage = json.loads(
            conn.execute("SELECT raw_detail_json FROM product_knowledge WHERE goods_id='goods-1'").fetchone()[0]
        )["usage"]
    finally:
        conn.close()
    assert raw_usage == "raw usage"


def test_effective_product_supports_platform_shop_id_join(tmp_path):
    db_path = tmp_path / "kc.db"
    _create_joined_product_db(db_path)
    service = KnowledgeCenterService(db_path)
    service.init_schema()

    effective = service.build_effective_product_knowledge("platform-shop-1", "goods-joined-1")

    assert effective["goods_id"] == "goods-joined-1"
    assert effective["fields"]["price"]["value"] == "19.90"
    assert effective["fields"]["goods_name"]["value"] == "Joined Product"


def test_retry_job_keeps_same_version_id(tmp_path):
    db_path = tmp_path / "kc.db"
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    sop = service.create_sop("shop-1", "promotion_policy", "Promo SOP", "Promo content")
    published = service.publish_sop("shop-1", sop["id"])
    version_id = published["version"]["id"]
    job_id = published["job"]["id"]

    service.mark_job_failed(job_id, "temporary failure")
    retried = service.retry_job(job_id)

    assert retried["version_id"] == version_id
    assert retried["status"] == "retrying"
    assert retried["retry_count"] == 1
