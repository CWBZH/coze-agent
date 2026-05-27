import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.domain_policy import (
    AFTER_SALES_EVIDENCE_COLLECTION,
    LOGISTICS_ORDER_STATUS,
    PROMOTION_POLICY,
    REDLINE_ESCALATION,
    SENSITIVE_USER_SAFETY,
    DomainPolicyResponder,
    PolicyReplyResult,
)
from Message.workflow.guardrail import OutputGuardrail
from Message.workflow.types import WorkflowAction, WorkflowResult


def _records(domain: str):
    return [
        {
            "id": f"sop-{domain}",
            "source": "fake_sop",
            "domain": domain,
            "content": "raw sop content should not be copied into trace",
        }
    ]


def _reply(domain: str):
    return DomainPolicyResponder().respond(
        intent=domain,
        domain=domain,
        sop_records=_records(domain),
        query_summary="buyer query summary only",
    )


def test_logistics_order_status_uses_order_page_boundary_without_concrete_shipping_claims():
    result = _reply(LOGISTICS_ORDER_STATUS)

    assert isinstance(result, PolicyReplyResult)
    assert result.action == WorkflowAction.REPLY
    assert result.intent == LOGISTICS_ORDER_STATUS
    assert "订单物流页" in result.reply_text
    assert "转人工" in result.reply_text
    assert "已经发出" not in result.reply_text
    assert "明天一定到" not in result.reply_text
    assert "正在运输" not in result.reply_text


def test_after_sales_evidence_collection_requests_evidence_without_refund_or_reship_promises():
    result = _reply(AFTER_SALES_EVIDENCE_COLLECTION)

    assert result.action == WorkflowAction.REQUEST_EVIDENCE
    assert "照片" in result.reply_text
    assert "包裹" in result.reply_text
    assert "实物" in result.reply_text
    assert "订单信息" in result.reply_text
    assert "给您退款" not in result.reply_text
    assert "马上补发" not in result.reply_text
    assert "赔偿" not in result.reply_text
    assert "换货" not in result.reply_text


def test_promotion_policy_uses_page_and_checkout_boundary_without_private_discount_promises():
    result = _reply(PROMOTION_POLICY)

    assert result.action == WorkflowAction.REPLY
    assert "商品页面" in result.reply_text
    assert "活动页面" in result.reply_text
    assert "结算页" in result.reply_text
    assert "私下优惠" in result.reply_text
    assert "承诺私下优惠" in result.reply_text
    assert "额外赠品" in result.reply_text
    assert "返差价" in result.reply_text
    assert "给您优惠" not in result.reply_text
    assert "私下给" not in result.reply_text


def test_redline_escalation_transfers_to_human_without_authenticity_or_compensation_judgement():
    result = _reply(REDLINE_ESCALATION)

    assert result.action == WorkflowAction.TRANSFER_HUMAN
    assert "人工客服" in result.reply_text
    assert "核实" in result.reply_text
    assert "保证正品" not in result.reply_text
    assert "一定赔偿" not in result.reply_text


def test_sensitive_user_safety_is_conservative_without_safety_or_medical_certainty():
    result = _reply(SENSITIVE_USER_SAFETY)

    assert result.action == WorkflowAction.REPLY
    assert "产品说明" in result.reply_text
    assert "咨询专业人士" in result.reply_text
    assert "转人工客服" in result.reply_text
    assert "孕妇一定安全" not in result.reply_text
    assert "治疗" not in result.reply_text


def test_workflow_result_output_is_supported():
    result = DomainPolicyResponder().respond_workflow(
        intent=LOGISTICS_ORDER_STATUS,
        sop_records=_records(LOGISTICS_ORDER_STATUS),
    )

    assert isinstance(result, WorkflowResult)
    assert result.action == WorkflowAction.REPLY
    assert result.intent == LOGISTICS_ORDER_STATUS
    assert "订单物流页" in result.reply_text


def test_missing_sop_records_falls_back_without_raw_query_or_sop_trace():
    result = DomainPolicyResponder().respond(
        intent=PROMOTION_POLICY,
        sop_records=[],
        query_summary="buyer asked for a discount",
    )

    assert result.action == WorkflowAction.FALLBACK
    assert result.reason == "domain_policy_missing_sop"
    assert "domain_policy_missing_sop" in result.risk_flags
    trace = result.trace["domain_policy_responder"]
    assert trace["sop_record_count"] == 0
    assert trace["query_summary_length"] == len("buyer asked for a discount")
    assert "buyer asked for a discount" not in str(result.trace)


def test_missing_redline_sop_records_transfers_to_human():
    result = DomainPolicyResponder().respond(intent=REDLINE_ESCALATION, sop_records=[])

    assert result.action == WorkflowAction.TRANSFER_HUMAN
    assert result.reason == "domain_policy_missing_sop_transfer_human"


def test_sop_records_are_referenced_without_leaking_raw_sop_content():
    unsafe_sop_text = "I approved your refund and will compensate you today."
    result = DomainPolicyResponder().respond(
        intent=AFTER_SALES_EVIDENCE_COLLECTION,
        sop_records=[
            {
                "id": "unsafe-sop-1",
                "source": "sop_fixture",
                "domain": AFTER_SALES_EVIDENCE_COLLECTION,
                "content": unsafe_sop_text,
            }
        ],
        query_summary="buyer says item arrived broken",
    )

    assert result.action == WorkflowAction.REQUEST_EVIDENCE
    assert result.knowledge_refs == [
        {
            "source": "sop_fixture",
            "domain": AFTER_SALES_EVIDENCE_COLLECTION,
            "record_id": "unsafe-sop-1",
        }
    ]
    serialized = repr(result)
    assert unsafe_sop_text not in serialized
    assert "buyer says item arrived broken" not in serialized
    assert OutputGuardrail.detect_risks(result.reply_text) == []


def test_output_guardrail_still_blocks_unsafe_domain_policy_response_text():
    unsafe = WorkflowResult(
        action=WorkflowAction.REPLY,
        reply_text="I can give you a private discount and compensate you today.",
        intent=PROMOTION_POLICY,
        reason="domain_policy_test_fixture",
        risk_flags=["promotion_policy"],
    )

    checked = OutputGuardrail.check(unsafe)

    assert checked.action == WorkflowAction.TRANSFER_HUMAN
    assert checked.reason == "output_guardrail_policy_violation"
    assert checked.reply_text == OutputGuardrail.DEFAULT_TRANSFER_REPLY
    assert "policy_violation" in checked.risk_flags
    assert "private_discount" in checked.risk_flags
    assert "compensation" in checked.risk_flags
