import asyncio

import pytest

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.intent_classifier import (
    FakeLLMIntentClassifier,
    IntentClassification,
    validate_classification,
)


def test_fake_classifier_returns_injected_valid_classification():
    classifier = FakeLLMIntentClassifier(
        result=IntentClassification(
            intent="product_basic",
            confidence=0.86,
            reason="rule:product_basic",
            risk_flags=["knowledge_allowed"],
            metadata={"source": "test"},
        )
    )

    result = asyncio.run(classifier.classify("buyer content must not be stored"))

    assert result.intent == "product_basic"
    assert result.confidence == pytest.approx(0.86)
    assert result.reason == "rule:product_basic"
    assert result.risk_flags == ["knowledge_allowed"]
    assert result.metadata == {"source": "test"}


def test_fake_classifier_can_use_deterministic_rules():
    classifier = FakeLLMIntentClassifier(
        rules=[
            (
                lambda text, metadata: "coupon" in text,
                IntentClassification(
                    intent="promotion_policy",
                    confidence=0.91,
                    reason="matched_coupon_rule",
                    risk_flags=[],
                ),
            )
        ]
    )

    result = asyncio.run(classifier.classify("coupon available?", {"channel": "test"}))

    assert result.intent == "promotion_policy"
    assert result.reason == "matched_coupon_rule"


def test_invalid_intent_validates_to_fallback():
    result = validate_classification(
        IntentClassification(
            intent="unknown_intent",
            confidence=0.93,
            reason="model_output_not_allowed",
            risk_flags=["kept"],
        )
    )

    assert result.intent == "fallback"
    assert result.confidence <= 0.2
    assert result.reason == "invalid_intent_fallback"
    assert result.risk_flags == ["kept"]


def test_low_confidence_validates_to_fallback_with_reason():
    result = validate_classification(
        IntentClassification(
            intent="product_basic",
            confidence=0.34,
            reason="weak_match",
            risk_flags=[],
        )
    )

    assert result.intent == "fallback"
    assert result.confidence == pytest.approx(0.34)
    assert result.reason == "low_confidence_fallback:weak_match"


def test_redline_content_forces_human_escalation_and_redline_flag():
    result = validate_classification(
        IntentClassification(
            intent="product_basic",
            confidence=0.88,
            reason="product_match",
            risk_flags=[],
        ),
        content_metadata={"signals": ["buyer said 12315 complaint"]},
    )

    assert result.intent == "human_escalation_redline"
    assert result.confidence == 1.0
    assert result.reason == "redline_signal_forced_human_escalation"
    assert "redline" in result.risk_flags


def test_redline_metadata_forces_human_escalation_and_preserves_flags():
    result = validate_classification(
        IntentClassification(
            intent="promotion_policy",
            confidence=0.7,
            reason="promotion_match",
            risk_flags=["existing_flag"],
        ),
        content_metadata={"risk_flags": ["redline"]},
    )

    assert result.intent == "human_escalation_redline"
    assert result.risk_flags == ["existing_flag", "redline"]


def test_sensitive_content_forces_sensitive_user_safety():
    result = validate_classification(
        IntentClassification(
            intent="product_basic",
            confidence=0.82,
            reason="product_match",
            risk_flags=[],
        ),
        content_metadata={"signals": ["pregnant buyer asks if this is safe"]},
    )

    assert result.intent == "sensitive_user_safety"
    assert result.reason == "sensitive_signal_forced_user_safety"
    assert "sensitive_user_safety" in result.risk_flags


def test_sensitive_metadata_preserves_existing_sensitive_handling():
    result = validate_classification(
        IntentClassification(
            intent="sensitive_user_safety",
            confidence=0.72,
            reason="already_sensitive",
            risk_flags=["custom_flag"],
        ),
        content_metadata={"sensitive": True},
    )

    assert result.intent == "sensitive_user_safety"
    assert result.confidence == pytest.approx(0.72)
    assert result.risk_flags == ["custom_flag", "sensitive_user_safety"]


def test_validation_does_not_store_raw_content_in_metadata_or_reason():
    raw_content = "buyer says 12315 and includes private details"

    result = validate_classification(
        IntentClassification(
            intent="product_basic",
            confidence=0.9,
            reason="product_match",
            risk_flags=[],
        ),
        content_metadata={"content": raw_content, "signals": [raw_content]},
    )

    assert raw_content not in result.reason
    assert raw_content not in repr(result.metadata)
