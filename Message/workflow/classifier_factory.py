"""Intent classifier selection helpers for the internal workflow backend.

The production default remains the local null classifier. The OpenAI-compatible
adapter is only constructed when explicitly selected, so FastGPT and the default
internal path never create a real network client.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from .intent_classifier import (
    FALLBACK,
    FakeLLMIntentClassifier,
    IntentClassification,
    LLMIntentClassifier,
    validate_classification,
)
from .llm_classifier import (
    LLMClassifierTransport,
    OpenAICompatibleIntentClassifier,
    OpenAICompatibleIntentClassifierConfig,
)


INTENT_CLASSIFIER_ENV_VAR = "AI_WORKFLOW_INTENT_CLASSIFIER"
DEFAULT_INTENT_CLASSIFIER = "null"
NULL_INTENT_CLASSIFIER = "null"
FAKE_INTENT_CLASSIFIER = "fake"
OPENAI_COMPATIBLE_INTENT_CLASSIFIER = "openai_compatible"
VALID_INTENT_CLASSIFIERS = frozenset(
    {
        NULL_INTENT_CLASSIFIER,
        FAKE_INTENT_CLASSIFIER,
        OPENAI_COMPATIBLE_INTENT_CLASSIFIER,
    }
)


@dataclass(frozen=True)
class IntentClassifierFactoryConfig:
    """Configuration for selecting an internal workflow intent classifier."""

    classifier: str = DEFAULT_INTENT_CLASSIFIER
    backend: str = "internal"
    model: str = "intent-classifier"
    base_url: str = ""
    api_key_env: str = "AI_WORKFLOW_LLM_API_KEY"
    timeout_seconds: float = 20.0


class NullIntentClassifier:
    """Offline classifier that preserves the internal backend's null behavior."""

    async def classify(
        self,
        content: str,
        content_metadata: Mapping[str, object] | None = None,
    ) -> IntentClassification:
        del content
        return validate_classification(
            IntentClassification(intent=FALLBACK, confidence=0.0, reason="no_rule_matched"),
            content_metadata,
        )


def get_intent_classifier_name(
    env: Mapping[str, str] | None = None,
    default: str = DEFAULT_INTENT_CLASSIFIER,
) -> str:
    """Return a normalized classifier name, falling back to ``null``."""

    source = os.environ if env is None else env
    value = str(source.get(INTENT_CLASSIFIER_ENV_VAR) or default or DEFAULT_INTENT_CLASSIFIER)
    normalized = value.strip().lower()
    if normalized not in VALID_INTENT_CLASSIFIERS:
        return NULL_INTENT_CLASSIFIER
    return normalized


def create_intent_classifier(
    config: IntentClassifierFactoryConfig | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: LLMClassifierTransport | None = None,
) -> LLMIntentClassifier | None:
    """Create a classifier only for the internal backend.

    Non-internal backends ignore ``AI_WORKFLOW_INTENT_CLASSIFIER`` and return
    ``None`` so FastGPT routing is unaffected.
    """

    selected_config = config or IntentClassifierFactoryConfig(
        classifier=get_intent_classifier_name(env),
    )
    if selected_config.backend.strip().lower() != "internal":
        return None

    classifier_name = _normalize_classifier(selected_config.classifier)
    if classifier_name == FAKE_INTENT_CLASSIFIER:
        return FakeLLMIntentClassifier()
    if classifier_name == OPENAI_COMPATIBLE_INTENT_CLASSIFIER:
        return OpenAICompatibleIntentClassifier(
            transport=transport,
            config=OpenAICompatibleIntentClassifierConfig(
                base_url=selected_config.base_url,
                model=selected_config.model,
                api_key_env=selected_config.api_key_env,
                timeout_seconds=selected_config.timeout_seconds,
                enabled=bool(transport or (selected_config.base_url and selected_config.model)),
            ),
        )
    return NullIntentClassifier()


def _normalize_classifier(value: str) -> str:
    normalized = str(value or DEFAULT_INTENT_CLASSIFIER).strip().lower()
    if normalized not in VALID_INTENT_CLASSIFIERS:
        return NULL_INTENT_CLASSIFIER
    return normalized

