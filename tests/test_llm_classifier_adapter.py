import asyncio
import logging

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.intent_classifier import (
    AFTER_SALES_EVIDENCE_COLLECTION,
    ASK_PRODUCT_CLARIFICATION,
    EXPLICIT_HUMAN_REQUEST,
    FALLBACK,
    HUMAN_ESCALATION_REDLINE,
    LOGISTICS_ORDER_STATUS,
    PRODUCT_BASIC,
    PROMOTION_POLICY,
    SENSITIVE_USER_SAFETY,
)
from Message.workflow.llm_classifier import (
    OpenAICompatibleIntentClassifier,
    OpenAICompatibleIntentClassifierConfig,
)
from Message.workflow.types import WorkflowContext


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.payloads = []

    async def complete(self, payload):
        self.payloads.append(payload)
        return self.response


def _classifier(response):
    transport = FakeTransport(response)
    classifier = OpenAICompatibleIntentClassifier(
        transport=transport,
        config=OpenAICompatibleIntentClassifierConfig(enabled=True),
    )
    return classifier, transport


def _run(classifier, content="这个商品是什么规格", *, history=None, goods_context=None):
    return asyncio.run(
        classifier.classify_context(
            WorkflowContext(
                trace_id="trace-1",
                shop_id="shop-1",
                user_id="buyer-1",
                session_id="session-1",
                content=content,
                history=list(history or []),
                goods_context=goods_context,
            )
        )
    )


def test_chinese_label_classifies_product_basic_and_prompt_is_chinese():
    classifier, transport = _classifier("商品基础咨询")

    result = _run(classifier)

    assert result.intent == PRODUCT_BASIC
    assert result.domain == "product_catalog"
    assert result.requires_rag is True
    assert result.requires_product_context is True
    assert result.requires_answer_generation is True
    system_prompt = transport.payloads[0]["messages"][0]["content"]
    assert "拼多多店铺客服问题分类器" in system_prompt
    assert "只返回分类名称" in system_prompt
    assert "不要输出JSON" in system_prompt
    assert "商品基础咨询" in system_prompt


def test_openai_compatible_response_shape_returns_chinese_label():
    classifier, _ = _classifier({"choices": [{"message": {"content": "物流订单查询"}}]})

    result = _run(classifier, "什么时候发货")

    assert result.intent == LOGISTICS_ORDER_STATUS
    assert result.domain == "logistics_policy"
    assert result.requires_order_context is True


def test_reasoning_model_extra_text_can_still_extract_known_label():
    classifier, _ = _classifier("我判断如下：\n```text\n优惠活动咨询\n```\n仅供分类。")

    result = _run(classifier, "能不能便宜点")

    assert result.intent == PROMOTION_POLICY
    assert result.domain == "promotion_policy"
    assert result.requires_rag is True


def test_all_chinese_labels_map_to_internal_intents():
    cases = {
        "商品基础咨询": PRODUCT_BASIC,
        "物流订单查询": LOGISTICS_ORDER_STATUS,
        "售后取证处理": AFTER_SALES_EVIDENCE_COLLECTION,
        "优惠活动咨询": PROMOTION_POLICY,
        "敏感人群安全": SENSITIVE_USER_SAFETY,
        "红线转人工": HUMAN_ESCALATION_REDLINE,
        "明确要求人工": EXPLICIT_HUMAN_REQUEST,
        "商品信息缺失澄清": ASK_PRODUCT_CLARIFICATION,
        "其他问题": FALLBACK,
    }

    for label, intent in cases.items():
        classifier, _ = _classifier(label)
        result = _run(classifier)
        assert result.intent == intent
        if intent != HUMAN_ESCALATION_REDLINE:
            assert result.reason == f"llm_chinese_label:{intent}"
        assert result.metadata
        assert result.metadata.get("classifier_label_intent") == intent


def test_unrecognized_label_falls_back_without_raw_response():
    raw_response = "这是一个很长的解释，不是合法分类"
    classifier, _ = _classifier(raw_response)

    result = _run(classifier, "这个多少钱")

    assert result.intent == FALLBACK
    assert result.reason == "llm_classifier_unrecognized_label"
    assert result.metadata
    assert raw_response not in repr(result.metadata)


def test_default_classifier_does_not_call_transport_or_real_llm():
    classifier = OpenAICompatibleIntentClassifier()

    result = _run(classifier)

    assert result.intent == FALLBACK
    assert result.reason == "llm_classifier_disabled"


def test_payload_uses_fastgpt_style_conversation_text_with_history_product_anchor():
    classifier, transport = _classifier("商品基础咨询")
    history = [
        {
            "role": "buyer",
            "message_type": "product_card",
            "goods_id": "goods-1",
            "goods_name": "测试商品",
            "goods_price": "9.9",
        },
        {"role": "assistant", "content": "亲，这款可以看页面说明哦"},
    ]

    result = _run(classifier, "这个多少钱", history=history)

    assert result.intent == PRODUCT_BASIC
    payload_text = transport.payloads[0]["messages"][1]["content"]
    assert "前文摘要:" in payload_text
    assert "买家: 商品：测试商品，价格：9.9，商品ID：goods-1" in payload_text
    assert "客服: 亲，这款可以看页面说明哦" in payload_text
    assert "当前消息: 内容：这个多少钱" in payload_text


def test_payload_includes_current_goods_context_as_product_line():
    classifier, transport = _classifier("商品基础咨询")

    result = _run(
        classifier,
        "这个怎么用",
        history=[{"role": "buyer", "message_type": "text", "content": "上一轮完整问题"}],
        goods_context={"goods_id": "goods-1", "goods_name": "测试商品"},
    )

    assert result.intent == PRODUCT_BASIC
    payload_text = transport.payloads[0]["messages"][1]["content"]
    assert "买家: 商品：测试商品，商品ID：goods-1" in payload_text
    assert "上一轮完整问题" in payload_text


def test_does_not_log_raw_prompt_or_response(caplog):
    raw_response = "商品基础咨询"
    classifier, _ = _classifier(raw_response)
    buyer_text = "buyer private text should not be logged"

    with caplog.at_level(logging.DEBUG):
        result = _run(classifier, buyer_text)

    assert result.intent == PRODUCT_BASIC
    assert buyer_text not in caplog.text
    assert raw_response not in caplog.text


def test_enabled_classifier_without_transport_uses_http_post_path():
    class HttpPathClassifier(OpenAICompatibleIntentClassifier):
        def __init__(self):
            super().__init__(
                config=OpenAICompatibleIntentClassifierConfig(
                    enabled=True,
                    base_url="http://localhost:11435/v1",
                    model="test-intent-model",
                )
            )
            self.payloads = []

        def _post_json(self, payload):
            self.payloads.append(payload)
            return {"choices": [{"message": {"content": "物流订单查询"}}]}

    classifier = HttpPathClassifier()

    result = _run(classifier, "when will it ship")

    assert result.intent == LOGISTICS_ORDER_STATUS
    assert classifier.payloads
