"""Offline intent classifier contracts and validation helpers.

This module defines the future LLM classifier boundary without invoking any
external model provider. The fake classifier is deterministic and intended for
tests or local workflow experiments only.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Protocol, Sequence


EXPLICIT_HUMAN_REQUEST = "explicit_human_request"
HUMAN_ESCALATION_REDLINE = "human_escalation_redline"
AFTER_SALES_EVIDENCE_COLLECTION = "after_sales_evidence_collection"
LOGISTICS_ORDER_STATUS = "logistics_order_status"
LOGISTICS_POLICY = "logistics_policy"
PROMOTION_POLICY = "promotion_policy"
SENSITIVE_USER_SAFETY = "sensitive_user_safety"
PRODUCT_BASIC = "product_basic"
ASK_PRODUCT_CLARIFICATION = "ask_product_clarification"
FALLBACK = "fallback"

VALID_INTENTS = frozenset(
    {
        EXPLICIT_HUMAN_REQUEST,
        HUMAN_ESCALATION_REDLINE,
        AFTER_SALES_EVIDENCE_COLLECTION,
        LOGISTICS_ORDER_STATUS,
        LOGISTICS_POLICY,
        PROMOTION_POLICY,
        SENSITIVE_USER_SAFETY,
        PRODUCT_BASIC,
        ASK_PRODUCT_CLARIFICATION,
        FALLBACK,
    }
)

PRODUCT_CATALOG_DOMAIN = "product_catalog"
LOGISTICS_POLICY_DOMAIN = "logistics_policy"
AFTER_SALES_EVIDENCE_DOMAIN = "after_sales_evidence"
PROMOTION_POLICY_DOMAIN = "promotion_policy"
REDLINE_ESCALATION_DOMAIN = "redline_escalation"
SENSITIVE_USER_SAFETY_DOMAIN = "sensitive_user_safety"

VALID_DOMAINS = frozenset(
    {
        PRODUCT_CATALOG_DOMAIN,
        LOGISTICS_POLICY_DOMAIN,
        AFTER_SALES_EVIDENCE_DOMAIN,
        PROMOTION_POLICY_DOMAIN,
        REDLINE_ESCALATION_DOMAIN,
        SENSITIVE_USER_SAFETY_DOMAIN,
    }
)

INTENT_DOMAIN_MAP = {
    PRODUCT_BASIC: PRODUCT_CATALOG_DOMAIN,
    LOGISTICS_ORDER_STATUS: LOGISTICS_POLICY_DOMAIN,
    LOGISTICS_POLICY: LOGISTICS_POLICY_DOMAIN,
    AFTER_SALES_EVIDENCE_COLLECTION: AFTER_SALES_EVIDENCE_DOMAIN,
    PROMOTION_POLICY: PROMOTION_POLICY_DOMAIN,
    SENSITIVE_USER_SAFETY: SENSITIVE_USER_SAFETY_DOMAIN,
    HUMAN_ESCALATION_REDLINE: REDLINE_ESCALATION_DOMAIN,
    EXPLICIT_HUMAN_REQUEST: REDLINE_ESCALATION_DOMAIN,
    ASK_PRODUCT_CLARIFICATION: None,
    FALLBACK: None,
}

LOW_CONFIDENCE_THRESHOLD = 0.5
INVALID_INTENT_CONFIDENCE = 0.2

REDLINE_RISK_FLAG = "redline"
SENSITIVE_RISK_FLAG = SENSITIVE_USER_SAFETY

_RAW_CONTENT_KEYS = {
    "buyer_content",
    "content",
    "message",
    "messages",
    "raw",
    "raw_content",
    "reply",
    "text",
}
_REDLINE_KEYWORDS = (
    "12315",
    "complaint",
    "counterfeit",
    "expose",
    "fake",
    "fraud",
    "media",
    "platform complaint",
    "redline",
    "scam",
    "假货",
    "投诉",
    "曝光",
    "投诉",
    "假货",
    "诈骗",
    "曝光",
    "媒体",
    "平台投诉",
    "赔偿",
)
_SENSITIVE_KEYWORDS = (
    "allergy",
    "baby",
    "child",
    "doctor",
    "drug",
    "infant",
    "medical",
    "medicine",
    "pregnant",
    "sensitive",
    "treatment",
    "孕妇",
    "儿童",
    "婴儿",
    "宝宝",
    "医生",
    "医药",
    "过敏",
    "儿童",
    "医生",
    "医药",
    "宝宝",
    "孕妇",
    "治疗",
    "药",
    "过敏",
)


@dataclass(frozen=True)
class IntentClassification:
    intent: str
    confidence: float
    reason: str
    risk_flags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] | None = None
    domain: str | None = None
    requires_rag: bool | None = None
    requires_product_context: bool | None = None
    requires_order_context: bool | None = None
    requires_answer_generation: bool | None = None
    should_transfer_human: bool | None = None
    should_request_evidence: bool | None = None
    clarification_needed: bool | None = None


class LLMIntentClassifier(Protocol):
    async def classify(
        self,
        content: str,
        content_metadata: Mapping[str, Any] | None = None,
    ) -> IntentClassification:
        """Classify buyer content without exposing provider-specific details."""


RuleMatcher = Callable[[str, Mapping[str, Any]], bool]


class FakeLLMIntentClassifier:
    """Deterministic offline classifier for tests.

    The fake can return an injected result or evaluate rules in order. It never
    calls an external LLM or stores raw buyer content.
    """

    def __init__(
        self,
        result: IntentClassification | None = None,
        rules: Sequence[tuple[RuleMatcher, IntentClassification]] | None = None,
        default: IntentClassification | None = None,
    ) -> None:
        self._result = result
        self._rules = list(rules or ())
        self._default = default or IntentClassification(
            intent=FALLBACK,
            confidence=0.0,
            reason="fake_classifier_no_rule_matched",
            risk_flags=[],
        )

    async def classify(
        self,
        content: str,
        content_metadata: Mapping[str, Any] | None = None,
    ) -> IntentClassification:
        metadata = content_metadata or {}
        if self._result is not None:
            return validate_classification(self._result, metadata)

        for matcher, classification in self._rules:
            if matcher(content, metadata):
                return validate_classification(classification, metadata)

        return validate_classification(self._default, metadata)


def validate_classification(
    classification: IntentClassification,
    content_metadata: Mapping[str, Any] | None = None,
) -> IntentClassification:
    """Normalize and safety-guard a classifier result.

    The validator uses only metadata signals for safety overrides and never
    copies raw content into the returned classification.
    """

    metadata = content_metadata or {}
    intent = str(classification.intent or "").strip()
    confidence = _clamp_confidence(classification.confidence)
    reason = str(classification.reason or "").strip() or "classification_validated"
    risk_flags = _dedupe_flags(classification.risk_flags)
    safe_metadata = _sanitize_metadata(classification.metadata)
    domain = _normalize_domain(classification.domain)

    if _has_redline_signal(metadata, risk_flags):
        return IntentClassification(
            intent=HUMAN_ESCALATION_REDLINE,
            domain=REDLINE_ESCALATION_DOMAIN,
            confidence=1.0,
            reason="redline_signal_forced_human_escalation",
            risk_flags=_append_flag(risk_flags, REDLINE_RISK_FLAG),
            metadata=safe_metadata,
            requires_rag=False,
            requires_product_context=False,
            requires_order_context=False,
            requires_answer_generation=False,
            should_transfer_human=True,
            should_request_evidence=False,
            clarification_needed=False,
        )

    if _has_sensitive_signal(metadata, risk_flags, intent):
        return IntentClassification(
            intent=SENSITIVE_USER_SAFETY,
            domain=SENSITIVE_USER_SAFETY_DOMAIN,
            confidence=confidence,
            reason=(
                reason
                if intent == SENSITIVE_USER_SAFETY
                else "sensitive_signal_forced_user_safety"
            ),
            risk_flags=_append_flag(risk_flags, SENSITIVE_RISK_FLAG),
            metadata=safe_metadata,
            requires_rag=True,
            requires_product_context=False,
            requires_order_context=False,
            requires_answer_generation=True,
            should_transfer_human=False,
            should_request_evidence=False,
            clarification_needed=False,
        )

    if intent not in VALID_INTENTS:
        return IntentClassification(
            intent=FALLBACK,
            domain=None,
            confidence=min(confidence, INVALID_INTENT_CONFIDENCE),
            reason="invalid_intent_fallback",
            risk_flags=risk_flags,
            metadata={**safe_metadata, "clear": False},
            requires_rag=False,
            requires_product_context=False,
            requires_order_context=False,
            requires_answer_generation=False,
            should_transfer_human=False,
            should_request_evidence=False,
            clarification_needed=False,
        )

    expected_domain = INTENT_DOMAIN_MAP.get(intent)
    if domain is None:
        domain = expected_domain
    elif domain not in VALID_DOMAINS or domain != expected_domain:
        return IntentClassification(
            intent=FALLBACK,
            domain=None,
            confidence=min(confidence, INVALID_INTENT_CONFIDENCE),
            reason="invalid_domain_fallback",
            risk_flags=risk_flags,
            metadata={**safe_metadata, "clear": False},
            requires_rag=False,
            requires_product_context=False,
            requires_order_context=False,
            requires_answer_generation=False,
            should_transfer_human=False,
            should_request_evidence=False,
            clarification_needed=False,
        )

    if intent != FALLBACK and confidence < LOW_CONFIDENCE_THRESHOLD:
        return IntentClassification(
            intent=FALLBACK,
            domain=None,
            confidence=confidence,
            reason=f"low_confidence_fallback:{reason}",
            risk_flags=risk_flags,
            metadata={**safe_metadata, "clear": False},
            requires_rag=False,
            requires_product_context=False,
            requires_order_context=False,
            requires_answer_generation=False,
            should_transfer_human=False,
            should_request_evidence=False,
            clarification_needed=False,
        )

    defaults = _intent_defaults(intent)
    return replace(
        classification,
        intent=intent,
        domain=domain,
        confidence=confidence,
        reason=reason,
        risk_flags=risk_flags,
        metadata=safe_metadata,
        requires_rag=_bool_or_default(classification.requires_rag, defaults["requires_rag"]),
        requires_product_context=_bool_or_default(
            classification.requires_product_context,
            defaults["requires_product_context"],
        ),
        requires_order_context=_bool_or_default(classification.requires_order_context, defaults["requires_order_context"]),
        requires_answer_generation=_bool_or_default(
            classification.requires_answer_generation,
            defaults["requires_answer_generation"],
        ),
        should_transfer_human=_bool_or_default(classification.should_transfer_human, defaults["should_transfer_human"]),
        should_request_evidence=_bool_or_default(
            classification.should_request_evidence,
            defaults["should_request_evidence"],
        ),
        clarification_needed=_bool_or_default(classification.clarification_needed, defaults["clarification_needed"]),
    )


def _normalize_domain(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _intent_defaults(intent: str) -> dict[str, bool]:
    requires_rag = intent in {
        PRODUCT_BASIC,
        LOGISTICS_ORDER_STATUS,
        LOGISTICS_POLICY,
        AFTER_SALES_EVIDENCE_COLLECTION,
        PROMOTION_POLICY,
        SENSITIVE_USER_SAFETY,
    }
    return {
        "requires_rag": requires_rag,
        "requires_product_context": intent in {PRODUCT_BASIC, ASK_PRODUCT_CLARIFICATION},
        "requires_order_context": intent == LOGISTICS_ORDER_STATUS,
        "requires_answer_generation": intent not in {FALLBACK, ASK_PRODUCT_CLARIFICATION, HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST},
        "should_transfer_human": intent in {HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST},
        "should_request_evidence": intent == AFTER_SALES_EVIDENCE_COLLECTION,
        "clarification_needed": intent == ASK_PRODUCT_CLARIFICATION,
    }


def _bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _clamp_confidence(value: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _dedupe_flags(flags: Sequence[str] | None) -> list[str]:
    deduped: list[str] = []
    for flag in flags or ():
        value = str(flag or "").strip()
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _append_flag(flags: Sequence[str], flag: str) -> list[str]:
    result = list(flags)
    if flag not in result:
        result.append(flag)
    return result


def _has_redline_signal(metadata: Mapping[str, Any], risk_flags: Sequence[str]) -> bool:
    return (
        REDLINE_RISK_FLAG in risk_flags
        or bool(metadata.get("redline"))
        or _metadata_flags_include(metadata, REDLINE_RISK_FLAG)
        or _metadata_signals_include(metadata, _REDLINE_KEYWORDS)
    )


def _has_sensitive_signal(
    metadata: Mapping[str, Any],
    risk_flags: Sequence[str],
    intent: str,
) -> bool:
    return (
        intent == SENSITIVE_USER_SAFETY
        or SENSITIVE_RISK_FLAG in risk_flags
        or bool(metadata.get("sensitive"))
        or _metadata_flags_include(metadata, SENSITIVE_RISK_FLAG)
        or _metadata_signals_include(metadata, _SENSITIVE_KEYWORDS)
    )


def _metadata_flags_include(metadata: Mapping[str, Any], flag: str) -> bool:
    return flag in _dedupe_flags(_as_sequence(metadata.get("risk_flags")))


def _metadata_signals_include(metadata: Mapping[str, Any], keywords: Sequence[str]) -> bool:
    haystack = " ".join(
        str(value).lower()
        for key, value in metadata.items()
        if key.lower() not in _RAW_CONTENT_KEYS
        for value in _as_sequence(value)
    )
    return any(keyword.lower() in haystack for keyword in keywords)


def content_safety_signals(content: str) -> list[str]:
    """Return coarse safety signals without retaining buyer wording."""

    text = str(content or "").lower()
    signals: list[str] = []
    if any(keyword.lower() in text for keyword in _REDLINE_KEYWORDS):
        signals.append(REDLINE_RISK_FLAG)
    if any(keyword.lower() in text for keyword in _SENSITIVE_KEYWORDS):
        signals.append(SENSITIVE_RISK_FLAG)
    return signals


def _as_sequence(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


def _sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if key_text.lower() in _RAW_CONTENT_KEYS:
            continue
        sanitized[key_text] = _sanitize_metadata_value(value)
    return sanitized


def _sanitize_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_metadata(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _sanitize_metadata_value(item)
            for item in value
            if not isinstance(item, str)
        ]
    if isinstance(value, str):
        return value if len(value) <= 64 and "\n" not in value else "[redacted]"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(type(value).__name__)
