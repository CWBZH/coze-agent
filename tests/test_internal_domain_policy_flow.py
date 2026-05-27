import asyncio

import pytest
import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.intent_classifier import IntentClassification
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.types import WorkflowAction, WorkflowContext, WorkflowResult


def _context(content: str = "policy question") -> WorkflowContext:
    return WorkflowContext(
        trace_id="trace-domain-policy-flow-1",
        shop_id="synthetic-shop-1",
        user_id="user-1",
        customer_uid="buyer-1",
        buyer_id="buyer-1",
        session_id="session-1",
        chat_id="chat-1",
        dataset_id="dataset-1",
        message_type="text",
        content=content,
    )


class SpyIntentClassifier:
    def __init__(self, intent: str, *, confidence: float = 0.93, risk_flags=None):
        self.classification = IntentClassification(
            intent=intent,
            confidence=confidence,
            reason="fixture_classifier",
            risk_flags=list(risk_flags or []),
        )
        self.calls = []

    async def classify(self, content, content_metadata=None):
        self.calls.append((content, content_metadata))
        return self.classification


class FakeSopRetriever:
    def __init__(self, records_by_domain):
        self.records_by_domain = records_by_domain
        self.calls = []

    def search(self, *, shop_id, domain, query, limit=3):
        self.calls.append({"shop_id": shop_id, "domain": domain, "query": query, "limit": limit})
        return list(self.records_by_domain.get(domain, []))


class SpyDomainPolicyResponder:
    def __init__(self, replies_by_domain):
        self.replies_by_domain = replies_by_domain
        self.calls = []

    def respond_workflow(self, *, intent="", domain="", sop_records=None, query_summary=""):
        records = list(sop_records or [])
        selected_domain = domain or intent
        self.calls.append(
            {
                "intent": intent,
                "domain": selected_domain,
                "sop_record_count": len(records),
                "query_summary": query_summary,
            }
        )
        if not records:
            return WorkflowResult(
                action=WorkflowAction.FALLBACK,
                reply_text="I cannot confirm that here. Please contact human support for help.",
                intent=intent,
                reason="domain_policy_missing_sop",
                risk_flags=["domain_policy_missing_sop"],
            )
        action, reply_text, reason = self.replies_by_domain[selected_domain]
        return WorkflowResult(
            action=action,
            reply_text=reply_text,
            intent=intent,
            reason=reason,
            risk_flags=[selected_domain],
            knowledge_refs=[
                {
                    "source": "sop_fixture",
                    "domain": selected_domain,
                    "record_id": records[0]["id"],
                }
            ],
        )


def _engine(*, intent, sop_domain=None, sop_records=None, replies_by_domain=None):
    engine = InternalWorkflowEngine(intent_classifier=SpyIntentClassifier(intent))
    engine.sop_retriever = FakeSopRetriever({sop_domain or intent: list(sop_records or [])})
    engine.domain_policy_responder = SpyDomainPolicyResponder(replies_by_domain or {})
    return engine


@pytest.mark.parametrize(
    ("intent", "domain", "action", "reply_text", "reason", "forbidden"),
    [
        (
            "logistics_order_status",
            "logistics_policy",
            WorkflowAction.REPLY,
            "Please check the order logistics page; I cannot promise shipping status or arrival time.",
            "logistics_policy_order_page_boundary",
            ("already shipped", "will arrive tomorrow"),
        ),
        (
            "after_sales_evidence_collection",
            "after_sales_evidence",
            WorkflowAction.REQUEST_EVIDENCE,
            "Please provide order info, package photos, item photos, and issue details for review.",
            "request_buyer_evidence",
            ("refund approved", "replacement shipped", "compensation"),
        ),
        (
            "promotion_policy",
            "promotion_policy",
            WorkflowAction.REPLY,
            "Please follow the product page, campaign page, and checkout page. I cannot offer a private discount.",
            "promotion_policy_page_or_checkout_boundary",
            ("give you a discount", "private deal"),
        ),
        (
            "human_escalation_redline",
            "redline_escalation",
            WorkflowAction.TRANSFER_HUMAN,
            "This needs human support to review the order and platform rules.",
            "redline_requires_human_review",
            ("definitely fake", "compensation approved"),
        ),
        (
            "sensitive_user_safety",
            "sensitive_user_safety",
            WorkflowAction.REPLY,
            "Please check product instructions and consult a qualified professional for health or pregnancy concerns.",
            "sensitive_safety_conservative_boundary",
            ("guaranteed safe", "will cure"),
        ),
    ],
)
def test_internal_engine_routes_classifier_domain_to_sop_backed_policy_responder(
    intent,
    domain,
    action,
    reply_text,
    reason,
    forbidden,
):
    async def scenario():
        engine = _engine(
            intent=intent,
            sop_domain=domain,
            sop_records=[
                {
                    "id": f"sop-{domain}",
                    "source": "sop_fixture",
                    "shop_id": "synthetic-shop-1",
                    "domain": domain,
                    "version": "sop-test-v1",
                }
            ],
            replies_by_domain={domain: (action, reply_text, reason)},
        )

        result = await engine.run(_context())

        assert result.action == action
        assert result.intent == intent
        assert result.reason == reason
        assert reply_text == result.reply_text
        assert all(term not in result.reply_text for term in forbidden)
        assert result.knowledge_refs[0]["record_id"] == f"sop-{domain}"
        assert engine.domain_policy_responder.calls == [
            {
                "intent": intent,
                "domain": domain,
                "sop_record_count": 1,
                "query_summary": "policy question",
            }
        ]

    asyncio.run(scenario())


def test_internal_engine_uses_domain_policy_fallback_when_sop_records_are_missing():
    async def scenario():
        intent = "promotion_policy"
        engine = _engine(intent=intent, sop_records=[], replies_by_domain={})

        result = await engine.run(_context())

        assert result.action == WorkflowAction.FALLBACK
        assert result.intent == intent
        assert result.reason == "domain_policy_missing_sop"
        assert "domain_policy_missing_sop" in result.risk_flags
        assert engine.domain_policy_responder.calls[0]["sop_record_count"] == 0

    asyncio.run(scenario())


def test_internal_engine_guardrail_blocks_unsafe_sop_responder_output():
    async def scenario():
        intent = "promotion_policy"
        engine = _engine(
            intent=intent,
            sop_records=[{"id": "unsafe-sop", "source": "sop_fixture", "domain": intent}],
            replies_by_domain={
                intent: (
                    WorkflowAction.REPLY,
                    "I can give you a private discount and compensate you today.",
                    "promotion_policy_page_or_checkout_boundary",
                )
            },
        )

        result = await engine.run(_context())

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.reason == "output_guardrail_policy_violation"
        assert "policy_violation" in result.risk_flags
        assert "private_discount" in result.risk_flags
        assert "compensation" in result.risk_flags

    asyncio.run(scenario())
