from fastapi.testclient import TestClient

from web_api.deps import get_rag_debug_service
from web_api.main import app
from web_api.schemas.products import ProductChunk
from web_api.schemas.rag import RagDebugHit, RagDebugRequest, RagDebugResponse
from web_api.services.rag_debug_service import RagDebugService


class FakeRagDebugService:
    def list_product_chunks(self, **kwargs):
        assert kwargs["goods_id"] == "goods-1"
        return [
            ProductChunk(
                chunk_id="chunk-1",
                shop_id=kwargs.get("shop_id") or "shop-1",
                domain="product_catalog",
                source_type="product",
                source_id="goods-1",
                version="real-product-v1",
                content="full chunk content for local debug",
                content_hash="hash-1",
                metadata={"goods_id": "goods-1", "field": "usage"},
                created_at="2026-05-25T00:00:00Z",
            )
        ], None

    def retrieve_debug(self, request: RagDebugRequest):
        return RagDebugResponse(
            query=request.query,
            shop_id=request.shop_id,
            domain=request.domain,
            version=request.version,
            hits=[
                RagDebugHit(
                    chunk_id="chunk-1",
                    content="full retrieved content for local debug",
                    score=1.0,
                    domain=request.domain,
                    source_type="product",
                    source_id=request.goods_id or "goods-1",
                    version=request.version,
                    metadata={"goods_id": request.goods_id or "goods-1"},
                )
            ],
            connects_pgvector=True,
            calls_ollama=False,
        )


def _client() -> TestClient:
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_product_chunks_returns_warning_when_pgvector_not_configured(monkeypatch):
    monkeypatch.delenv("WEB_API_PGVECTOR_DSN", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_PGVECTOR_DSN", raising=False)
    app.dependency_overrides[get_rag_debug_service] = lambda: RagDebugService(dsn="")
    try:
        response = _client().get("/api/products/goods-1/chunks?shop_id=shop-1")
        assert response.status_code == 200
        payload = response.json()
        assert payload["chunks"] == []
        assert payload["warning"] == "pgvector_not_configured"
        assert "postgresql://" not in response.text
        assert "password" not in response.text.lower()
        assert "fastgpt" not in response.text.lower()
    finally:
        _clear_overrides()


def test_retrieve_debug_returns_warning_when_pgvector_not_configured(monkeypatch):
    monkeypatch.delenv("WEB_API_PGVECTOR_DSN", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_PGVECTOR_DSN", raising=False)
    app.dependency_overrides[get_rag_debug_service] = lambda: RagDebugService(dsn="")
    try:
        response = _client().post(
            "/api/rag/retrieve-debug",
            json={"shop_id": "shop-1", "query": "怎么用", "domain": "product_catalog", "goods_id": "goods-1"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["hits"] == []
        assert payload["connects_pgvector"] is False
        assert payload["calls_ollama"] is False
        assert payload["warning"] == "pgvector_not_configured"
        assert "postgresql://" not in response.text
        assert "fastgpt" not in response.text.lower()
    finally:
        _clear_overrides()


def test_mock_rag_debug_service_can_return_product_chunks():
    app.dependency_overrides[get_rag_debug_service] = lambda: FakeRagDebugService()
    try:
        response = _client().get("/api/products/goods-1/chunks?shop_id=shop-1")
        assert response.status_code == 200
        payload = response.json()
        assert payload["chunks"][0]["chunk_id"] == "chunk-1"
        assert payload["chunks"][0]["content"] == "full chunk content for local debug"
        assert payload["chunks"][0]["metadata"]["goods_id"] == "goods-1"
    finally:
        _clear_overrides()


def test_mock_retrieve_debug_returns_hits_without_ollama_or_secret_values():
    app.dependency_overrides[get_rag_debug_service] = lambda: FakeRagDebugService()
    try:
        response = _client().post(
            "/api/rag/retrieve-debug",
            json={"shop_id": "shop-1", "query": "这个怎么用", "domain": "product_catalog", "goods_id": "goods-1"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["hits"][0]["content"] == "full retrieved content for local debug"
        assert payload["connects_pgvector"] is True
        assert payload["calls_ollama"] is False
        assert "postgresql://" not in response.text
        assert "token" not in response.text.lower()
        assert "fastgpt" not in response.text.lower()
    finally:
        _clear_overrides()
