"""Offline output guardrail for workflow replies.

The guardrail is intentionally deterministic and self-contained. It does not
call LLMs, FastGPT, embeddings, or external policy services.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Iterable, Pattern

from .types import WorkflowAction, WorkflowResult


class OutputGuardrail:
    """Validate workflow output text for policy-sensitive promises or claims."""

    DEFAULT_TRANSFER_REPLY = "I need to transfer this to a human support specialist for confirmation."
    DEFAULT_FALLBACK_REPLY = "I cannot confirm that here. Please contact human support for help."

    _RISK_PATTERNS: tuple[tuple[str, tuple[Pattern[str], ...]], ...] = (
        (
            "refund",
            (
                re.compile(r"\b(refund|refunded|refunds)\b.*\b(approved|processed|issued|returned|today|now)\b", re.I),
                re.compile(r"\b(approved|processed|issued)\b.*\b(refund|refunds)\b", re.I),
                re.compile(r"退款.*(批准|通过|马上|立刻|今天|已经|会退|给您退)", re.I),
            ),
        ),
        (
            "reship",
            (
                re.compile(r"\b(reship|re-ship|replacement|send (you )?another|ship another)\b", re.I),
                re.compile(r"(补发|重发|换货|重新发|给您再发|寄一个新的)", re.I),
            ),
        ),
        (
            "compensation",
            (
                re.compile(r"\b(compensate|compensation|credit you|pay you|reimburse)\b", re.I),
                re.compile(r"(赔偿|补偿|赔付|补您|赔您|返现|给您.*红包)", re.I),
            ),
        ),
        (
            "private_discount",
            (
                re.compile(r"\b(private discount|special discount|give you .*discount|coupon just for you)\b", re.I),
                re.compile(r"(私下优惠|私下给|单独优惠|给您优惠|给你优惠|专属优惠|内部价|送赠品|赠送赠品|给您赠品|返差价|退差价)", re.I),
            ),
        ),
        (
            "concrete_logistics",
            (
                re.compile(r"\b(has shipped|already shipped|will arrive|arrives|delivered by|out for delivery)\b", re.I),
                re.compile(r"\b(today|tomorrow|tonight|this afternoon|this morning|within \d+ (hours?|days?))\b.*\b(arrive|deliver|ship)\b", re.I),
                re.compile(r"(已经发货|已发出|正在派送|今天到|明天到|今晚到|一定到|肯定到|预计.*到达|预计.*送达)", re.I),
            ),
        ),
        (
            "fake_product",
            (
                re.compile(r"\b(definitely|certainly|confirmed)\b.*\b(fake|counterfeit|liable|responsible)\b", re.I),
                re.compile(r"\b(fake|counterfeit)\b.*\b(product|item|seller|store)\b", re.I),
                re.compile(r"(假货|伪劣|欺诈|诈骗|商家.*责任|卖家.*责任|平台.*责任|一定负责|肯定负责|投诉.*会赢|12315.*会支持|法律.*一定|平台.*会判)", re.I),
            ),
        ),
        (
            "medical_certainty",
            (
                re.compile(r"\b(guaranteed|definitely|certainly|100%)\b.*\b(safe|cure|treat|heal|medical|medicine|pregnant)\b", re.I),
                re.compile(r"\b(safe for everyone|will cure|guaranteed safe|no side effects)\b", re.I),
                re.compile(r"(一定安全|绝对安全|放心使用|保证安全|没有副作用|治疗|治愈|药品.*安全|孕妇.*安全)", re.I),
            ),
        ),
    )

    @classmethod
    def check(
        cls,
        result: WorkflowResult,
        context: object | None = None,
        *,
        unsafe_action: WorkflowAction = WorkflowAction.TRANSFER_HUMAN,
    ) -> WorkflowResult:
        """Return the original result when safe, otherwise a sanitized result."""
        del context

        reply_text = str(result.reply_text or "")
        risks = cls.detect_risks(reply_text)
        if not risks:
            return result

        action = unsafe_action if isinstance(unsafe_action, WorkflowAction) else WorkflowAction.TRANSFER_HUMAN
        replacement_reply = cls.DEFAULT_FALLBACK_REPLY if action == WorkflowAction.FALLBACK else cls.DEFAULT_TRANSFER_REPLY
        risk_flags = cls._merged_flags(result.risk_flags, ("policy_violation", *risks))
        trace = cls._safe_trace(result.trace, reply_text, risks)

        return replace(
            result,
            action=action,
            reply_text=replacement_reply,
            reason="output_guardrail_policy_violation",
            risk_flags=risk_flags,
            trace=trace,
            raw_error_summary="",
        )

    @classmethod
    def apply(
        cls,
        result: WorkflowResult,
        context: object | None = None,
        *,
        unsafe_action: WorkflowAction = WorkflowAction.TRANSFER_HUMAN,
    ) -> WorkflowResult:
        """Alias for callers that prefer action-oriented naming."""
        return cls.check(result, context=context, unsafe_action=unsafe_action)

    @classmethod
    def detect_risks(cls, reply_text: str) -> list[str]:
        """Return deterministic risk labels found in reply text."""
        text = str(reply_text or "")
        if not text:
            return []

        risks: list[str] = []
        for risk, patterns in cls._RISK_PATTERNS:
            if risk == "compensation" and cls._is_non_committal_compensation(text):
                continue
            if risk == "private_discount" and cls._is_negated_private_discount(text):
                continue
            if cls._matches_any(text, patterns):
                risks.append(risk)
        return risks

    @staticmethod
    def _matches_any(text: str, patterns: Iterable[Pattern[str]]) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    @staticmethod
    def _is_negated_private_discount(text: str) -> bool:
        normalized = " ".join(str(text or "").lower().split())
        return any(
            phrase in normalized
            for phrase in (
                "cannot offer a private discount",
                "can't offer a private discount",
                "do not offer a private discount",
                "not offer a private discount",
                "no private discount",
                "无法承诺私下优惠",
                "不能承诺私下优惠",
                "不承诺私下优惠",
                "不提供私下优惠",
                "暂不承诺额外私下优惠",
                "不能承诺额外私下优惠",
                "无法承诺额外私下优惠",
            )
        )

    @staticmethod
    def _is_non_committal_compensation(text: str) -> bool:
        normalized = " ".join(str(text or "").lower().split())
        return any(
            phrase in normalized
            for phrase in (
                "do not make compensation commitments",
                "cannot confirm compensation",
                "compensation requires human review",
                "赔付结果的问题，需要人工",
                "赔偿结果的问题，需要人工",
                "不做赔偿结论",
                "不承诺赔偿",
                "不能承诺赔偿",
            )
        )

    @staticmethod
    def _merged_flags(existing: Iterable[str], additions: Iterable[str]) -> list[str]:
        merged: list[str] = []
        for flag in (*tuple(existing or ()), *tuple(additions)):
            value = str(flag or "").strip()
            if value and value not in merged:
                merged.append(value)
        return merged

    @staticmethod
    def _safe_trace(existing_trace: object, reply_text: str, risks: Iterable[str]) -> dict[str, object]:
        trace = dict(existing_trace) if isinstance(existing_trace, dict) else {}
        trace["output_guardrail"] = {
            "reply_length": len(reply_text),
            "reply_hash": hashlib.sha256(reply_text.encode("utf-8")).hexdigest()[:16],
            "risk_count": len(tuple(risks)),
        }
        return trace
