from fastapi.testclient import TestClient

from web_api.deps import get_live_chat_service
from web_api.main import app
from web_api.services.live_chat_service import LiveChatService
from web_api.services.trace_service import TraceService


def _client() -> TestClient:
    service = LiveChatService(trace_service=TraceService())
    app.dependency_overrides[get_live_chat_service] = lambda: service
    return TestClient(app)


def _assert_no_secret_values(text: str) -> None:
    lowered = text.lower()
    forbidden = ["bearer ", "ark-", "postgresql://", "authorization:", "pdd_session="]
    assert all(value not in lowered for value in forbidden)


def test_create_session_returns_internal_no_send_session():
    client = _client()

    response = client.post("/api/live-chat/sessions", json={"shop_id": "323473738", "buyer_id": "buyer-a"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["engine"] == "internal"
    assert payload["no_send"] is True


def test_product_question_without_context_asks_for_product_clarification():
    client = _client()
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "buyer_id": "buyer-a",
            "message": "这个多少钱",
            "metadata": {},
            "no_send": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "ask_product_clarification"
    assert payload["action"] == "reply"
    assert payload["no_send"] is True
    assert "哪款商品" in payload["reply"]
    assert payload["trace"]["product_context_status"] == "missing_required"
    assert payload["trace"]["product_anchor_source"] == "none"
    assert payload["trace"]["rag_status"] == "skipped"
    assert payload["trace"]["answer_generation_status"] == "skipped"
    assert payload["trace"]["sends_pdd"] is False
    assert payload["trace"]["calls_llm"] is False
    assert payload["trace"]["calls_ollama"] is False
    assert payload["trace"]["connects_pgvector"] is False
    assert "fastgpt" not in response.text.lower()
    _assert_no_secret_values(response.text)


def test_session_keeps_product_context_for_followup_product_question():
    client = _client()
    session = client.post(
        "/api/live-chat/sessions",
        json={"shop_id": "323473738", "buyer_id": "buyer-a"},
    ).json()

    first = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "buyer_id": "buyer-a",
            "message": "这款商品",
            "metadata": {
                "goods_id": "943269377110",
                "goods_name": "脖子身体懒人素颜霜",
            },
            "no_send": True,
        },
    )
    assert first.status_code == 200
    assert first.json()["trace"]["product_context_status"] == "resolved"

    second = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "buyer_id": "buyer-a",
            "message": "这个多少钱",
            "metadata": {},
            "no_send": True,
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["intent"] == "product_basic"
    assert payload["domain"] == "product_catalog"
    assert payload["trace"]["product_context_status"] == "resolved"
    assert payload["trace"]["product_anchor_source"] == "session"
    assert payload["trace"]["history_message_count"] >= 2
    assert payload["trace"]["rag_hit_count"] >= 1
    assert payload["trace"]["no_send"] is True
    assert payload["trace"]["sends_pdd"] is False
    assert payload["trace"]["calls_llm"] is False
    assert payload["trace"]["calls_ollama"] is False
    assert payload["trace"]["connects_pgvector"] is False
    assert "api_key" not in payload["trace"]
    assert "token" not in payload["trace"]
    assert "cookie" not in payload["trace"]
    assert "authorization" not in payload["trace"]
    assert "fastgpt" not in second.text.lower()


def test_real_service_flags_default_to_disabled_even_when_rag_enabled():
    client = _client()
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "buyer_id": "buyer-a",
            "message": "什么时候发货",
            "metadata": {},
            "use_rag": True,
            "use_llm_intent_classifier": True,
            "use_llm_answer_generator": True,
            "use_real_llm": False,
            "use_real_ollama": False,
            "use_real_pgvector": False,
            "no_send": True,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["calls_llm"] is False
    assert trace["calls_ollama"] is False
    assert trace["connects_pgvector"] is False
    assert trace["sends_pdd"] is False
    assert trace["no_send"] is True
    assert "fastgpt" not in response.text.lower()
    _assert_no_secret_values(response.text)
