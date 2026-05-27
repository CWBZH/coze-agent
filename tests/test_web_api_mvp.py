from fastapi.testclient import TestClient

from web_api.main import app


client = TestClient(app)


def _assert_no_secret_values(payload_text: str) -> None:
    lowered = payload_text.lower()
    forbidden_values = ["bearer ", "ark-", "postgresql://", "pdd_session=", "authorization:"]
    assert all(value not in lowered for value in forbidden_values)


def test_health_returns_internal_engine_status():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "internal-engine-web-api",
        "version": "mvp",
        "engine": "internal",
    }


def test_shops_list_is_internal_only_and_safe():
    response = client.get("/api/shops")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    assert all(item["no_send"] is True for item in payload["items"])
    assert all("ai_backend" not in item for item in payload["items"])
    assert "fastgpt" not in response.text.lower()
    _assert_no_secret_values(response.text)


def test_ai_settings_force_no_send_and_has_no_backend_selector():
    get_response = client.get("/api/shops/323473738/ai-settings")
    assert get_response.status_code == 200
    settings = get_response.json()
    assert settings["no_send_mode"] is True
    assert settings["send_enabled"] is False
    assert "ai_backend" not in settings
    assert "fastgpt" not in get_response.text.lower()

    put_response = client.put(
        "/api/shops/323473738/ai-settings",
        json={"send_enabled": True, "rag_enabled": True, "llm_enabled": True},
    )

    assert put_response.status_code == 200
    updated = put_response.json()
    assert updated["send_enabled"] is False
    assert updated["no_send_mode"] is True
    assert updated["warning"] == "real PDD sending is disabled in MVP"


def test_products_list_and_detail_return_full_business_fields():
    list_response = client.get("/api/products")
    assert list_response.status_code == 200
    product = list_response.json()["items"][0]
    assert product["goods_id"]
    assert product["goods_name"]
    assert product["product_title"]
    assert "masked_goods_id" not in product

    detail_response = client.get(f"/api/products/{product['goods_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["goods_id"] == product["goods_id"]
    assert "raw_detail_json" in detail
    assert "chunks" in detail
    _assert_no_secret_values(detail_response.text)


def test_sop_detail_returns_full_content():
    list_response = client.get("/api/sop")
    assert list_response.status_code == 200
    record_id = list_response.json()["items"][0]["id"]

    detail_response = client.get(f"/api/sop/{record_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["content"]
    assert len(detail["content"]) > len(detail["title"])


def test_live_chat_is_no_send_and_returns_full_debug_trace():
    session_response = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"})
    assert session_response.status_code == 200
    session = session_response.json()
    assert session["no_send"] is True
    assert session["engine"] == "internal"

    message_response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={
            "shop_id": "323473738",
            "buyer_id": "buyer-demo",
            "message": "这个多少钱",
            "metadata": {"goods_id": "943269377110", "goods_name": "脖子身体懒人素颜霜"},
            "use_rag": True,
            "use_llm_intent_classifier": True,
            "use_llm_answer_generator": True,
            "no_send": True,
        },
    )

    assert message_response.status_code == 200
    payload = message_response.json()
    assert payload["reply"]
    assert payload["trace"]["engine"] == "internal"
    assert payload["trace"]["buyer_message"] == "这个多少钱"
    assert payload["trace"]["ai_reply"] == payload["reply"]
    assert payload["trace"]["prompt"]
    assert payload["trace"]["raw_response"]
    assert payload["trace"]["retrieved_chunks"][0]["content"]
    assert payload["trace"]["sends_pdd"] is False
    assert payload["trace"]["no_send"] is True
    assert "calls_fastgpt" not in payload["trace"]
    assert "fastgpt" not in message_response.text.lower()
    _assert_no_secret_values(message_response.text)


def test_trace_detail_returns_full_debug_content_without_secret_values():
    list_response = client.get("/api/traces")
    assert list_response.status_code == 200
    trace_id = list_response.json()["items"][0]["trace_id"]

    detail_response = client.get(f"/api/traces/{trace_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["buyer_message"]
    assert detail["ai_reply"]
    assert detail["prompt"]
    assert detail["raw_response"]
    assert detail["retrieved_chunks"][0]["content"]
    assert detail["sends_pdd"] is False
    assert "fastgpt" not in detail_response.text.lower()
    _assert_no_secret_values(detail_response.text)


def test_rag_job_is_dry_run_by_default():
    response = client.post(
        "/api/rag/jobs",
        json={"shop_id": "323473738", "source_type": "product", "domain": "product_catalog"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
