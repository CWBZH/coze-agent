"""OpenAI-compatible Chinese intent classifier adapter.

The adapter is transport-only: tests pass a fake transport, and the default
path never calls a provider. The model is asked to return one Chinese category
name; code maps that label to the internal intent schema.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .intent_classifier import (
    AFTER_SALES_EVIDENCE_COLLECTION,
    ASK_PRODUCT_CLARIFICATION,
    EXPLICIT_HUMAN_REQUEST,
    FALLBACK,
    HUMAN_ESCALATION_REDLINE,
    INTENT_DOMAIN_MAP,
    LOGISTICS_ORDER_STATUS,
    PRODUCT_BASIC,
    PROMOTION_POLICY,
    SENSITIVE_USER_SAFETY,
    IntentClassification,
    content_safety_signals,
    validate_classification,
)
from .prompt_builder import format_conversation_text
from .private_trace import write_private_trace
from .types import WorkflowContext


class LLMClassifierTransport(Protocol):
    async def complete(self, payload: Mapping[str, Any]) -> Any:
        """Return an OpenAI-compatible response or a plain classification label."""


CHINESE_LABEL_TO_INTENT: dict[str, str] = {
    "商品基础咨询": PRODUCT_BASIC,
    "物流订单查询": LOGISTICS_ORDER_STATUS,
    "售后取证处理": AFTER_SALES_EVIDENCE_COLLECTION,
    "优惠活动咨询": PROMOTION_POLICY,
    "敏感人群安全": SENSITIVE_USER_SAFETY,
    "红线转人工": HUMAN_ESCALATION_REDLINE,
    "明确要求人工": EXPLICIT_HUMAN_REQUEST,
    "商品信息缺失澄清": ASK_PRODUCT_CLARIFICATION,
    "其他问题": FALLBACK,
}

INTENT_TO_CHINESE_LABEL = {value: key for key, value in CHINESE_LABEL_TO_INTENT.items()}


@dataclass(frozen=True)
class OpenAICompatibleIntentClassifierConfig:
    model: str = "intent-classifier"
    base_url: str = ""
    api_key_env: str = "AI_WORKFLOW_LLM_API_KEY"
    timeout_seconds: float = 20.0
    temperature: float = 0.0
    confidence_threshold: float = 0.5
    enabled: bool = False


class OpenAICompatibleIntentClassifier:
    """Classify ``WorkflowContext`` via an injected OpenAI-compatible transport."""

    def __init__(
        self,
        transport: LLMClassifierTransport | None = None,
        config: OpenAICompatibleIntentClassifierConfig | None = None,
        *,
        base_url: str = "",
        model: str = "",
        api_key_env: str = "AI_WORKFLOW_LLM_API_KEY",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._transport = transport
        self._config = config or OpenAICompatibleIntentClassifierConfig(
            base_url=base_url,
            model=model or "intent-classifier",
            api_key_env=api_key_env,
            timeout_seconds=timeout_seconds,
            enabled=bool(base_url and model),
        )

    async def classify_context(self, context: WorkflowContext) -> IntentClassification:
        metadata = self._metadata_from_context(context)
        if not self._config.enabled:
            return validate_classification(
                IntentClassification(
                    intent=FALLBACK,
                    confidence=0.0,
                    reason="llm_classifier_disabled",
                    risk_flags=[],
                ),
                metadata,
            )

        payload = self._build_payload(context)
        response: Any = None
        try:
            write_private_trace(
                context.trace_id,
                "intent_classifier_input",
                {
                    "latest_message": context.content,
                    "history": list(context.history or []),
                    "product_context": (context.metadata or {}).get("product_context", {})
                    if isinstance(context.metadata, dict)
                    else {},
                    "request_payload": payload,
                },
            )
            if self._transport is not None:
                response = await self._maybe_await(self._transport.complete(payload))
            else:
                response = self._post_json(payload)
            label = self._extract_label(response)
            classification = self._classification_from_label(label)
            write_private_trace(
                context.trace_id,
                "intent_classifier_output",
                {
                    "response_text": self._response_text(response),
                    "label": label,
                    "classification": {
                        "intent": classification.intent,
                        "domain": classification.domain,
                        "confidence": classification.confidence,
                        "reason": classification.reason,
                        "requires_rag": classification.requires_rag,
                        "requires_product_context": classification.requires_product_context,
                        "should_transfer_human": classification.should_transfer_human,
                        "should_request_evidence": classification.should_request_evidence,
                        "clarification_needed": classification.clarification_needed,
                    },
                },
            )
        except Exception as exc:
            raw_text = self._response_text(response)
            write_private_trace(
                context.trace_id,
                "intent_classifier_output",
                {
                    "response_text": raw_text,
                    "error_type": type(exc).__name__,
                    "parse_fallback": True,
                },
            )
            classification = self._keyword_fallback(
                context,
                reason="llm_classifier_parse_fallback",
                extra_metadata={
                    "llm_classifier_parse_fallback": True,
                    "llm_classifier_raw_length": len(raw_text),
                    "llm_classifier_raw_hash": _stable_hash(raw_text),
                    "parse_error_type": type(exc).__name__,
                },
            )

        return validate_classification(classification, metadata)

    def _post_json(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        api_key = os.environ.get(self._config.api_key_env, "")
        if not api_key:
            raise RuntimeError("missing_api_key")
        base_url = str(self._config.base_url or "").rstrip("/")
        if not base_url:
            raise RuntimeError("missing_base_url")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=float(self._config.timeout_seconds or 20.0)) as response:
            return json.loads(response.read().decode("utf-8"))

    async def classify(
        self,
        content: str,
        content_metadata: Mapping[str, Any] | None = None,
    ) -> IntentClassification:
        context = WorkflowContext(content=content, metadata=dict(content_metadata or {}))
        return await self.classify_context(context)

    def _build_payload(self, context: WorkflowContext) -> dict[str, Any]:
        conversation_text = format_conversation_text(context)
        return {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {
                    "role": "user",
                    "content": f"输入如下：\n{conversation_text}\n\n请只返回一个分类名称。",
                },
            ],
        }

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    @classmethod
    def _extract_label(cls, response: Any) -> str:
        if isinstance(response, Mapping):
            if "choices" in response:
                content = response["choices"][0]["message"]["content"]
                return _clean_label(str(content or ""))
            # Test/backward compatibility: allow direct structured values.
            if "label" in response or "category" in response:
                return _clean_label(str(response.get("label") or response.get("category") or ""))
            if "intent" in response:
                return INTENT_TO_CHINESE_LABEL.get(str(response.get("intent") or ""), "其他问题")
            return "其他问题"
        if isinstance(response, str):
            text = _clean_label(response)
            if text.startswith("{"):
                try:
                    data = json.loads(text)
                    if isinstance(data, Mapping) and "intent" in data:
                        return INTENT_TO_CHINESE_LABEL.get(str(data.get("intent") or ""), "其他问题")
                except json.JSONDecodeError:
                    pass
            return text
        return "其他问题"

    def _classification_from_label(self, label: str) -> IntentClassification:
        normalized = _clean_label(label)
        intent = CHINESE_LABEL_TO_INTENT.get(normalized)
        if intent is None:
            return IntentClassification(
                intent=FALLBACK,
                domain=None,
                confidence=0.2,
                reason="llm_classifier_unrecognized_label",
                risk_flags=[],
                metadata={"classifier_label_hash": _stable_hash(normalized), "classifier_label_valid": False},
                requires_rag=False,
                requires_product_context=False,
                requires_order_context=False,
                requires_answer_generation=False,
                should_transfer_human=False,
                should_request_evidence=False,
                clarification_needed=False,
            )
        return IntentClassification(
            intent=intent,
            domain=INTENT_DOMAIN_MAP.get(intent),
            confidence=0.9 if intent != FALLBACK else 0.0,
            reason=f"llm_chinese_label:{intent}",
            risk_flags=_risk_flags_for_intent(intent),
            metadata={
                "classifier_label_hash": _stable_hash(normalized),
                "classifier_label_intent": intent,
                "classifier_label_valid": True,
            },
            requires_rag=intent in {
                PRODUCT_BASIC,
                LOGISTICS_ORDER_STATUS,
                AFTER_SALES_EVIDENCE_COLLECTION,
                PROMOTION_POLICY,
                SENSITIVE_USER_SAFETY,
            },
            requires_product_context=intent in {PRODUCT_BASIC, ASK_PRODUCT_CLARIFICATION},
            requires_order_context=intent == LOGISTICS_ORDER_STATUS,
            requires_answer_generation=intent not in {FALLBACK, ASK_PRODUCT_CLARIFICATION, HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST},
            should_transfer_human=intent in {HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST},
            should_request_evidence=intent == AFTER_SALES_EVIDENCE_COLLECTION,
            clarification_needed=intent == ASK_PRODUCT_CLARIFICATION,
        )

    def _keyword_fallback(
        self,
        context: WorkflowContext,
        *,
        reason: str,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> IntentClassification:
        text = format_conversation_text(context)
        current = str(context.content or "")
        label = _keyword_label(current, text)
        classification = self._classification_from_label(label)
        return IntentClassification(
            intent=classification.intent,
            domain=classification.domain,
            confidence=0.72 if classification.intent != FALLBACK else 0.0,
            reason=reason if classification.intent == FALLBACK else f"{reason}:keyword_fallback",
            risk_flags=classification.risk_flags,
            metadata={**(extra_metadata or {}), "keyword_fallback_label": label},
            requires_rag=classification.requires_rag,
            requires_product_context=classification.requires_product_context,
            requires_order_context=classification.requires_order_context,
            requires_answer_generation=classification.requires_answer_generation,
            should_transfer_human=classification.should_transfer_human,
            should_request_evidence=classification.should_request_evidence,
            clarification_needed=classification.clarification_needed,
        )

    @classmethod
    def _response_text(cls, response: Any) -> str:
        if response is None:
            return ""
        if isinstance(response, str):
            return response
        if isinstance(response, Mapping):
            if "choices" in response:
                try:
                    return str(response["choices"][0]["message"].get("content") or "")
                except Exception:
                    return ""
            try:
                return json.dumps(response, ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(type(response).__name__)
        return str(type(response).__name__)

    @staticmethod
    def _metadata_from_context(context: WorkflowContext) -> dict[str, Any]:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        risk_flags = OpenAICompatibleIntentClassifier._string_list(metadata.get("risk_flags"))
        signals = OpenAICompatibleIntentClassifier._string_list(metadata.get("signals"))
        for signal in content_safety_signals(context.content):
            if signal not in signals:
                signals.append(signal)
        return {
            "trace_id": context.trace_id,
            "shop_id": context.shop_id,
            "user_id": context.user_id,
            "session_id": context.session_id,
            "message_type": context.message_type,
            "risk_flags": risk_flags,
            "signals": signals,
            "sensitive": bool(metadata.get("sensitive", False)),
            "redline": bool(metadata.get("redline", False)),
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set, frozenset)):
            items = value
        else:
            items = (value,)
        result: list[str] = []
        for item in items:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result


def _system_prompt() -> str:
    return """你是一个拼多多店铺客服问题分类器。你的任务是根据完整聊天记录和当前买家问题，判断当前问题属于哪个类别。

你只能返回下面9个分类之一：
商品基础咨询
物流订单查询
售后取证处理
优惠活动咨询
敏感人群安全
红线转人工
明确要求人工
商品信息缺失澄清
其他问题

只返回分类名称，不要解释，不要输出JSON，不要输出Markdown，不要输出多余文字。

分类规则：

【商品基础咨询】
用户询问商品价格、规格、型号、款式、颜色、味道、香型、用法、成分、保质期、功效、适合人群、是否新品、库存、推荐哪款、怎么选、有什么区别等。
如果前文里有商品卡片或商品名称，用户问“这个多少钱”“这个怎么用”“这款是新品吗”等，都属于商品基础咨询。

【物流订单查询】
用户询问什么时候发货、什么时候到、快递、物流、运输、运费、配送、订单状态、单号、到哪里了等。

【售后取证处理】
用户收到货后反馈破损、漏液、少发、错发、质量问题、包装损坏、不能用、坏了、需要怎么处理、退换货流程等，需要收集照片、包装、订单、问题描述等证据。

【优惠活动咨询】
用户询问能不能便宜点、优惠券、满减、活动、赠品、返差价、议价、打折、价格能否再低等。

【敏感人群安全】
用户询问孕妇、儿童、宝宝、老人、敏感肌、过敏、伤口、疾病、哺乳期、医用安全、是否一定安全等。

【红线转人工】
用户涉及假货、真假判断、投诉、差评、赔偿、12315、法律责任、平台介入、威胁、严重争议、辱骂、责任归属判断等。

【明确要求人工】
用户明确说人工客服、转人工、真人客服、找客服、人工呢、不要机器人等。

【商品信息缺失澄清】
用户问“这个多少钱”“这个怎么用”“这款怎么样”等商品指代问题，但当前消息和前文摘要中都没有明确商品卡片、商品名称或商品ID。

【其他问题】
无法归入以上分类，或问题不完整、不清楚、闲聊、无业务含义。

优先级规则：
1. 明确要求人工 优先于其它分类。
2. 红线转人工 优先于商品、售后、优惠、物流。
3. 敏感人群安全 优先于普通商品咨询。
4. 收到货后的破损、漏发、错发、质量问题归 售后取证处理。
5. 发货、到货、快递、物流归 物流订单查询。
6. 价格、规格、用法、味道、成分、保质期、新品、推荐、怎么选归 商品基础咨询。
7. 如果用户使用“这个/这款/它”等指代词，并且前文摘要里有商品卡片或商品ID，归 商品基础咨询。
8. 如果用户使用“这个/这款/它”等指代词，但前文摘要和当前消息都没有商品信息，归 商品信息缺失澄清。"""


def _keyword_label(current: str, conversation_text: str) -> str:
    current_text = str(current or "")
    full_text = str(conversation_text or "")
    if _contains(current_text, ("人工客服", "转人工", "真人客服", "找客服", "人工呢", "不要机器人")):
        return "明确要求人工"
    if _contains(current_text, ("假货", "投诉", "差评", "赔偿", "12315", "法律责任", "平台介入", "举报", "威胁")):
        return "红线转人工"
    if _contains(current_text, ("孕妇", "儿童", "宝宝", "老人", "敏感肌", "过敏", "伤口", "疾病", "哺乳期", "安全吗")):
        return "敏感人群安全"
    if _contains(current_text, ("破损", "漏液", "少发", "错发", "质量问题", "包装损坏", "坏了", "不能用", "退换货", "破了", "碎了")):
        return "售后取证处理"
    if _contains(current_text, ("发货", "到货", "快递", "物流", "运费", "配送", "订单状态", "单号", "到哪里", "什么时候到")):
        return "物流订单查询"
    if _contains(current_text, ("便宜", "优惠", "优惠券", "满减", "活动", "赠品", "返差价", "差价", "打折")):
        return "优惠活动咨询"
    if _contains(current_text, ("多少钱", "价格", "规格", "型号", "款式", "颜色", "味道", "香型", "怎么用", "用法", "成分", "保质期", "功效", "适合", "新品", "库存", "推荐", "怎么选", "区别")):
        return "商品基础咨询"
    if _contains(current_text, ("这个", "这款", "它")):
        if _contains(full_text, ("商品：", "商品ID：")):
            return "商品基础咨询"
        return "商品信息缺失澄清"
    return "其他问题"


def _contains(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _risk_flags_for_intent(intent: str) -> list[str]:
    if intent == HUMAN_ESCALATION_REDLINE:
        return ["redline"]
    if intent == EXPLICIT_HUMAN_REQUEST:
        return ["requires_human"]
    if intent == SENSITIVE_USER_SAFETY:
        return ["sensitive_user_safety"]
    if intent == AFTER_SALES_EVIDENCE_COLLECTION:
        return ["needs_evidence"]
    if intent == PROMOTION_POLICY:
        return ["no_private_discount"]
    if intent == LOGISTICS_ORDER_STATUS:
        return ["order_context_required"]
    return []


def _clean_label(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:text|json|JSON)?\s*", "", value)
    value = re.sub(r"\s*```$", "", value)
    value = value.strip().strip('"').strip("'").strip()
    for label in CHINESE_LABEL_TO_INTENT:
        if label in value:
            return label
    return value


def _stable_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
