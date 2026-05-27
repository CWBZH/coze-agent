import json

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.prompt_builder import build_prompt_payload, format_conversation_text


def test_prompt_builder_adds_domain_constraints_and_stable_hash():
    first = build_prompt_payload(
        intent="after_sales_evidence_collection",
        query_summary="buyer reports damage",
        history_window=[{"content_summary": "previous summary", "content_hash": "h1"}],
        product_hits=[],
        sop_records=[{"id": "sop-1", "domain": "after_sales_evidence", "version": "sop-v1"}],
        constraints=[],
        forbidden_phrases=[],
    )
    second = build_prompt_payload(
        intent="after_sales_evidence_collection",
        query_summary="buyer reports damage",
        history_window=[{"content_summary": "previous summary", "content_hash": "h1"}],
        product_hits=[],
        sop_records=[{"id": "sop-1", "domain": "after_sales_evidence", "version": "sop-v1"}],
        constraints=[],
        forbidden_phrases=[],
    )

    rendered = repr(first)
    assert "不要承诺退款、补发、赔偿或换货结果" in rendered
    assert "前文摘要:" in first.conversation_text
    assert "当前消息: 内容：buyer reports damage" in first.conversation_text
    assert first.prompt_hash == second.prompt_hash
    assert first.redaction_summary["history_count"] == 1


def test_prompt_builder_covers_safety_constraints_by_intent():
    cases = {
        "logistics_order_status": "不要编造具体物流状态",
        "promotion_policy": "不要承诺私下优惠、赠品、返差价",
        "human_escalation_redline": "不要判断真假、责任、赔偿",
        "sensitive_user_safety": "不要做医疗、功效或绝对安全承诺",
        "product_basic": "价格必须以商品页面或结算页为准",
    }

    for intent, expected in cases.items():
        payload = build_prompt_payload(intent=intent, query_summary="summary")
        assert expected in repr(payload)


def test_prompt_payload_has_no_forbidden_raw_fields():
    payload = build_prompt_payload(intent="product_basic", query_summary="summary")
    field_names = set(payload.__dict__)

    assert "raw_db_row" not in field_names
    assert "api_key" not in field_names
    assert "token" not in field_names
    assert "raw_prompt" not in field_names


def test_prompt_payload_exposes_safe_counts_for_artifacts():
    private_chunk = "PRIVATE_CHUNK_SHOULD_NOT_APPEAR_IN_ARTIFACT"
    payload = build_prompt_payload(
        intent="logistics_policy",
        query_summary="summary only",
        history_window=[{"content_summary": "history summary", "content_hash": "h1"}],
        product_hits=[
            {
                "domain": "logistics_policy",
                "title": "private title",
                "content_summary": private_chunk,
            }
        ],
        sop_records=[],
        constraints=["Custom constraint"],
        forbidden_phrases=["refund"],
    )

    assert payload.context_block_count == 4
    assert payload.used_history_count == 1
    assert payload.used_rag_hit_count == 1
    assert payload.constraint_count >= 1
    artifact_summary = {
        "prompt_hash": payload.prompt_hash,
        "context_block_count": payload.context_block_count,
        "constraint_count": payload.constraint_count,
        "used_history_count": payload.used_history_count,
        "used_rag_hit_count": payload.used_rag_hit_count,
        "redaction_summary": payload.redaction_summary,
    }
    rendered = json.dumps(artifact_summary, ensure_ascii=False, sort_keys=True)
    assert private_chunk not in rendered


def test_format_conversation_text_renders_fastgpt_style_product_card():
    text = format_conversation_text(
        history=[
            {
                "role": "buyer",
                "message_type": "product_card",
                "goods_name": "测试商品",
                "goods_price": "3.64",
                "goods_id": "943",
            },
            {"role": "assistant", "content": "亲，这款可以看页面说明哦"},
        ],
        current_message="是新品吗",
    )

    assert "前文摘要:" in text
    assert "买家: 商品：测试商品，价格：3.64，商品ID：943" in text
    assert "客服: 亲，这款可以看页面说明哦" in text
    assert "当前消息: 内容：是新品吗" in text


def test_format_conversation_text_keeps_recent_20_messages_without_compression():
    history = [{"role": "buyer", "content": f"第{i}轮消息"} for i in range(20)]

    text = format_conversation_text(history=history, current_message="当前问题")

    assert "较早对话摘要" not in text
    assert "第0轮消息" in text
    assert "第19轮消息" in text
    assert "当前消息: 内容：当前问题" in text


def test_format_conversation_text_compresses_first_10_when_history_exceeds_20():
    history = [{"role": "buyer", "content": f"第{i}轮消息"} for i in range(25)]
    history[2] = {
        "role": "buyer",
        "message_type": "product_card",
        "goods_name": "测试商品",
        "goods_price": "3.64",
        "goods_id": "943",
    }

    text = format_conversation_text(history=history, current_message="这个多少钱")

    assert "较早对话摘要" in text
    assert "共10条" in text
    assert "商品：测试商品" in text
    assert "商品ID：943" in text
    assert "\n买家: 内容：第0轮消息" not in text
    assert "\n买家: 内容：第9轮消息" not in text
    assert "第10轮消息" in text
    assert "第24轮消息" in text
    assert "当前消息: 内容：这个多少钱" in text
def test_product_prompt_allows_price_specs_and_usage_with_boundaries():
    payload = build_prompt_payload(
        intent="product_basic",
        query_summary="\u8fd9\u4e2a\u591a\u5c11\u94b1",
        history_window=[
            {
                "role": "buyer",
                "message_type": "product_card",
                "goods_name": "YACN\u7261\u4e39\u82b1\u7d20\u989c\u971c",
                "goods_price": "19.7",
                "goods_id": "773044930700",
                "spec": "\u4e00\u74f6",
            }
        ],
        product_hits=[
            {
                "domain": "product_catalog",
                "content": (
                    "price [raw]: 19.70-29.60\n"
                    "specs [raw]: ['\u6b3e\u5f0f: \u4e00\u74f6', '\u6b3e\u5f0f: \u4e24\u74f6']\n"
                    "usage [manual_override]: \u8bf7\u6309\u5546\u54c1\u9875\u9762\u8bf4\u660e\u4f7f\u7528"
                ),
            }
        ],
    )

    instructions = "\n".join(payload.system_instructions)
    assert "\u5f53\u524d\u5546\u54c1\u4fe1\u606f\u663e\u793a\u4ef7\u683c\u4e3a" in instructions
    assert "\u4ee5\u5546\u54c1\u9875\u9762\u548c\u4e0b\u5355\u7ed3\u7b97\u9875\u4e3a\u51c6" in instructions
    assert "\u5f53\u524d\u5546\u54c1\u4fe1\u606f\u663e\u793a\u89c4\u683c\u4e3a" in instructions
    assert "usage/manual_override" in instructions
    assert "\u5fc5\u987b\u5148\u590d\u8ff0\u8be5\u7528\u6cd5" in instructions
    assert "\u79c1\u4e0b\u4f18\u60e0" in instructions
    assert "\u8d60\u54c1" in instructions
    assert "\u8fd4\u5dee\u4ef7" in instructions
    assert "\u4ef7\u683c\uff1a19.7" in payload.conversation_text
    assert "\u89c4\u683c\uff1a\u4e00\u74f6" in payload.conversation_text
