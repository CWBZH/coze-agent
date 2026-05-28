import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_knowledge_center_service
from web_api.main import app
from web_api.services.knowledge_center_service import KnowledgeCenterService, _FakeEmbeddingClient, _InMemoryVectorStore


def _client_for_db(db_path: Path) -> TestClient:
    service = KnowledgeCenterService(
        db_path,
        default_embedding_client=_FakeEmbeddingClient(dimension=8, model="test-embedding"),
        default_vector_store=_InMemoryVectorStore(),
    )
    service.init_schema()
    app.dependency_overrides[get_knowledge_center_service] = lambda: service
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _create_sop(client: TestClient, title: str = "Shipping SOP", content: str = "Ship safely") -> dict:
    response = client.post(
        "/api/knowledge/sop",
        json={"shop_id": "shop-1", "domain": "logistics_policy", "title": title, "content": content},
    )
    assert response.status_code == 200
    return response.json()


def test_sop_crud_api_and_archive(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        created = _create_sop(client)
        listed = client.get("/api/knowledge/sop?shop_id=shop-1&domain=logistics_policy")
        fetched = client.get(f"/api/knowledge/sop/{created['id']}")
        updated = client.put(
            f"/api/knowledge/sop/{created['id']}",
            json={"title": "Shipping SOP v2", "content": "Updated", "expected_content_hash": created["content_hash"]},
        )
        archived = client.delete(f"/api/knowledge/sop/{created['id']}")

        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert fetched.json()["content"] == "Ship safely"
        assert updated.status_code == 200
        assert updated.json()["title"] == "Shipping SOP v2"
        assert updated.json()["content_hash"] != created["content_hash"]
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
    finally:
        _clear_overrides()


def test_update_sop_with_stale_hash_returns_409(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        created = _create_sop(client)
        response = client.put(
            f"/api/knowledge/sop/{created['id']}",
            json={"content": "Stale update", "expected_content_hash": "stale-hash"},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["status"] == "conflict"
    finally:
        _clear_overrides()


def test_publish_sop_creates_snapshot_version_and_job(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        created = _create_sop(client, content="Version one")
        published = client.post(f"/api/knowledge/sop/{created['id']}/publish").json()
        client.put(f"/api/knowledge/sop/{created['id']}", json={"content": "Version two"})
        version_response = client.get(f"/api/knowledge/versions/{published['version']['id']}")
        job_response = client.get(f"/api/knowledge/index-jobs/{published['index_job']['id']}")
        snapshot = json.loads(version_response.json()["snapshot_json"])

        assert published["version"]["status"] == "active"
        assert published["index_job"]["status"] == "succeeded"
        assert snapshot["content"] == "Version one"
        assert job_response.json()["version_id"] == published["version"]["id"]
    finally:
        _clear_overrides()


def test_publish_sop_runs_real_index_and_activates_version(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        created = _create_sop(client)
        published = client.post(f"/api/knowledge/sop/{created['id']}/publish").json()

        payload = published
        assert payload["index_job"]["status"] == "succeeded"
        assert payload["index_job"]["chunk_count"] >= 1
        assert payload["index_job"]["embedded_count"] == payload["index_job"]["chunk_count"]
        assert payload["version"]["status"] == "active"
        assert payload["version"]["is_active"] == 1
    finally:
        _clear_overrides()


def test_second_publish_run_deactivates_old_active_version(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        created = _create_sop(client, content="Version one")
        first = client.post(f"/api/knowledge/sop/{created['id']}/publish").json()
        client.put(f"/api/knowledge/sop/{created['id']}", json={"content": "Version two"})
        second = client.post(f"/api/knowledge/sop/{created['id']}/publish").json()
        versions = client.get("/api/knowledge/versions?shop_id=shop-1&is_active=true").json()["items"]
        old_version = client.get(f"/api/knowledge/versions/{first['version']['id']}").json()

        assert len(versions) == 1
        assert versions[0]["id"] == second["version"]["id"]
        assert old_version["is_active"] == 0
        assert old_version["status"] == "retired"
    finally:
        _clear_overrides()


def test_real_index_config_failure_does_not_activate_version(tmp_path):
    db_path = tmp_path / "kc.db"
    service = KnowledgeCenterService(db_path)
    service.init_schema()
    app.dependency_overrides[get_knowledge_center_service] = lambda: service
    client = TestClient(app)
    try:
        created = _create_sop(client)
        published = client.post(f"/api/knowledge/sop/{created['id']}/publish").json()
        version = client.get(f"/api/knowledge/versions/{published['version']['id']}").json()

        assert published["index_job"]["status"] == "failed"
        assert version["is_active"] == 0
        assert version["status"] == "failed"
    finally:
        _clear_overrides()


def test_retry_failed_job_does_not_create_new_version(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        created = _create_sop(client)
        published = client.post(f"/api/knowledge/sop/{created['id']}/publish").json()
        job_id = published["index_job"]["id"]
        version_id = published["version"]["id"]
        service: KnowledgeCenterService = app.dependency_overrides[get_knowledge_center_service]()
        service.mark_job_failed(job_id, "fake failure")
        before_versions = client.get("/api/knowledge/versions").json()["total"]

        retry = client.post(f"/api/knowledge/index-jobs/{job_id}/retry")
        after_versions = client.get("/api/knowledge/versions").json()["total"]

        assert retry.status_code == 200
        assert retry.json()["version_id"] == version_id
        assert retry.json()["retry_count"] == 1
        assert before_versions == after_versions
    finally:
        _clear_overrides()


def test_versions_and_index_jobs_list_detail_api(tmp_path):
    client = _client_for_db(tmp_path / "kc.db")
    try:
        created = _create_sop(client)
        published = client.post(f"/api/knowledge/sop/{created['id']}/publish").json()

        versions = client.get("/api/knowledge/versions?shop_id=shop-1&source_type=sop").json()
        version = client.get(f"/api/knowledge/versions/{published['version']['id']}").json()
        jobs = client.get(f"/api/knowledge/index-jobs?version_id={published['version']['id']}").json()
        job = client.get(f"/api/knowledge/index-jobs/{published['index_job']['id']}").json()

        assert versions["total"] == 1
        assert version["snapshot_json"]
        assert jobs["total"] == 1
        assert job["version_id"] == version["id"]
        response_text = json.dumps({"versions": versions, "version": version, "jobs": jobs, "job": job})
        assert "password" not in response_text.lower()
        assert "authorization" not in response_text.lower()
        assert "token" not in response_text.lower()
    finally:
        _clear_overrides()
