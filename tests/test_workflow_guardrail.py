import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.guardrail import OutputGuardrail
from Message.workflow.types import WorkflowAction, WorkflowResult


def _result(reply_text: str, *, action: WorkflowAction = WorkflowAction.REPLY) -> WorkflowResult:
    return WorkflowResult(action=action, reply_text=reply_text, intent="test_intent", reason="test_reason")


def test_safe_logistics_boundary_reply_passes():
    original = _result("Please check the order logistics page for the latest carrier status. I can transfer you to support if you need help verifying it.")

    checked = OutputGuardrail.check(original)

    assert checked is original
    assert checked.action == WorkflowAction.REPLY
    assert checked.reply_text == original.reply_text
    assert checked.risk_flags == []
    assert checked.trace == {}


def test_refund_compensation_reship_private_discount_concrete_logistics_fake_product_and_medical_certainty_are_flagged():
    cases = {
        "refund": "I approved your refund and it will be returned today.",
        "compensation": "We will compensate you 20 dollars for this issue.",
        "reship": "We will send a replacement package right away.",
        "private_discount": "I can give you a private discount if you order now.",
        "concrete_logistics": "Your package has already shipped and will arrive tomorrow.",
        "fake_product": "This item is definitely fake and the seller is liable.",
        "medical_certainty": "This medicine is guaranteed safe for pregnant customers and will cure the symptoms.",
    }

    for risk, text in cases.items():
        checked = OutputGuardrail.check(_result(text))

        assert "policy_violation" in checked.risk_flags
        assert risk in checked.risk_flags


def test_chinese_promotion_and_platform_outcome_promises_are_flagged():
    cases = {
        "private_discount": "亲，可以给您送赠品并返差价。",
        "fake_product": "您投诉12315一定会支持，平台会判商家责任。",
    }

    for risk, text in cases.items():
        checked = OutputGuardrail.check(_result(text))

        assert checked.action == WorkflowAction.TRANSFER_HUMAN
        assert risk in checked.risk_flags


def test_unsafe_reply_is_converted_to_transfer_human_with_policy_violation_flag():
    checked = OutputGuardrail.check(_result("I approved your refund and will compensate you today."))

    assert checked.action == WorkflowAction.TRANSFER_HUMAN
    assert checked.reply_text == OutputGuardrail.DEFAULT_TRANSFER_REPLY
    assert "policy_violation" in checked.risk_flags
    assert "refund" in checked.risk_flags
    assert "compensation" in checked.risk_flags
    assert checked.reason == "output_guardrail_policy_violation"


def test_existing_non_reply_action_can_be_converted_to_fallback_with_policy_violation_flag():
    checked = OutputGuardrail.check(
        _result("We guarantee this product is safe for everyone.", action=WorkflowAction.FALLBACK),
        unsafe_action=WorkflowAction.FALLBACK,
    )

    assert checked.action == WorkflowAction.FALLBACK
    assert checked.reply_text == OutputGuardrail.DEFAULT_FALLBACK_REPLY
    assert "policy_violation" in checked.risk_flags
    assert "medical_certainty" in checked.risk_flags


def test_safe_replies_with_existing_flags_are_preserved():
    original = _result("Discounts and shipping status are subject to the product page, checkout page, and carrier tracking page.")
    original.risk_flags.append("order_context_required")

    checked = OutputGuardrail.check(original)

    assert checked is original
    assert checked.action == WorkflowAction.REPLY
    assert checked.reply_text == original.reply_text
    assert checked.risk_flags == ["order_context_required"]


def test_raw_original_reply_is_not_copied_to_diagnostics_or_logger_output(caplog):
    unsafe_text = "SECRET_BUYER_TEXT I approved your refund and will compensate you today."

    checked = OutputGuardrail.check(_result(unsafe_text))

    assert unsafe_text not in repr(checked.trace)
    assert unsafe_text not in checked.reason
    assert unsafe_text not in checked.raw_error_summary
    assert unsafe_text not in caplog.text
    assert checked.reply_text != unsafe_text
