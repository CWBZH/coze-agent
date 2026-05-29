from types import SimpleNamespace

from fastapi.testclient import TestClient

from web_api.deps import get_live_chat_service
from web_api.main import app
from web_api.services.internal_engine_adapter import WebInternalEngineAdapter, WebEngineOptions
from web_api.services.live_chat_service import LiveChatService
from web_api.services.trace_service import TraceService


def _client(service: LiveChatService) -> TestClient:
    app.dependency_overrides[get_live_chat_service] = lambda: service
    return TestClient(app)


def _assert_no_secret_values(text: str) -> None:
    lowered = text.lower()
    forbidden = ["bearer ", "ark-", "postgresql://", "authorization:", "pdd_session="]
    assert all(value not in lowered for value in forbidden)


def test_default_facade_mode_does_not_call_real_engine():
    service = LiveChatService(trace_service=TraceService())
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={"shop_id": "323473738", "message": "这个多少钱", "no_send": True},
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["engine_mode"] == "facade"
    assert trace["engine_adapter_status"] == "skipped"
    assert trace["real_engine_called"] is False
    assert trace["calls_llm"] is False
    assert trace["calls_ollama"] is False
    assert trace["connects_pgvector"] is False
    assert trace["sends_pdd"] is False
    assert "fastgpt" not in response.text.lower()
    _assert_no_secret_values(response.text)


def test_real_engine_missing_environment_falls_back_without_external_calls(monkeypatch):
    for key in (
        "AI_WORKFLOW_PGVECTOR_DSN",
        "AI_WORKFLOW_OLLAMA_BASE_URL",
        "AI_WORKFLOW_EMBEDDING_MODEL",
        "AI_WORKFLOW_LLM_BASE_URL",
        "AI_WORKFLOW_LLM_MODEL",
        "AI_WORKFLOW_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    service = LiveChatService(trace_service=TraceService())
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "什么时候发货",
            "use_real_engine": True,
            "use_real_pgvector": True,
            "use_real_ollama": True,
            "use_real_llm": True,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["engine_mode"] == "facade"
    assert trace["engine_adapter_status"] == "config_missing"
    assert trace["engine_adapter_error_type"] == "missing_env"
    assert trace["real_engine_called"] is False
    assert trace["calls_llm"] is False
    assert trace["calls_ollama"] is False
    assert trace["connects_pgvector"] is False
    assert trace["sends_pdd"] is False
    assert "fastgpt" not in response.text.lower()
    _assert_no_secret_values(response.text)


def test_fake_injected_internal_engine_returns_real_mode_no_send_response():
    class FakeEngine:
        async def run(self, context):
            return SimpleNamespace(
                action="reply",
                reply_text="真实 InternalEngine no-send 测试回复",
                intent="product_basic",
                reason="fake_engine",
                trace={
                    "selected_domain": "product_catalog",
                    "rag_status": "ok",
                    "rag_hit_count": 1,
                    "answer_generation_status": "ok",
                    "guardrail_status": "safe",
                    "retrieved_chunks": [{"content": "fake chunk", "score": 1.0}],
                    "prompt": f"message={context.content}",
                    "raw_response": "真实 InternalEngine no-send 测试回复",
                },
            )

    def factory(options: WebEngineOptions):
        assert options.use_real_engine is True
        return FakeEngine()

    adapter = WebInternalEngineAdapter(engine_factory=factory)
    service = LiveChatService(trace_service=TraceService(), engine_adapter=adapter)
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "这个多少钱",
            "metadata": {"goods_id": "943269377110", "goods_name": "脖子身体懒人素颜霜"},
            "use_real_engine": True,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    trace = payload["trace"]
    assert payload["reply"] == "真实 InternalEngine no-send 测试回复"
    assert payload["no_send"] is True
    assert trace["engine_mode"] == "real_internal"
    assert trace["engine_adapter_status"] == "ok"
    assert trace["real_engine_called"] is True
    assert trace["product_context_forwarded"] is True
    assert trace["sends_pdd"] is False
    assert trace["calls_llm"] is False
    assert trace["calls_ollama"] is False
    assert trace["connects_pgvector"] is False
    assert "api_key" not in trace
    assert "token" not in trace
    assert "cookie" not in trace
    assert "authorization" not in trace
    assert "fastgpt" not in response.text.lower()


def test_real_engine_context_injects_product_card_history_from_web_metadata():
    class FakeEngine:
        async def run(self, context):
            assert context.history
            product_card = context.history[0]
            assert product_card["message_type"] == "product_card"
            assert product_card["goods_id"] == "773044930700"
            assert product_card["goods_price"] == "19.7"
            assert "\u4ef7\u683c\uff1a19.7" in product_card["content"]
            assert "\u89c4\u683c\uff1a\u4e00\u74f6" in product_card["content"]
            return SimpleNamespace(
                action="reply",
                reply_text="\u4ef7\u683c\u4ee5\u9875\u9762\u4e3a\u51c6",
                intent="product_basic",
                reason="fake_engine",
                trace={
                    "selected_domain": "product_catalog",
                    "rag_status": "ok",
                    "rag_hit_count": 1,
                    "answer_generation_status": "ok",
                    "guardrail_status": "safe",
                    "history_message_count": len(context.history),
                    "history_has_product_card": True,
                    "prompt": product_card["content"],
                },
            )

    adapter = WebInternalEngineAdapter(engine_factory=lambda options: FakeEngine())
    service = LiveChatService(trace_service=TraceService(), engine_adapter=adapter)
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "565617"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "565617",
            "message": "\u8fd9\u4e2a\u591a\u5c11\u94b1",
            "metadata": {
                "goods_id": "773044930700",
                "goods_name": "YACN\u7261\u4e39\u82b1\u7d20\u989c\u971c",
                "goods_price": "19.7",
                "spec": "\u4e00\u74f6",
            },
            "use_real_engine": True,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["history_message_count"] == 1
    assert trace["history_has_product_card"] is True
    assert trace["web_product_card_history_injected"] is True
    assert "\u4ef7\u683c\uff1a19.7" in trace["prompt"]
    assert trace["sends_pdd"] is False


def test_real_engine_mode_can_lazy_load_without_provider_flags():
    service = LiveChatService(trace_service=TraceService())
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "hello",
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": False,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["engine_adapter_status"] == "ok"
    assert trace["engine_mode"] == "real_internal"
    assert trace["real_engine_called"] is True
    assert trace["calls_llm"] is False
    assert trace["calls_ollama"] is False
    assert trace["connects_pgvector"] is False
    assert trace["sends_pdd"] is False


def test_adapter_maps_alternate_rag_trace_fields_and_latency():
    class FakeEngine:
        async def run(self, context):
            del context
            return SimpleNamespace(
                action="reply",
                reply_text="亲亲，价格以页面为准",
                intent="product_basic",
                reason="fake_engine",
                trace={
                    "selected_domain": "product_catalog",
                    "rag_status": "ok",
                    "rag_hit_count": 2,
                    "knowledge_hits": [
                        {
                            "chunk_id": "chunk-1",
                            "content": "价格：9.90",
                            "score": 0.92,
                            "metadata": {"goods_id": "943269377110"},
                        }
                    ],
                    "stage_latency_ms": {
                        "total": 345,
                        "engine": 300,
                        "rag": 120,
                        "llm": 180,
                        "guardrail": 10,
                    },
                    "answer_generation_status": "ok",
                    "guardrail_status": "safe",
                },
            )

    adapter = WebInternalEngineAdapter(engine_factory=lambda options: FakeEngine())
    service = LiveChatService(trace_service=TraceService(), engine_adapter=adapter)
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "这个多少钱",
            "metadata": {"goods_id": "943269377110", "goods_name": "脖子身体懒人素颜霜"},
            "use_real_engine": True,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["retrieved_chunks"][0]["content"] == "价格：9.90"
    assert trace["retrieved_chunks_unavailable"] is False
    assert trace["latency_ms"]["total"] == 345
    assert trace["latency_ms"]["rag"] == 120
    assert trace["latency_ms"]["llm"] == 180


def test_adapter_supplies_elapsed_latency_when_engine_trace_omits_it():
    class FakeEngine:
        async def run(self, context):
            del context
            return SimpleNamespace(
                action="reply",
                reply_text="ok",
                intent="product_basic",
                reason="fake_engine",
                trace={
                    "selected_domain": "product_catalog",
                    "rag_status": "ok",
                    "rag_hit_count": 0,
                    "answer_generation_status": "ok",
                    "guardrail_status": "safe",
                },
            )

    adapter = WebInternalEngineAdapter(engine_factory=lambda options: FakeEngine())
    service = LiveChatService(trace_service=TraceService(), engine_adapter=adapter)
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "price",
            "use_real_engine": True,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    latency = response.json()["trace"]["latency_ms"]
    assert latency["total"] >= 1
    assert latency["engine"] >= 1


def test_adapter_fills_missing_engine_chunks_from_readonly_debug_loader(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_PGVECTOR_DSN", "postgresql://user:password@localhost:5432/db")
    monkeypatch.setenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_EMBEDDING_API_KEY", "configured")
    monkeypatch.setenv("DOUBAO_EMBEDDING_MODEL", "doubao-embedding-vision-test")

    class FakeEngine:
        async def run(self, context):
            del context
            return SimpleNamespace(
                action="reply",
                reply_text="ok",
                intent="product_basic",
                reason="fake_engine",
                trace={
                    "selected_domain": "product_catalog",
                    "rag_status": "ok",
                    "rag_hit_count": 3,
                    "answer_generation_status": "ok",
                    "guardrail_status": "safe",
                },
            )

    def chunk_loader(**kwargs):
        assert kwargs["goods_id"] == "943269377110"
        assert kwargs["shop_id"] == "323473738"
        return (
            [
                {
                    "chunk_id": "chunk-debug-1",
                    "domain": "product_catalog",
                    "source_type": "product",
                    "source_id": "943269377110",
                    "version": "real-product-v1",
                    "content": "price debug chunk",
                    "metadata": {"goods_id": "943269377110"},
                }
            ],
            None,
        )

    adapter = WebInternalEngineAdapter(engine_factory=lambda options: FakeEngine(), chunk_loader=chunk_loader)
    service = LiveChatService(trace_service=TraceService(), engine_adapter=adapter)
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "price",
            "metadata": {"goods_id": "943269377110", "goods_name": "test"},
            "use_real_engine": True,
            "use_real_pgvector": True,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["retrieved_chunks"][0]["content"] == "price debug chunk"
    assert trace["retrieved_chunks_unavailable"] is False


def test_real_rag_profile_uses_doubao_pgvector_without_ollama_env(monkeypatch):
    for key in (
        "AI_WORKFLOW_OLLAMA_BASE_URL",
        "AI_WORKFLOW_EMBEDDING_MODEL",
        "AI_WORKFLOW_LLM_BASE_URL",
        "AI_WORKFLOW_LLM_MODEL",
        "AI_WORKFLOW_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WEB_API_PGVECTOR_DSN", "postgresql://user:password@localhost:5432/db")
    monkeypatch.setenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_EMBEDDING_API_KEY", "configured")
    monkeypatch.setenv("DOUBAO_EMBEDDING_MODEL", "doubao-embedding-vision-test")

    captured: list[WebEngineOptions] = []

    class FakeEngine:
        async def run(self, context):
            del context
            return SimpleNamespace(
                action="reply",
                reply_text="ok",
                intent="product_basic",
                reason="fake_engine",
                trace={
                    "selected_domain": "product_catalog",
                    "rag_status": "hit",
                    "rag_hit_count": 1,
                    "retrieved_chunks": [
                        {
                            "chunk_id": "kc-product-1",
                            "domain": "product_catalog",
                            "source_type": "product",
                            "source_id": "943269377110",
                            "content": "价格：9.90",
                            "score": 0.88,
                        }
                    ],
                    "answer_generation_status": "ok",
                    "guardrail_status": "safe",
                },
            )

    def factory(options: WebEngineOptions):
        captured.append(options)
        return FakeEngine()

    adapter = WebInternalEngineAdapter(engine_factory=factory)
    service = LiveChatService(trace_service=TraceService(), engine_adapter=adapter)
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "这个多少钱",
            "metadata": {"goods_id": "943269377110", "goods_name": "test"},
            "smoke_profile": "real_rag",
            "no_send": True,
        },
    )

    assert response.status_code == 200
    assert captured and captured[0].use_real_pgvector is True
    trace = response.json()["trace"]
    assert trace["engine_adapter_status"] == "ok"
    assert trace["provider_status"]["pgvector"] == "enabled"
    assert trace["provider_status"]["embedding_provider"] == "doubao"
    assert trace["provider_status"]["embedding"] == "enabled"
    assert trace["provider_status"]["ollama"] == "disabled"
    assert trace["calls_ollama"] is False
    assert trace["connects_pgvector"] is True
    assert trace["retrieved_chunks"][0]["content"] == "价格：9.90"
    _assert_no_secret_values(response.text)


def test_real_full_profile_forces_real_provider_flags_even_if_payload_flags_are_stale(monkeypatch):
    for key in (
        "AI_WORKFLOW_PGVECTOR_DSN",
        "AI_WORKFLOW_OLLAMA_BASE_URL",
        "AI_WORKFLOW_EMBEDDING_MODEL",
        "AI_WORKFLOW_LLM_BASE_URL",
        "AI_WORKFLOW_LLM_MODEL",
        "AI_WORKFLOW_LLM_API_KEY",
    ):
        monkeypatch.setenv(key, "configured")

    captured: list[WebEngineOptions] = []

    class FakeEngine:
        async def run(self, context):
            del context
            return SimpleNamespace(
                action="reply",
                reply_text="ok",
                intent="product_basic",
                reason="fake_engine",
                trace={
                    "selected_domain": "product_catalog",
                    "rag_status": "ok",
                    "rag_hit_count": 0,
                    "answer_generator_called": True,
                    "answer_generation_status": "ok",
                    "guardrail_status": "safe",
                },
            )

    def factory(options: WebEngineOptions):
        captured.append(options)
        return FakeEngine()

    adapter = WebInternalEngineAdapter(engine_factory=factory)
    service = LiveChatService(trace_service=TraceService(), engine_adapter=adapter)
    client = _client(service)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "message": "price",
            "metadata": {"goods_id": "943269377110", "goods_name": "test"},
            "smoke_profile": "real_full",
            "use_real_engine": False,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": False,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": False,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    assert captured
    options = captured[0]
    assert options.use_real_engine is True
    assert options.use_real_pgvector is True
    assert options.use_real_ollama is True
    assert options.use_real_llm is True
    assert options.use_real_intent_classifier is True
    assert options.use_real_answer_generator is True
    trace = response.json()["trace"]
    assert trace["provider_status"]["answer_generator"] == "enabled"
    assert trace["use_real_answer_generator"] is True
    assert trace["answer_generation_status"] == "ok"
    assert trace["sends_pdd"] is False
