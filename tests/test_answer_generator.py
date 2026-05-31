import dataclasses
import json

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.answer_generator import (
    AnswerGenerationContext,
    FakeAnswerGenerator,
    NullAnswerGenerator,
    OpenAICompatibleAnswerGenerator,
    answer_preview,
    classify_answer_error,
)


def test_fake_answer_generator_returns_metadata_only_draft():
    generator = FakeAnswerGenerator()
    context = AnswerGenerationContext(
        intent="product_basic",
        action_hint="reply",
        query_summary="summary only",
        history_window=[{"content_summary": "previous summary", "content_hash": "abc"}],
        product_hits=[{"source": "product", "title_hash": "t1"}],
        sop_records=[],
        constraints=["keep it short"],
        forbidden_phrases=["refund"],
        workflow_version="internal-v1",
        sop_version="",
        knowledge_version="product_repository",
        trace_id="trace-1",
        prompt_hash="prompt-hash",
    )

    draft = generator.generate(context)

    assert draft.text
    assert draft.source == "fake"
    assert draft.used_history_count == 1
    assert draft.confidence > 0
    assert draft.used_knowledge_refs == [{"source": "product", "title_hash": "t1"}]
    assert not hasattr(draft, "raw_prompt")
    assert not hasattr(draft, "raw_response")


def test_null_answer_generator_returns_empty_fallback_draft():
    draft = NullAnswerGenerator().generate(AnswerGenerationContext(intent="fallback"))

    assert draft.text == ""
    assert draft.source == "null"
    assert draft.confidence == 0
    assert draft.raw_error_type == "answer_generator_disabled"


def test_answer_draft_has_no_forbidden_raw_fields():
    draft = FakeAnswerGenerator().generate(AnswerGenerationContext(intent="logistics_order_status"))
    field_names = {field.name for field in dataclasses.fields(draft)}

    assert "raw_prompt" not in field_names
    assert "raw_response" not in field_names
    assert "provider_response" not in field_names


def test_openai_compatible_answer_generator_fake_transport_success(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_TEST_LLM_KEY", "private-api-key")
    captured = {}

    def fake_transport(*, url, headers, body, timeout_seconds):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["timeout"] = timeout_seconds
        return {"choices": [{"message": {"content": "Please check the order logistics page."}}]}

    generator = OpenAICompatibleAnswerGenerator(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key_env="AI_WORKFLOW_TEST_LLM_KEY",
        transport=fake_transport,
    )
    draft = generator.generate(
        AnswerGenerationContext(
            intent="logistics_policy",
            query_summary="summary only",
            history_window=[{"content_summary": "history summary", "content_hash": "h1"}],
            product_hits=[{"domain": "logistics_policy", "title_hash": "t1"}],
            constraints=["Do not invent shipping status."],
            prompt_hash="prompt-hash",
        )
    )
    rendered_draft = json.dumps(dataclasses.asdict(draft), ensure_ascii=False)
    rendered_request = json.dumps(captured, ensure_ascii=False)

    assert draft.text == "Please check the order logistics page."
    assert draft.source == "openai_compatible"
    assert draft.confidence > 0
    assert draft.used_history_count == 1
    assert captured["url"].endswith("/chat/completions")
    assert "private-api-key" not in rendered_draft
    assert "raw_prompt" not in rendered_draft
    assert "raw_response" not in rendered_draft
    assert "private-api-key" not in rendered_request


def test_openai_compatible_answer_generator_does_not_force_price_retry(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_TEST_LLM_KEY", "private-api-key")
    calls = []

    def fake_transport(*, url, headers, body, timeout_seconds):
        del url, headers, timeout_seconds
        calls.append(body)
        return {"choices": [{"message": {"content": "亲亲，价格以商品页面或结算页为准哦~"}}]}

    generator = OpenAICompatibleAnswerGenerator(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key_env="AI_WORKFLOW_TEST_LLM_KEY",
        transport=fake_transport,
    )

    draft = generator.generate(
        AnswerGenerationContext(
            intent="product_basic",
            query_summary="这个多少钱",
            product_hits=[
                {
                    "domain": "product_catalog",
                    "content": "商品：脖子身体懒人素颜霜。Price reference: 3.64-11.50，最终以商品页面为准。",
                }
            ],
        )
    )

    assert draft.text == "亲亲，价格以商品页面或结算页为准哦~"
    assert len(calls) == 1


def test_openai_compatible_answer_generator_does_not_retry_non_price_question(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_TEST_LLM_KEY", "private-api-key")
    calls = []

    def fake_transport(*, url, headers, body, timeout_seconds):
        del url, headers, timeout_seconds
        calls.append(body)
        return {"choices": [{"message": {"content": "亲亲，使用方法请查看商品详情页说明哦~"}}]}

    generator = OpenAICompatibleAnswerGenerator(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key_env="AI_WORKFLOW_TEST_LLM_KEY",
        transport=fake_transport,
    )

    draft = generator.generate(
        AnswerGenerationContext(
            intent="product_basic",
            query_summary="这个怎么用",
            product_hits=[{"domain": "product_catalog", "content": "Price reference: 3.64-11.50"}],
        )
    )

    assert draft.text == "亲亲，使用方法请查看商品详情页说明哦~"
    assert len(calls) == 1


def test_openai_compatible_answer_generator_keeps_late_product_fields_in_prompt(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_TEST_LLM_KEY", "private-api-key")
    captured = {}

    def fake_transport(*, url, headers, body, timeout_seconds):
        del url, headers, timeout_seconds
        captured["body"] = body
        return {"choices": [{"message": {"content": "亲亲，保质期是3年，开封后建议12个月内用完哦"}}]}

    long_prefix = "ingredients [manual_override]: " + ("牡丹花提取物、烟酰胺、维生素C、胶原蛋白、甘油。" * 30)
    product_content = "\n".join(
        [
            "Product: YACN牡丹花素颜霜身体素颜伪体香纯欲斩男香持久留香保湿焕亮秋冬",
            "Goods ID: 773044930700",
            "Domain: product_catalog",
            "goods_name [manual_override]: YACN牡丹花素颜霜身体素颜伪体香纯欲斩男香持久留香保湿焕亮秋冬",
            long_prefix,
            "shelf_life [manual_override]: 3年（开封后建议在12个月内用完）",
            "usage [manual_override]: 取适量涂抹后按摩吸收。",
        ]
    )
    generator = OpenAICompatibleAnswerGenerator(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key_env="AI_WORKFLOW_TEST_LLM_KEY",
        transport=fake_transport,
    )

    draft = generator.generate(
        AnswerGenerationContext(
            intent="product_basic",
            query_summary="保质期多久",
            product_hits=[
                {
                    "domain": "product_catalog",
                    "source_type": "product",
                    "content": product_content,
                }
            ],
        )
    )
    prompt = captured["body"]["messages"][1]["content"]

    assert draft.text == "亲亲，保质期是3年，开封后建议12个月内用完哦"
    assert "保质期 [manual_override]: 3年（开封后建议在12个月内用完）" in prompt
    assert "用法 [manual_override]: 取适量涂抹后按摩吸收。" in prompt


def test_openai_compatible_answer_generator_missing_key_is_sanitized(monkeypatch):
    monkeypatch.delenv("AI_WORKFLOW_TEST_LLM_KEY", raising=False)
    generator = OpenAICompatibleAnswerGenerator(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key_env="AI_WORKFLOW_TEST_LLM_KEY",
        transport=lambda **kwargs: {"choices": []},
    )

    draft = generator.generate(AnswerGenerationContext(query_summary="PRIVATE_PROMPT_SHOULD_NOT_LEAK"))

    assert draft.text == ""
    assert draft.source == "openai_compatible"
    assert draft.confidence == 0
    assert draft.raw_error_type == "missing_api_key"
    assert "PRIVATE_PROMPT_SHOULD_NOT_LEAK" not in draft.raw_error_summary


def test_openai_compatible_answer_generator_error_does_not_leak_prompt_or_key(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_TEST_LLM_KEY", "private-api-key")

    def failing_transport(**kwargs):
        raise RuntimeError("network failed with PRIVATE_PROMPT and private-api-key")

    generator = OpenAICompatibleAnswerGenerator(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key_env="AI_WORKFLOW_TEST_LLM_KEY",
        transport=failing_transport,
    )

    draft = generator.generate(AnswerGenerationContext(query_summary="PRIVATE_PROMPT"))

    assert draft.text == ""
    assert draft.raw_error_type == "RuntimeError"
    assert "PRIVATE_PROMPT" not in draft.raw_error_summary
    assert "private-api-key" not in draft.raw_error_summary


def test_openai_compatible_answer_generator_classifies_provider_failures(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_TEST_LLM_KEY", "private-api-key")

    def failing_transport(**kwargs):
        raise ConnectionResetError("remote disconnected")

    generator = OpenAICompatibleAnswerGenerator(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key_env="AI_WORKFLOW_TEST_LLM_KEY",
        transport=failing_transport,
    )

    draft = generator.generate(AnswerGenerationContext(query_summary="PRIVATE_PROMPT"))

    assert draft.text == ""
    assert draft.raw_error_type == "ConnectionResetError"
    assert classify_answer_error(draft.raw_error_type, draft.raw_error_summary) == "answer_generator_provider_disconnected"
    assert draft.provider_host == "llm.example.test"
    assert draft.timeout_ms > 0
    assert "PRIVATE_PROMPT" not in draft.raw_error_summary


def test_classify_answer_error_categories_are_stable():
    assert classify_answer_error("missing_api_key", "") == "answer_generator_config_missing"
    assert classify_answer_error("empty_answer", "") == "answer_generator_empty_answer"
    assert classify_answer_error("TimeoutError", "provider request timed out") == "answer_generator_timeout"
    assert classify_answer_error("HTTPError", "provider http error status=429") == "answer_generator_http_error"
    assert classify_answer_error("JSONDecodeError", "bad json") == "answer_generator_parser_error"
    assert classify_answer_error("RuntimeError", "provider request failed") == "answer_generator_exception"


def test_answer_preview_is_truncated_and_sanitized():
    preview = answer_preview("token=secret " + "x" * 300, max_chars=40)

    assert len(preview) <= 40
    assert "secret" not in preview
