import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_knowledge_center_service
from web_api.main import app
from web_api.services.knowledge_center_service import KnowledgeCenterService, _FakeEmbeddingClient, _InMemoryVectorStore


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
                json.dumps({"usage": "raw usage", "warnings": "raw warning"}, ensure_ascii=False),
                "synced",
                "2026-05-27 10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _service(db_path: Path, *, with_product: bool = False) -> KnowledgeCenterService:
    if with_product:
        _create_product_db(db_path)
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    return service


def _publish_sop(service: KnowledgeCenterService, content: str = "物流以订单页为准") -> dict:
    sop = service.create_sop("shop-1", "logistics_policy", "Shipping SOP", content)
    return service.publish_sop("shop-1", sop["id"])


def _fake_embedder() -> _FakeEmbeddingClient:
    return _FakeEmbeddingClient(dimension=8, model="fake-bge-m3")


def test_real_index_missing_env_fails_without_activating(monkeypatch, tmp_path):
    for key in ("AI_WORKFLOW_PGVECTOR_DSN", "AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL"):
        monkeypatch.delenv(key, raising=False)
    service = _service(tmp_path / "kc.db")
    published = _publish_sop(service)

    result = service.run_index_job(
        published["job"]["id"],
        mode="real",
        embedding_provider="ollama",
        vector_store_provider="pgvector",
    )

    assert result["index_mode"] == "real"
    assert result["error_type"] == "config_missing"
    assert result["index_job"]["status"] == "failed"
    assert result["version"]["is_active"] == 0
    assert "postgresql://" not in (result["index_job"].get("error_summary") or "")


def test_real_index_with_fake_providers_succeeds_and_activates_sop(tmp_path):
    service = _service(tmp_path / "kc.db")
    published = _publish_sop(service)
    store = _InMemoryVectorStore()

    result = service.run_real_index_job(
        published["job"]["id"],
        embedding_client=_fake_embedder(),
        vector_store=store,
    )

    assert result["index_job"]["status"] == "succeeded"
    assert result["index_job"]["chunk_count"] >= 1
    assert result["index_job"]["embedded_count"] == result["index_job"]["chunk_count"]
    assert result["index_job"]["indexed_count"] == result["index_job"]["chunk_count"]
    assert result["version"]["status"] == "active"
    assert result["version"]["is_active"] == 1
    assert len(store._items) == result["index_job"]["chunk_count"]


def test_real_index_reads_snapshot_only_not_changed_sop_draft(tmp_path):
    service = _service(tmp_path / "kc.db")
    sop = service.create_sop("shop-1", "logistics_policy", "Shipping SOP", "snapshot content")
    published = service.publish_sop("shop-1", sop["id"])
    service.update_sop(sop["id"], content="changed draft content")
    store = _InMemoryVectorStore()

    service.run_real_index_job(published["job"]["id"], embedding_client=_fake_embedder(), vector_store=store)

    contents = "\n".join(item[0].content for item in store._items.values())
    assert "snapshot content" in contents
    assert "changed draft content" not in contents


def test_product_snapshot_chunks_include_field_sources(tmp_path):
    service = _service(tmp_path / "kc.db", with_product=True)
    service.upsert_override("shop-1", "goods-1", usage_override="manual usage", price_note_override="manual note")
    published = service.publish_product("shop-1", "goods-1")
    store = _InMemoryVectorStore()

    service.run_real_index_job(published["job"]["id"], embedding_client=_fake_embedder(), vector_store=store)

    content = "\n".join(item[0].content for item in store._items.values())
    metadata = next(iter(store._items.values()))[0].metadata
    assert "usage [manual_override]: manual usage" in content
    assert "price [raw]: 9.90" in content
    assert "price_note [manual_override]: manual note" in content
    assert metadata["version_id"] == published["version"]["id"]
    assert metadata["source_type"] == "product"
    assert metadata["chunk_hash"]


class _FailAfterUpsertStore(_InMemoryVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    def upsert(self, chunk, vector, *, embedding_model: str = "bge-m3") -> None:
        super().upsert(chunk, vector, embedding_model=embedding_model)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated pgvector upsert failure")


def test_retry_same_real_job_is_idempotent_for_chunks(tmp_path):
    service = _service(tmp_path / "kc.db")
    published = _publish_sop(service)
    store = _FailAfterUpsertStore()

    failed = service.run_real_index_job(published["job"]["id"], embedding_client=_fake_embedder(), vector_store=store)
    before_count = len(store._items)
    retried = service.retry_job(published["job"]["id"])
    succeeded = service.run_real_index_job(retried["id"], embedding_client=_fake_embedder(), vector_store=store)

    assert failed["index_job"]["status"] == "failed"
    assert succeeded["index_job"]["status"] == "succeeded"
    assert len(store._items) == before_count == succeeded["index_job"]["chunk_count"]
    assert succeeded["index_job"]["version_id"] == published["version"]["id"]


def test_failed_real_index_does_not_replace_old_active(tmp_path):
    service = _service(tmp_path / "kc.db")
    first = _publish_sop(service, content="first active")
    service.run_real_index_job(first["job"]["id"], embedding_client=_fake_embedder(), vector_store=_InMemoryVectorStore())
    second = _publish_sop(service, content="second pending")
    failing_store = _FailAfterUpsertStore()

    failed = service.run_real_index_job(second["job"]["id"], embedding_client=_fake_embedder(), vector_store=failing_store)
    active = service.list_active_versions("shop-1")

    assert failed["index_job"]["status"] == "failed"
    assert failed["version"]["is_active"] == 0
    assert len(active) == 1
    assert active[0]["id"] == first["version"]["id"]


def test_run_index_api_defaults_to_fake_and_accepts_explicit_real_missing_env(monkeypatch, tmp_path):
    for key in ("AI_WORKFLOW_PGVECTOR_DSN", "AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL"):
        monkeypatch.delenv(key, raising=False)
    service = _service(tmp_path / "kc.db")
    published = _publish_sop(service)
    app.dependency_overrides[get_knowledge_center_service] = lambda: service
    client = TestClient(app)
    try:
        fake_response = client.post(f"/api/knowledge/index-jobs/{published['job']['id']}/run")
        second = _publish_sop(service, content="real missing")
        real_response = client.post(
            f"/api/knowledge/index-jobs/{second['job']['id']}/run",
            json={"mode": "real", "embedding_provider": "ollama", "vector_store": "pgvector"},
        )

        assert fake_response.status_code == 200
        assert fake_response.json()["index_mode"] == "fake"
        assert real_response.status_code == 200
        assert real_response.json()["error_type"] == "config_missing"
        assert real_response.json()["version"]["is_active"] == 0
        assert "fastgpt" not in json.dumps(real_response.json()).lower()
    finally:
        app.dependency_overrides.clear()
