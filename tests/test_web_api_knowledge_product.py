import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from web_api.deps import get_knowledge_center_service
from web_api.main import app
from web_api.services.knowledge_center_service import KnowledgeCenterService


def _client_for_db(db_path: Path) -> TestClient:
    _create_product_db(db_path)
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    app.dependency_overrides[get_knowledge_center_service] = lambda: service
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


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
            "warnings": "raw warning",
            "shelf_life": "raw shelf life",
            "manual_notes": "raw note",
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
                "Raw Product",
                "9.90",
                json.dumps(["raw spec"], ensure_ascii=False),
                json.dumps(raw, ensure_ascii=False),
                "synced",
                "2026-05-27 10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _raw_detail_json(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        value = conn.execute("SELECT raw_detail_json FROM product_knowledge WHERE goods_id='goods-1'").fetchone()[0]
        return json.loads(value)
    finally:
        conn.close()


def _put_override(client: TestClient, expected_content_hash: str | None = None) -> dict:
    payload = {
        "goods_name": "Manual Product Name",
        "usage_override": "manual usage",
        "ingredients_override": "",
        "warnings_override": "manual warning",
        "shelf_life_override": "",
        "manual_notes": "manual note",
        "specs_override": "manual spec",
        "price_note_override": "manual price note",
    }
    if expected_content_hash is not None:
        payload["expected_content_hash"] = expected_content_hash
    response = client.put("/api/knowledge/products/goods-1/overrides?shop_id=shop-1", json=payload)
    assert response.status_code == 200
    return response.json()


def test_get_missing_override_returns_empty_draft(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        response = client.get("/api/knowledge/products/goods-1/overrides?shop_id=shop-1")

        assert response.status_code == 200
        payload = response.json()
        assert payload["shop_id"] == "shop-1"
        assert payload["goods_id"] == "goods-1"
        assert payload["status"] == "draft"
        assert payload["usage_override"] == ""
        assert payload["content_hash"] == ""
    finally:
        _clear_overrides()


def test_put_override_saves_without_modifying_product_knowledge_and_stale_hash_conflicts(tmp_path):
    db_path = tmp_path / "kc.db"
    client = _client_for_db(db_path)
    original_raw = _raw_detail_json(db_path)
    try:
        saved = _put_override(client)
        conflict = client.put(
            "/api/knowledge/products/goods-1/overrides?shop_id=shop-1",
            json={"usage_override": "stale", "expected_content_hash": "stale-hash"},
        )

        assert saved["usage_override"] == "manual usage"
        assert saved["price_note_override"] == "manual price note"
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["status"] == "conflict"
        assert _raw_detail_json(db_path) == original_raw
    finally:
        _clear_overrides()


def test_effective_view_applies_override_rules_and_missing_sources(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        saved = _put_override(client)
        effective_response = client.get("/api/knowledge/products/goods-1/effective?shop_id=shop-1")
        effective = effective_response.json()
        fields = effective["fields"]

        assert effective_response.status_code == 200
        assert effective["goods_name"] == "Manual Product Name"
        assert fields["usage"]["value"] == "manual usage"
        assert fields["usage"]["source"] == "manual_override"
        assert fields["warnings"]["value"] == "manual warning"
        assert fields["warnings"]["source"] == "manual_override"
        assert fields["shelf_life"]["value"] == "raw shelf life"
        assert fields["shelf_life"]["source"] == "raw"
        assert fields["ingredients"]["value"] == ""
        assert fields["ingredients"]["source"] == "missing"
        assert fields["price"]["value"] == "9.90"
        assert fields["price"]["source"] == "raw"
        assert fields["price_note"]["value"] == "manual price note"
        assert fields["price_note"]["source"] == "manual_override"
        assert effective["override"]["content_hash"] == saved["content_hash"]
    finally:
        _clear_overrides()


def test_publish_product_creates_snapshot_version_and_index_job(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        _put_override(client)
        published = client.post("/api/knowledge/products/goods-1/publish?shop_id=shop-1")
        payload = published.json()
        version = client.get(f"/api/knowledge/versions/{payload['version']['id']}").json()
        snapshot = json.loads(version["snapshot_json"])

        assert published.status_code == 200
        assert payload["version"]["source_type"] == "product"
        assert payload["version"]["status"] == "pending_index"
        assert payload["index_job"]["status"] == "pending"
        assert payload["index_job"]["version_id"] == payload["version"]["id"]
        assert snapshot["source_type"] == "product"
        assert snapshot["goods_id"] == "goods-1"
        assert snapshot["fields"]["usage"]["source"] == "manual_override"
        assert snapshot["raw"]["price"] == "9.90"
        assert snapshot["override"]["usage_override"] == "manual usage"
    finally:
        _clear_overrides()


def test_product_snapshot_is_immutable_after_override_changes(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        _put_override(client)
        published = client.post("/api/knowledge/products/goods-1/publish?shop_id=shop-1").json()
        client.put(
            "/api/knowledge/products/goods-1/overrides?shop_id=shop-1",
            json={"usage_override": "changed usage"},
        )
        version = client.get(f"/api/knowledge/versions/{published['version']['id']}").json()
        snapshot = json.loads(version["snapshot_json"])

        assert snapshot["fields"]["usage"]["value"] == "manual usage"
        assert snapshot["override"]["usage_override"] == "manual usage"
    finally:
        _clear_overrides()


def test_run_fake_index_job_activates_product_version_and_second_publish_retires_old(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        _put_override(client)
        first = client.post("/api/knowledge/products/goods-1/publish?shop_id=shop-1").json()
        first_run = client.post(f"/api/knowledge/index-jobs/{first['index_job']['id']}/run").json()
        client.put(
            "/api/knowledge/products/goods-1/overrides?shop_id=shop-1",
            json={"usage_override": "changed usage"},
        )
        second = client.post("/api/knowledge/products/goods-1/publish?shop_id=shop-1").json()
        second_run = client.post(f"/api/knowledge/index-jobs/{second['index_job']['id']}/run").json()
        active = client.get(
            "/api/knowledge/versions?shop_id=shop-1&source_type=product&source_id=goods-1&is_active=true"
        ).json()["items"]
        old = client.get(f"/api/knowledge/versions/{first_run['version']['id']}").json()

        assert first_run["version"]["status"] == "active"
        assert second_run["version"]["status"] == "active"
        assert len(active) == 1
        assert active[0]["id"] == second_run["version"]["id"]
        assert old["is_active"] == 0
        assert old["status"] == "retired"
    finally:
        _clear_overrides()


def test_retry_failed_product_job_does_not_create_new_version(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        published = client.post("/api/knowledge/products/goods-1/publish?shop_id=shop-1").json()
        service: KnowledgeCenterService = app.dependency_overrides[get_knowledge_center_service]()
        service.mark_job_failed(published["index_job"]["id"], "fake failure")
        before_total = client.get("/api/knowledge/versions").json()["total"]
        retry = client.post(f"/api/knowledge/index-jobs/{published['index_job']['id']}/retry").json()
        after_total = client.get("/api/knowledge/versions").json()["total"]

        assert retry["version_id"] == published["version"]["id"]
        assert retry["retry_count"] == 1
        assert before_total == after_total
    finally:
        _clear_overrides()


def test_version_chunks_returns_warning_when_pgvector_missing(tmp_path, monkeypatch):
    client = _client_for_db(tmp_path / "kc.db")
    monkeypatch.delenv("AI_WORKFLOW_PGVECTOR_DSN", raising=False)
    monkeypatch.delenv("WEB_API_PGVECTOR_DSN", raising=False)
    try:
        published = client.post("/api/knowledge/products/goods-1/publish?shop_id=shop-1").json()
        response = client.get(f"/api/knowledge/versions/{published['version']['id']}/chunks")

        assert response.status_code == 200
        payload = response.json()
        assert payload["version_id"] == published["version"]["id"]
        assert payload["chunks"] == []
        assert payload["warning"] == "pgvector_not_configured"
        assert "password" not in json.dumps(payload).lower()
    finally:
        _clear_overrides()


def test_version_chunks_returns_version_bound_chunks_from_pgvector(tmp_path, monkeypatch):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        published = client.post("/api/knowledge/products/goods-1/publish?shop_id=shop-1").json()
        version_id = published["version"]["id"]
        monkeypatch.setenv("AI_WORKFLOW_PGVECTOR_DSN", "postgresql://user:secret@example.local:5432/db")

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, sql, params):
                assert "metadata_json ->> 'version_id'" in sql
                assert params[0] == str(version_id)
                return self

            def fetchall(self):
                return [
                    (
                        "chunk-1",
                        "shop-1",
                        "product_catalog",
                        "product",
                        "goods-1",
                        "product-goods-1-v1",
                        "usage [manual_override]: clean usage",
                        "content-hash",
                        {
                            "version_id": version_id,
                            "chunk_hash": "chunk-hash",
                            "index_run_id": "idx-test",
                        },
                        "2026-05-27T00:00:00+00:00",
                        "idx-test",
                    )
                ]

        class FakePsycopg:
            @staticmethod
            def connect(_dsn):
                return FakeConnection()

        monkeypatch.setitem(__import__("sys").modules, "psycopg", SimpleNamespace(connect=FakePsycopg.connect))
        response = client.get(f"/api/knowledge/versions/{version_id}/chunks")

        assert response.status_code == 200
        payload = response.json()
        assert payload["warning"] is None
        assert payload["chunks"][0]["version_id"] == version_id
        assert payload["chunks"][0]["index_run_id"] == "idx-test"
        assert "clean usage" in payload["chunks"][0]["content"]
        assert "secret" not in json.dumps(payload).lower()
    finally:
        _clear_overrides()
