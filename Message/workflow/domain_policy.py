"""Deterministic domain policy responder.

This module intentionally stays offline: no LLM, no FastGPT, no DB writes, and
no integration with the internal workflow engine. It turns SOP hits into
conservative domain-bound replies while keeping raw user text and raw SOP text
out of trace data.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .types import WorkflowAction, WorkflowResult


LOGISTICS_ORDER_STATUS = "logistics_order_status"
AFTER_SALES_EVIDENCE_COLLECTION = "after_sales_evidence_collection"
PROMOTION_POLICY = "promotion_policy"
REDLINE_ESCALATION = "redline_escalation"
SENSITIVE_USER_SAFETY = "sensitive_user_safety"


@dataclass(frozen=True)
class PolicyReplyResult:
    action: WorkflowAction
    reply_text: str
    intent: str
    domain: str
    reason: str
    risk_flags: list[str] = field(default_factory=list)
    knowledge_refs: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    def to_workflow_result(self) -> WorkflowResult:
        return WorkflowResult(
            action=self.action,
            reply_text=self.reply_text,
            intent=self.intent,
            reason=self.reason,
            risk_flags=list(self.risk_flags),
            knowledge_refs=list(self.knowledge_refs),
            trace=dict(self.trace),
        )


class DomainPolicyResponder:
    """Render conservative replies for SOP-backed policy domains."""

    FALLBACK_REPLY = "亲，这个问题暂时无法仅凭当前信息确认，建议转人工客服进一步核实。"
    TRANSFER_REPLY = "亲，这类情况需要人工客服进一步核实处理，我先为您转人工确认。"

    _DOMAIN_REPLIES: dict[str, tuple[WorkflowAction, str, str, tuple[str, ...]]] = {
        LOGISTICS_ORDER_STATUS: (
            WorkflowAction.REPLY,
            "亲，物流状态请以订单物流页展示为准。当前我不能直接确认是否已发货、运输节点或到达时间，如页面信息不清楚，建议转人工客服为您核实。",
            "logistics_policy_order_page_boundary",
            ("logistics_policy",),
        ),
        AFTER_SALES_EVIDENCE_COLLECTION: (
            WorkflowAction.REQUEST_EVIDENCE,
            "亲，为了方便售后核实，请您提供订单信息、包裹外观照片、商品实物照片，以及能说明问题的位置细节。客服会根据凭证和平台规则进一步处理。",
            "request_buyer_evidence",
            ("after_sales_evidence",),
        ),
        PROMOTION_POLICY: (
            WorkflowAction.REPLY,
            "亲，活动价格、优惠和赠品规则请以商品页面、活动页面和结算页展示为准。客服无法承诺私下优惠、额外赠品或返差价。",
            "promotion_policy_page_or_checkout_boundary",
            ("promotion_policy",),
        ),
        REDLINE_ESCALATION: (
            WorkflowAction.TRANSFER_HUMAN,
            "亲，涉及商品真伪、责任认定、投诉或赔付结果的问题，需要人工客服结合订单和平台规则核实，我先为您转人工处理。",
            "redline_requires_human_review",
            ("redline",),
        ),
        SENSITIVE_USER_SAFETY: (
            WorkflowAction.REPLY,
            "亲，涉及使用安全、特殊人群或健康相关情况，请先查看商品页面和产品说明；如有不适、疾病史或特殊身体状况，建议咨询专业人士，也可以转人工客服进一步确认商品信息。",
            "sensitive_safety_conservative_boundary",
            ("sensitive_safety",),
        ),
    }

    _DOMAIN_ALIASES = {
        "after_sales_evidence": AFTER_SALES_EVIDENCE_COLLECTION,
        "human_escalation_redline": REDLINE_ESCALATION,
        "explicit_human_request": REDLINE_ESCALATION,
        "logistics_policy": LOGISTICS_ORDER_STATUS,
    }

    def respond(
        self,
        *,
        intent: str = "",
        domain: str = "",
        sop_records: Iterable[Any] | None = None,
        query_summary: str = "",
    ) -> PolicyReplyResult:
        records = list(sop_records or [])
        selected_domain = self._normalize_domain(domain or intent)
        selected_intent = intent or selected_domain
        trace = self._safe_trace(
            selected_domain=selected_domain,
            records=records,
            query_summary=query_summary,
        )

        if not records:
            return self._missing_sop_result(
                intent=selected_intent,
                domain=selected_domain,
                trace=trace,
            )

        action, reply_text, reason, flags = self._DOMAIN_REPLIES.get(
            selected_domain,
            (
                WorkflowAction.FALLBACK,
                self.FALLBACK_REPLY,
                "domain_policy_not_supported",
                ("unsupported_domain_policy",),
            ),
        )
        refs = self._knowledge_refs(records)
        return PolicyReplyResult(
            action=action,
            reply_text=reply_text,
            intent=selected_intent,
            domain=selected_domain,
            reason=reason,
            risk_flags=list(flags),
            knowledge_refs=refs,
            trace=trace,
        )

    def respond_workflow(
        self,
        *,
        intent: str = "",
        domain: str = "",
        sop_records: Iterable[Any] | None = None,
        query_summary: str = "",
    ) -> WorkflowResult:
        return self.respond(
            intent=intent,
            domain=domain,
            sop_records=sop_records,
            query_summary=query_summary,
        ).to_workflow_result()

    def _missing_sop_result(self, *, intent: str, domain: str, trace: dict[str, Any]) -> PolicyReplyResult:
        if domain == REDLINE_ESCALATION:
            action = WorkflowAction.TRANSFER_HUMAN
            reply = self.TRANSFER_REPLY
            reason = "domain_policy_missing_sop_transfer_human"
        else:
            action = WorkflowAction.FALLBACK
            reply = self.FALLBACK_REPLY
            reason = "domain_policy_missing_sop"
        return PolicyReplyResult(
            action=action,
            reply_text=reply,
            intent=intent,
            domain=domain,
            reason=reason,
            risk_flags=["domain_policy_missing_sop"],
            trace=trace,
        )

    def _normalize_domain(self, value: str) -> str:
        normalized = str(value or "").strip()
        return self._DOMAIN_ALIASES.get(normalized, normalized)

    def _safe_trace(
        self,
        *,
        selected_domain: str,
        records: list[Any],
        query_summary: str,
    ) -> dict[str, Any]:
        summary = str(query_summary or "")
        return {
            "domain_policy_responder": {
                "domain": selected_domain,
                "sop_record_count": len(records),
                "sop_record_ids": self._record_ids(records),
                "query_summary_length": len(summary),
                "query_summary_hash": self._hash(summary) if summary else "",
            }
        }

    def _knowledge_refs(self, records: list[Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for index, record in enumerate(records[:3]):
            refs.append(
                {
                    "source": str(self._get(record, "source") or "sop"),
                    "domain": str(self._get(record, "domain") or ""),
                    "record_id": str(self._get(record, "id") or self._get(record, "record_id") or index),
                }
            )
        return refs

    def _record_ids(self, records: list[Any]) -> list[str]:
        ids: list[str] = []
        for index, record in enumerate(records[:10]):
            value = self._get(record, "id") or self._get(record, "record_id") or self._get(record, "sop_id") or index
            ids.append(str(value))
        return ids

    @staticmethod
    def _get(record: Any, key: str) -> Any:
        if isinstance(record, Mapping):
            return record.get(key)
        return getattr(record, key, None)

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
