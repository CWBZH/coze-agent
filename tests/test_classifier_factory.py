import asyncio

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.classifier_factory import (
    FAKE_INTENT_CLASSIFIER,
    INTENT_CLASSIFIER_ENV_VAR,
    NULL_INTENT_CLASSIFIER,
    OPENAI_COMPATIBLE_INTENT_CLASSIFIER,
    IntentClassifierFactoryConfig,
    NullIntentClassifier,
    create_intent_classifier,
    get_intent_classifier_name,
)
from Message.workflow.intent_classifier import FakeLLMIntentClassifier
from Message.workflow.llm_classifier import OpenAICompatibleIntentClassifier


class FakeTransport:
    def __init__(self):
        self.payloads = []

    async def complete(self, payload):
        self.payloads.append(payload)
        return '{"intent":"product_basic","confidence":0.91,"reason":"fake_transport","risk_flags":[]}'


def test_default_classifier_config_is_null_and_offline(monkeypatch):
    monkeypatch.delenv(INTENT_CLASSIFIER_ENV_VAR, raising=False)

    classifier = create_intent_classifier(env={})
    result = asyncio.run(classifier.classify("buyer text"))

    assert isinstance(classifier, NullIntentClassifier)
    assert result.intent == "fallback"
    assert result.reason == "no_rule_matched"


def test_fake_classifier_can_be_constructed_for_tests():
    classifier = create_intent_classifier(
        env={INTENT_CLASSIFIER_ENV_VAR: FAKE_INTENT_CLASSIFIER}
    )

    assert isinstance(classifier, FakeLLMIntentClassifier)


def test_illegal_classifier_value_falls_back_to_null():
    assert get_intent_classifier_name({INTENT_CLASSIFIER_ENV_VAR: "bogus"}) == NULL_INTENT_CLASSIFIER

    classifier = create_intent_classifier(env={INTENT_CLASSIFIER_ENV_VAR: "bogus"})

    assert isinstance(classifier, NullIntentClassifier)


def test_non_internal_backend_ignores_classifier_config():
    classifier = create_intent_classifier(
        IntentClassifierFactoryConfig(
            backend="fastgpt",
            classifier=FAKE_INTENT_CLASSIFIER,
        )
    )

    assert classifier is None


def test_openai_compatible_without_transport_is_disabled_until_configured():
    classifier = create_intent_classifier(
        env={INTENT_CLASSIFIER_ENV_VAR: OPENAI_COMPATIBLE_INTENT_CLASSIFIER}
    )

    result = asyncio.run(classifier.classify("product specs"))

    assert isinstance(classifier, OpenAICompatibleIntentClassifier)
    assert result.intent == "fallback"
    assert result.reason == "llm_classifier_disabled"


def test_use_real_intent_classifier_alias_does_not_select_provider_without_explicit_classifier():
    classifier_name = get_intent_classifier_name(
        {
            "AI_WORKFLOW_USE_REAL_INTENT_CLASSIFIER": "1",
        }
    )

    assert classifier_name == NULL_INTENT_CLASSIFIER


def test_openai_compatible_uses_fake_transport_and_validates_result():
    transport = FakeTransport()
    classifier = create_intent_classifier(
        env={INTENT_CLASSIFIER_ENV_VAR: OPENAI_COMPATIBLE_INTENT_CLASSIFIER},
        transport=transport,
    )

    result = asyncio.run(classifier.classify("product specs"))

    assert isinstance(classifier, OpenAICompatibleIntentClassifier)
    assert result.intent == "product_basic"
    assert result.reason == "llm_chinese_label:product_basic"
    assert transport.payloads
