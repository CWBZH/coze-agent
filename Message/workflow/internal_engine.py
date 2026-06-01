"""Rule-based internal workflow engine.

This backend is intentionally not the default runtime path. It provides a
deterministic classifier for future self-hosted workflow work without calling
LLMs, FastGPT, or embeddings.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict
from typing import Any, Iterable, Mapping

from .base import AIWorkflowEngine
from .active_version import ActiveVersionResolver
from .answer_generator import AnswerGenerationContext, answer_hash, answer_preview, classify_answer_error
from .conversation_context import ConversationContext, stable_hash
from .domain_policy import DomainPolicyResponder
from .guardrail import OutputGuardrail
from .intent_classifier import (
    AFTER_SALES_EVIDENCE_COLLECTION,
    ASK_PRODUCT_CLARIFICATION,
    EXPLICIT_HUMAN_REQUEST,
    FALLBACK,
    HUMAN_ESCALATION_REDLINE,
    LOGISTICS_ORDER_STATUS,
    LOGISTICS_POLICY,
    PRODUCT_BASIC,
    PROMOTION_POLICY,
    SENSITIVE_USER_SAFETY,
    IntentClassification,
    LLMIntentClassifier,
    validate_classification,
)
from .knowledge import KnowledgeHit, KnowledgeRetriever, ProductKnowledgeRetriever
from .prompt_builder import build_prompt_payload, format_conversation_text
from .private_trace import write_private_trace
from .rag_retriever import RAGRetriever
from .rag_types import RetrievalHit
from .types import ProductContext, WorkflowAction, WorkflowContext, WorkflowResult

INTERNAL_WORKFLOW_VERSION = "internal-v1"
PRODUCT_KNOWLEDGE_VERSION = "product_repository"
PRODUCT_CARD_ACK_REPLY = "亲亲，已看到这款商品，您可以继续问我价格、规格或用法哦。"
PRODUCT_ANSWER_SAFE_FALLBACK_REPLY = "这款商品的信息我先帮您确认一下，您可以先参考商品页面展示的规格、价格和说明，具体以页面和下单结算页为准。"
AFTER_SALES_ANSWER_SAFE_FALLBACK_REPLY = "亲，请先提供问题照片、外包装照片、订单信息和具体情况说明，客服会为您核实处理。"
SENSITIVE_ANSWER_SAFE_FALLBACK_REPLY = "亲，孕妇、儿童、敏感肌或过敏情况建议先查看成分和说明，必要时咨询专业人士或转人工确认。"
LOGISTICS_ANSWER_SAFE_FALLBACK_REPLY = "亲，发货和物流进度请以订单物流页为准，如需进一步核实可以转人工确认。"
PROMOTION_ANSWER_SAFE_FALLBACK_REPLY = "亲，优惠活动请以商品页面、活动页和结算页显示为准，暂不承诺额外优惠哦。"
PRODUCT_CLARIFICATION_REPLY = "请问您要咨询哪款商品呢？可以发一下商品卡片或商品名称，我帮您查看。"


class InternalWorkflowEngine(AIWorkflowEngine):
    _EXPLICIT_HUMAN_KEYWORDS = (
        "转人工",
        "人工客服",
        "找真人",
        "人工",
        "客服",
    )
    _REDLINE_KEYWORDS = (
        "假货",
        "诈骗",
        "投诉",
        "12315",
        "消协",
        "赔偿",
        "曝光",
        "媒体",
        "差评威胁",
        "差评",
        "平台投诉",
    )
    _EVIDENCE_KEYWORDS = (
        "破损",
        "破了",
        "碎了",
        "坏了",
        "漏了",
        "漏液",
        "少发",
        "缺件",
        "发错",
        "错发",
        "不是我买的",
        "质量问题",
        "包装损坏",
        "不能用",
        "退换货",
    )
    _LOGISTICS_KEYWORDS = (
        "为什么还没到",
        "快递到哪了",
        "怎么还没发货",
        "什么时候发货",
        "物流怎么不动",
        "什么时候到",
        "快递",
        "物流",
        "发货",
        "到货",
        "运费",
        "配送",
        "订单状态",
        "单号",
    )
    _PROMOTION_KEYWORDS = (
        "便宜点",
        "便宜",
        "优惠",
        "优惠券",
        "赠品",
        "包邮",
        "返差价",
        "满减",
        "活动",
        "差价",
        "打折",
    )
    _SENSITIVE_USER_KEYWORDS = (
        "孕妇",
        "儿童",
        "小孩",
        "宝宝",
        "老人",
        "过敏",
        "敏感肌",
        "伤口",
        "疾病",
        "哺乳期",
        "安全吗",
        "医生",
        "治疗",
        "药",
        "医疗",
    )
    _PRODUCT_BASIC_KEYWORDS = (
        "多少钱",
        "价格",
        "价钱",
        "什么规格",
        "规格",
        "型号",
        "款式",
        "颜色",
        "味道",
        "香型",
        "怎么用",
        "用法",
        "成分",
        "保质期",
        "功效",
        "适合什么肤质",
        "适合",
        "新品",
        "库存",
        "推荐",
        "怎么选",
        "区别",
    )
    _AFTER_SALES_PRIORITY_KEYWORDS = (
        "破损",
        "破了",
        "破碎",
        "碎了",
        "坏了",
        "漏了",
        "漏液",
        "少发",
        "缺件",
        "发错",
        "错发",
        "包装破",
        "包装损坏",
        "质量问题",
        "不能用",
        "退款",
        "退货",
        "退换货",
        "换货",
        "补发",
        "赔偿",
        "赔付",
        "给我退",
        "赶紧退",
        "怎么处理",
        "怎么办",
    )
    _AFTER_SALES_FOLLOWUP_TEXTS = (
        "?",
        "？",
        "啊",
        "呢",
        "哦",
        "嗯",
        "然后呢",
        "那怎么办",
        "怎么处理",
        "给我处理",
        "赶紧处理",
    )

    _EVIDENCE_REPLY = "亲，已收到您的反馈。请提供问题照片、外包装照片和具体情况说明，客服会为您核实处理。"
    _LOGISTICS_REPLY = "亲，具体物流状态请以订单物流页为准。若需要核实当前订单，我可以为您转人工处理。"
    _PROMOTION_REPLY = "亲，优惠、赠品和包邮以商品页面及结算页显示为准，暂不承诺额外优惠。"
    _SENSITIVE_USER_REPLY = "亲，孕妇、儿童、过敏或医疗相关情况建议先查看产品说明，必要时咨询专业人士或转人工确认。"

    _STAGE_TIMING_KEYS = (
        "context_build_ms",
        "history_load_ms",
        "product_context_ms",
        "keyword_classify_ms",
        "llm_classify_ms",
        "rag_query_build_ms",
        "embedding_ms",
        "vector_search_ms",
        "rag_total_ms",
        "prompt_build_ms",
        "llm_answer_ms",
        "guardrail_ms",
        "internal_total_ms",
    )

    def __init__(
        self,
        knowledge_retriever: KnowledgeRetriever | None = None,
        knowledge_repository: Any | None = None,
        intent_classifier: LLMIntentClassifier | None = None,
        output_guardrail: Any | None = None,
        sop_provider: Any | None = None,
        domain_policy_responder: Any | None = None,
        conversation_context_repository: Any | None = None,
        answer_generator: Any | None = None,
        rag_retriever: RAGRetriever | None = None,
        active_version_resolver: Any | None = None,
    ):
        self.knowledge_retriever = knowledge_retriever
        self.knowledge_repository = knowledge_repository
        self.intent_classifier = intent_classifier or _NullIntentClassifier()
        self.output_guardrail = output_guardrail if output_guardrail is not None else OutputGuardrail
        self.sop_provider = sop_provider
        self.domain_policy_responder = domain_policy_responder or DomainPolicyResponder()
        self.conversation_context_repository = conversation_context_repository
        self.answer_generator = answer_generator
        self.rag_retriever = rag_retriever
        self.active_version_resolver = active_version_resolver

    async def run(self, context: WorkflowContext) -> WorkflowResult:
        internal_started_at = time.perf_counter()
        context_started_at = time.perf_counter()
        content = str(context.content or "")
        write_private_trace(
            context.trace_id,
            "input",
            {
                "buyer_message": content,
                "history": list(context.history or []),
                "metadata": context.metadata if isinstance(context.metadata, dict) else {},
                "goods_context": context.goods_context,
                "shop_id": context.shop_id,
                "user_id": context.user_id,
                "buyer_id": context.buyer_id or context.customer_uid,
                "session_id": context.session_id,
            },
        )
        trace = self._safe_trace(content)
        trace["trace_id"] = context.trace_id
        trace["_internal_started_at"] = internal_started_at
        self._set_stage_timing_value(trace, "context_build_ms", self._elapsed_ms(context_started_at))
        history_started_at = time.perf_counter()
        conversation_context = self._load_conversation_context(context)
        trace = self._merge_conversation_trace(trace, conversation_context)
        self._attach_history(context, conversation_context)
        context.metadata = {
            **(context.metadata if isinstance(context.metadata, dict) else {}),
            "pending_human": bool(conversation_context.pending_human) if conversation_context else False,
        }
        self._set_stage_timing_value(trace, "history_load_ms", self._elapsed_ms(history_started_at))

        if conversation_context and conversation_context.pending_human:
            return self._finalize(
                WorkflowResult(
                    action=WorkflowAction.TRANSFER_HUMAN,
                    intent="pending_human_lock",
                    reason="pending_human_conversation",
                    risk_flags=["requires_human", "pending_human"],
                    trace=trace,
                ),
                context,
            )

        keyword_started_at = time.perf_counter()
        if self._matches(content, self._REDLINE_KEYWORDS):
            self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
            return self._finalize(
                self._domain_policy_or_default(
                    context,
                    content,
                    trace,
                    intent="human_escalation_redline",
                    domain="redline_escalation",
                    default=WorkflowResult(
                        action=WorkflowAction.TRANSFER_HUMAN,
                        intent="human_escalation_redline",
                        reason="redline_requires_human",
                        risk_flags=["redline"],
                        trace=trace,
                    ),
                ),
                context,
            )

        if self._matches(content, self._EXPLICIT_HUMAN_KEYWORDS):
            self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
            return self._finalize(
                WorkflowResult(
                action=WorkflowAction.TRANSFER_HUMAN,
                intent="explicit_human_request",
                reason="buyer_requested_human",
                risk_flags=["requires_human"],
                trace=trace,
                ),
                context,
            )

        product_started_at = time.perf_counter()
        product_context = self._resolve_product_context(context, conversation_context)
        trace = self._merge_product_context_trace(trace, product_context)
        context.metadata = {
            **(context.metadata if isinstance(context.metadata, dict) else {}),
            "product_context": asdict(product_context),
        }
        self._set_stage_timing_value(trace, "product_context_ms", self._elapsed_ms(product_started_at))
        trace["message_has_product_card"] = self._message_has_product_card(context)
        trace["message_type"] = str(context.message_type or "")

        if self._looks_like_after_sales_issue(context, content):
            self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
            return self._finalize(
                self._domain_policy_or_default(
                    context,
                    content,
                    trace,
                    intent="after_sales_evidence_collection",
                    domain="after_sales_evidence",
                    default=WorkflowResult(
                        action=WorkflowAction.REQUEST_EVIDENCE,
                        reply_text=self._EVIDENCE_REPLY,
                        intent="after_sales_evidence_collection",
                        reason="request_buyer_evidence",
                        risk_flags=["needs_evidence"],
                        trace=trace,
                    ),
                ),
                context,
            )

        if self._is_product_card_without_question(context, content):
            return self._finalize(self._product_card_ack_result(trace), context)

        if self._matches(content, self._LOGISTICS_KEYWORDS):
            self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
            return self._finalize(
                self._domain_policy_or_default(
                    context,
                    content,
                    trace,
                    intent="logistics_order_status",
                    domain="logistics_policy",
                    default=WorkflowResult(
                        action=WorkflowAction.REPLY,
                        reply_text=self._LOGISTICS_REPLY,
                        intent="logistics_order_status",
                        reason="order_status_requires_order_page_or_human",
                        risk_flags=["order_context_required"],
                        trace=trace,
                    ),
                ),
                context,
            )

        if self._matches(content, self._PROMOTION_KEYWORDS):
            self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
            return self._finalize(
                self._domain_policy_or_default(
                    context,
                    content,
                    trace,
                    intent="promotion_policy",
                    domain="promotion_policy",
                    default=WorkflowResult(
                        action=WorkflowAction.REPLY,
                        reply_text=self._PROMOTION_REPLY,
                        intent="promotion_policy",
                        reason="promotion_policy_requires_page_or_checkout",
                        risk_flags=["no_private_discount"],
                        trace=trace,
                    ),
                ),
                context,
            )

        if self._matches(content, self._SENSITIVE_USER_KEYWORDS):
            self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
            return self._finalize(
                self._domain_policy_or_default(
                    context,
                    content,
                    trace,
                    intent="sensitive_user_safety",
                    domain="sensitive_user_safety",
                    default=WorkflowResult(
                        action=WorkflowAction.REPLY,
                        reply_text=self._SENSITIVE_USER_REPLY,
                        intent="sensitive_user_safety",
                        reason="avoid_deterministic_safety_or_medical_claim",
                        risk_flags=["sensitive_user_safety"],
                        trace=trace,
                    ),
                ),
                context,
            )

        if self._matches(content, self._PRODUCT_BASIC_KEYWORDS):
            self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
            if self._requires_product_context(content) and product_context.status != "resolved":
                return self._finalize(self._product_clarification_result(trace), context)
            return self._finalize(self._handle_product_basic(context, content, trace), context)

        self._set_stage_timing_value(trace, "keyword_classify_ms", self._elapsed_ms(keyword_started_at))
        classify_started_at = time.perf_counter()
        classification = await self._classify_intent(context, content)
        self._set_stage_timing_value(trace, "llm_classify_ms", self._elapsed_ms(classify_started_at))
        return self._finalize(self._handle_classification(context, content, trace, classification), context)

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _set_stage_timing_value(trace: dict[str, object], key: str, value: int) -> None:
        timings = trace.setdefault("stage_timing", {})
        if not isinstance(timings, dict):
            timings = {}
            trace["stage_timing"] = timings
        safe_value = max(0, int(value))
        timings[key] = safe_value
        trace[key] = safe_value

    @classmethod
    def _ensure_stage_timing(cls, trace: dict[str, object]) -> None:
        timings = trace.setdefault("stage_timing", {})
        if not isinstance(timings, dict):
            timings = {}
            trace["stage_timing"] = timings
        for key in cls._STAGE_TIMING_KEYS:
            if key not in timings:
                timings[key] = int(trace.get(key) or 0)
            trace[key] = int(timings.get(key) or 0)

    async def _classify_intent(self, context: WorkflowContext, content: str) -> IntentClassification:
        metadata = self._classification_metadata(context)
        classify_context = getattr(self.intent_classifier, "classify_context", None)
        if callable(classify_context):
            classification = await classify_context(context)
        else:
            classification = await self.intent_classifier.classify(content, metadata)
        return validate_classification(classification, metadata)

    def _handle_classification(
        self,
        context: WorkflowContext,
        content: str,
        trace: dict[str, object],
        classification: IntentClassification,
    ) -> WorkflowResult:
        trace = {
            **trace,
            "intent_source": "llm",
            "intent_classifier_called": True,
            "intent_classifier_status": "ok",
            "llm_intent_called": self.intent_classifier.__class__.__name__ != "_NullIntentClassifier",
            "classifier_intent_raw": classification.intent,
            "normalized_intent": classification.intent,
            "classifier_intent": classification.intent,
            "classifier_domain": classification.domain or "",
            "classifier_confidence": round(float(classification.confidence), 3),
            "classifier_requires_rag": bool(classification.requires_rag),
            "classifier_requires_product_context": bool(classification.requires_product_context),
            "classifier_requires_order_context": bool(classification.requires_order_context),
            "classifier_requires_answer_generation": bool(classification.requires_answer_generation),
            "classifier_should_transfer_human": bool(classification.should_transfer_human),
            "classifier_should_request_evidence": bool(classification.should_request_evidence),
            "classifier_clarification_needed": bool(classification.clarification_needed),
        }
        if classification.should_transfer_human:
            intent = (
                classification.intent
                if classification.intent in {HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST}
                else HUMAN_ESCALATION_REDLINE
            )
            return WorkflowResult(
                action=WorkflowAction.TRANSFER_HUMAN,
                intent=intent,
                reason=classification.reason or "classifier_requested_human_transfer",
                risk_flags=self._merge_flags(classification.risk_flags, ["requires_human"]),
                trace=trace,
            )
        if classification.clarification_needed or classification.intent == ASK_PRODUCT_CLARIFICATION:
            return self._product_clarification_result(trace)
        if classification.intent == HUMAN_ESCALATION_REDLINE:
            domain_result = self._domain_policy_result(
                context,
                content,
                trace,
                classification.intent,
                "redline_escalation",
                include_missing=True,
            )
            if domain_result is not None:
                domain_result.risk_flags = self._merge_flags(domain_result.risk_flags, ["redline"])
                return domain_result
            return WorkflowResult(
                action=WorkflowAction.TRANSFER_HUMAN,
                intent="human_escalation_redline",
                reason=classification.reason or "classifier_redline_requires_human",
                risk_flags=self._merge_flags(classification.risk_flags, ["redline"]),
                trace=trace,
            )
        if classification.intent == EXPLICIT_HUMAN_REQUEST:
            return WorkflowResult(
                action=WorkflowAction.TRANSFER_HUMAN,
                intent="explicit_human_request",
                reason=classification.reason or "buyer_requested_human",
                risk_flags=self._merge_flags(classification.risk_flags, ["requires_human"]),
                trace=trace,
            )
        if classification.intent == PRODUCT_BASIC:
            product_context = self._product_context_from_metadata(context)
            if product_context.status != "resolved" and (
                classification.requires_product_context or self._requires_product_context(content)
            ):
                return self._product_clarification_result(trace)
            return self._handle_product_basic(context, content, trace)
        policy_domain = classification.domain or self._policy_domain_for_intent(classification.intent)
        if classification.should_request_evidence and not policy_domain:
            policy_domain = "after_sales_evidence"
        if policy_domain:
            domain_result = self._domain_policy_result(
                context,
                content,
                trace,
                classification.intent,
                policy_domain,
                include_missing=True,
            )
            if domain_result is not None:
                return domain_result
        if classification.intent == FALLBACK:
            generated = self._answer_generation_result(
                context=context,
                content=content,
                trace=trace,
                intent=FALLBACK,
                action_hint=WorkflowAction.REPLY,
                product_hits=[],
                sop_records=[],
                fallback_reason=classification.reason or "classifier_fallback_answer_generated",
            )
            if generated is not None:
                return generated
            return WorkflowResult(
                action=WorkflowAction.FALLBACK,
                intent="fallback",
                reason=classification.reason or "classifier_fallback",
                risk_flags=list(classification.risk_flags),
                trace=trace,
            )
        return WorkflowResult(
            action=WorkflowAction.TRANSFER_HUMAN,
            intent=classification.intent or "fallback",
            reason="unsupported_classifier_intent_fallback",
            risk_flags=self._merge_flags(classification.risk_flags, ["unsupported_intent"]),
            trace={
                **trace,
                "unsupported_intent_fallback": True,
                "unsupported_intent": classification.intent or "",
                "transfer_reason": "unsupported_classifier_intent",
            },
        )

    def _handle_product_basic(self, context: WorkflowContext, content: str, trace: dict[str, object]) -> WorkflowResult:
        product_context = self._product_context_from_metadata(context)
        query_started_at = time.perf_counter()
        query = self._build_product_query(context, content)
        self._set_stage_timing_value(trace, "rag_query_build_ms", self._elapsed_ms(query_started_at))
        rag_hits = self._retrieve_rag(context, "product_basic", "product_catalog", query, trace)
        if rag_hits:
            rag_trace = self._trace_with_rag(trace, rag_hits)
            generated = self._answer_generation_result(
                context=context,
                content=content,
                trace=rag_trace,
                intent="product_basic",
                action_hint=WorkflowAction.REPLY,
                product_hits=rag_hits,
                sop_records=[],
                fallback_reason="rag_answer_generated",
            )
            if generated is not None:
                generated.knowledge_refs = [self._rag_ref(hit) for hit in rag_hits]
                return generated
            return self._answer_generator_unavailable_result(
                intent="product_basic",
                trace=rag_trace,
                risk_flags=[],
                knowledge_refs=[self._rag_ref(hit) for hit in rag_hits],
            )

        hits = self._search_product_knowledge(context.shop_id, query)
        cache_stats = self._product_cache_stats()
        trace = {
            **trace,
            "hit_count": len(hits),
            "hit_domains": sorted({hit.domain for hit in hits}),
            "knowledge_source": self._knowledge_source(),
            "knowledge_hit_count": len(hits),
            "knowledge_version": PRODUCT_KNOWLEDGE_VERSION if hits else None,
            "product_cache_hit": cache_stats.get("product_cache_hit"),
            "product_cache_ttl_seconds": cache_stats.get("product_cache_ttl_seconds"),
        }

        if not hits:
            return WorkflowResult(
                action=WorkflowAction.REPLY if product_context.status != "resolved" else WorkflowAction.FALLBACK,
                reply_text=PRODUCT_CLARIFICATION_REPLY if product_context.status != "resolved" else "",
                intent="product_basic",
                reason="product_context_missing_required" if product_context.status != "resolved" else "product_knowledge_not_found",
                trace=trace,
            )

        generated = self._answer_generation_result(
            context=context,
            content=content,
            trace=trace,
            intent="product_basic",
            action_hint=WorkflowAction.REPLY,
            product_hits=hits,
            sop_records=[],
            fallback_reason="product_answer_generated",
        )
        if generated is not None:
            generated.knowledge_refs = [self._knowledge_ref(hit) for hit in hits]
            return generated

        return self._answer_generator_unavailable_result(
            intent="product_basic",
            trace=trace,
            risk_flags=[],
            knowledge_refs=[self._knowledge_ref(hit) for hit in hits],
        )

    def _product_clarification_result(self, trace: dict[str, object]) -> WorkflowResult:
        return WorkflowResult(
            action=WorkflowAction.REPLY,
            reply_text=PRODUCT_CLARIFICATION_REPLY,
            intent=ASK_PRODUCT_CLARIFICATION,
            reason="product_context_missing_required",
            risk_flags=["product_context_required"],
            trace={
                **trace,
                "selected_domain": "product_catalog",
                "selected_knowledge_base": "product_catalog",
                "product_context_status": "missing_required",
                "answer_generator_called": False,
                "answer_generation_status": "not_required",
            },
        )

    def _product_card_ack_result(self, trace: dict[str, object]) -> WorkflowResult:
        return WorkflowResult(
            action=WorkflowAction.REPLY,
            reply_text=PRODUCT_CARD_ACK_REPLY,
            intent="product_basic",
            reason="product_card_context_ack",
            trace={
                **trace,
                "selected_domain": "product_catalog",
                "selected_knowledge_base": "product_catalog",
                "answer_generator_present": self.answer_generator is not None,
                "answer_generator_type": self.answer_generator.__class__.__name__ if self.answer_generator is not None else "",
                "answer_generator_called": False,
                "answer_generation_status": "not_required",
                "answer_failure_policy": "not_required",
                "answer_fallback_reason": "",
                "answer_used_rag_hit_count": 0,
                "answer_used_history_count": int(trace.get("history_message_count") or 0),
                "sets_pending_human": False,
            },
        )

    def _message_has_product_card(self, context: WorkflowContext) -> bool:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        message_type = str(context.message_type or metadata.get("message_type") or "").strip().lower()
        if message_type in {"64", "product_card", "goods_card", "product"}:
            return True
        if any(str(metadata.get(key) or "").strip() for key in ("goods_id", "goodsID", "goodsId", "goods_name", "goodsName")):
            return True
        parsed = self._parse_product_anchor_text(str(context.content or ""))
        return bool(parsed.get("goods_id") or parsed.get("goods_name"))

    def _is_product_card_without_question(self, context: WorkflowContext, content: str) -> bool:
        if not self._message_has_product_card(context):
            return False
        text = str(content or "")
        if self._looks_like_after_sales_issue(context, text):
            return False
        question_markers = (
            "?",
            "？",
            "吗",
            "呢",
            "多少钱",
            "怎么用",
            "怎么",
            "用法",
            "有没有",
            "什么",
        )
        return not any(marker in text for marker in question_markers)

    def _looks_like_after_sales_issue(self, context: WorkflowContext, content: str) -> bool:
        text = str(content or "").strip()
        if self._matches(text, self._EVIDENCE_KEYWORDS) or self._matches(text, self._AFTER_SALES_PRIORITY_KEYWORDS):
            return True
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return False
        is_short_followup = (
            normalized in self._AFTER_SALES_FOLLOWUP_TEXTS
            or (len(normalized) <= 3 and all(ch in "?？！!。.~～" for ch in normalized))
        )
        if not is_short_followup:
            return False
        return self._recent_history_has_after_sales_issue(context)

    def _recent_history_has_after_sales_issue(self, context: WorkflowContext) -> bool:
        history = [item for item in list(context.history or []) if isinstance(item, Mapping)]
        for item in history[-8:]:
            text = str(item.get("content") or item.get("message") or item.get("text") or "")
            if self._matches(text, self._EVIDENCE_KEYWORDS) or self._matches(text, self._AFTER_SALES_PRIORITY_KEYWORDS):
                return True
        return False

    def _search_product_knowledge(self, shop_id: str, query: str) -> list[KnowledgeHit]:
        if not self.knowledge_retriever:
            if not self.knowledge_repository:
                return []
            loader = getattr(self.knowledge_repository, "load_shop_products", None)
            records = (
                loader(shop_id)
                if callable(loader)
                else self.knowledge_repository.load_records(shop_id=shop_id)
            )
            return ProductKnowledgeRetriever(records).search(shop_id=shop_id, domain="product_basic", query=query, limit=3)
        return self.knowledge_retriever.search(shop_id=shop_id, domain="product_basic", query=query, limit=3)

    def _resolve_product_context(
        self,
        context: WorkflowContext,
        conversation_context: ConversationContext | None,
    ) -> ProductContext:
        del conversation_context
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        direct = self._product_context_from_sources(context.goods_context, metadata, context.shop_id)
        if direct.status == "resolved":
            return direct

        content = str(context.content or "")
        history_match = self._resolve_product_from_history(context)
        if history_match.status == "resolved":
            return history_match

        repository_match = self._resolve_product_from_repository(context.shop_id, content)
        if repository_match.status == "resolved":
            return repository_match
        retriever_match = self._resolve_product_from_knowledge_retriever(context.shop_id, content)
        if retriever_match.status == "resolved":
            return retriever_match

        if self._requires_product_context(content):
            return ProductContext(shop_id=context.shop_id, status="missing_required", source="none")
        return ProductContext(shop_id=context.shop_id, status="none", source="none")

    def _product_context_from_sources(self, goods_context: Any, metadata: Mapping[str, Any], shop_id: str) -> ProductContext:
        candidates: list[tuple[str, Mapping[str, Any]]] = []
        if isinstance(goods_context, Mapping):
            candidates.append(("message_card", goods_context))
        if isinstance(metadata.get("product_context"), Mapping):
            candidates.append(("history", metadata["product_context"]))
        if isinstance(metadata, Mapping):
            candidates.append(("message_metadata", metadata))
        raw_data = metadata.get("raw_data") or metadata.get("raw_message") or metadata.get("product_card_payload")
        parsed_raw = self._parse_raw_product_payload(raw_data)
        if parsed_raw:
            candidates.insert(0, ("raw_data", parsed_raw))

        for source, candidate in candidates:
            goods_id = self._first_candidate_value(candidate, ("goods_id", "goodsID", "goodsId"))
            product_name = self._first_candidate_value(candidate, ("product_name", "goods_name", "goodsName", "title"))
            if goods_id or product_name:
                resolved_source = str(candidate.get("source") or source)
                inherited = bool(candidate.get("inherited")) or resolved_source in {"history", "memory_cache"}
                age_messages = int(candidate.get("age_messages") or candidate.get("product_context_age_messages") or 0)
                return ProductContext(
                    goods_id=goods_id,
                    product_name=product_name,
                    shop_id=str(shop_id or candidate.get("shop_id") or ""),
                    source=resolved_source,
                    confidence=1.0 if goods_id else 0.82,
                    candidates_summary=self._candidate_summary(goods_id, product_name, resolved_source),
                    status="resolved",
                    inherited=inherited,
                    age_messages=age_messages,
                )
        return ProductContext(shop_id=str(shop_id or ""), status="none", source="none")

    def _resolve_product_from_knowledge_retriever(self, shop_id: str, content: str) -> ProductContext:
        if not self.knowledge_retriever or not str(content or "").strip():
            return ProductContext(shop_id=str(shop_id or ""), status="none", source="none")
        search = getattr(self.knowledge_retriever, "search", None)
        if not callable(search):
            return ProductContext(shop_id=str(shop_id or ""), status="none", source="none")
        try:
            hits = list(search(shop_id=shop_id, domain="product_catalog", query=content, limit=3))
        except Exception:
            hits = []
        if len(hits) == 1:
            hit = hits[0]
            metadata = hit.metadata if isinstance(hit.metadata, Mapping) else {}
            fields = metadata.get("fields") if isinstance(metadata.get("fields"), Mapping) else {}
            goods_id = str(metadata.get("goods_id") or fields.get("goods_id") or "")
            product_name = str(hit.title or fields.get("goods_name") or "")
            return ProductContext(
                goods_id=goods_id,
                product_name=product_name,
                shop_id=str(shop_id or ""),
                source="product_repository",
                confidence=0.82,
                candidates_summary=self._candidate_summary(goods_id, product_name, "product_repository"),
                status="resolved",
            )
        if len(hits) > 1:
            return ProductContext(
                shop_id=str(shop_id or ""),
                source="product_repository",
                confidence=0.4,
                candidates_summary=[
                    self._safe_product_candidate(
                        {
                            "goods_id": (hit.metadata or {}).get("goods_id") if isinstance(hit.metadata, Mapping) else "",
                            "product_name": hit.title,
                        }
                    )
                    for hit in hits[:3]
                ],
                status="ambiguous",
            )
        return ProductContext(shop_id=str(shop_id or ""), status="none", source="none")

    def _resolve_product_from_repository(self, shop_id: str, content: str) -> ProductContext:
        records = self._load_product_records(shop_id)
        matches: list[dict[str, Any]] = []
        for record in records:
            goods_id = str(self._record_value(record, "goods_id") or "").strip()
            goods_name = str(self._record_value(record, "goods_name") or self._record_value(record, "product_name") or "").strip()
            if goods_id and goods_id in content or goods_name and goods_name in content:
                matches.append({"goods_id": goods_id, "product_name": goods_name})
        if len(matches) == 1:
            match = matches[0]
            return ProductContext(
                goods_id=match["goods_id"],
                product_name=match["product_name"],
                shop_id=str(shop_id or ""),
                source="product_repository",
                confidence=0.9,
                candidates_summary=self._candidate_summary(match["goods_id"], match["product_name"], "product_repository"),
                status="resolved",
            )
        if len(matches) > 1:
            return ProductContext(
                shop_id=str(shop_id or ""),
                source="product_repository",
                confidence=0.4,
                candidates_summary=[self._safe_product_candidate(item) for item in matches[:3]],
                status="ambiguous",
            )
        return ProductContext(shop_id=str(shop_id or ""), status="none", source="none")

    def _resolve_product_from_history(self, context: WorkflowContext) -> ProductContext:
        age_messages = 0
        for item in reversed(list(context.history or [])):
            age_messages += 1
            if not isinstance(item, Mapping):
                continue
            product_context = item.get("product_context")
            if isinstance(product_context, Mapping):
                resolved = self._product_context_from_sources(product_context, {}, context.shop_id)
                if resolved.status == "resolved":
                    return ProductContext(
                        goods_id=resolved.goods_id,
                        product_name=resolved.product_name,
                        shop_id=resolved.shop_id,
                        source="history",
                        confidence=0.75,
                        candidates_summary=resolved.candidates_summary,
                        status="resolved",
                        inherited=True,
                        age_messages=age_messages,
                    )
            resolved = self._product_context_from_sources(item, {}, context.shop_id)
            if resolved.status == "resolved":
                return ProductContext(
                    goods_id=resolved.goods_id,
                    product_name=resolved.product_name,
                    shop_id=resolved.shop_id,
                    source="history",
                    confidence=0.75,
                    candidates_summary=resolved.candidates_summary,
                    status="resolved",
                    inherited=True,
                    age_messages=age_messages,
                )
            parsed_raw = self._parse_raw_product_payload(item.get("raw_data") or item.get("raw_message"))
            if parsed_raw:
                resolved = self._product_context_from_sources(parsed_raw, {}, context.shop_id)
                if resolved.status == "resolved":
                    return ProductContext(
                        goods_id=resolved.goods_id,
                        product_name=resolved.product_name,
                        shop_id=resolved.shop_id,
                        source="history",
                        confidence=0.75,
                        candidates_summary=resolved.candidates_summary,
                        status="resolved",
                        inherited=True,
                        age_messages=age_messages,
                    )
            parsed_text = self._parse_product_anchor_text(str(item.get("content") or ""))
            if parsed_text:
                resolved = self._product_context_from_sources(parsed_text, {}, context.shop_id)
                if resolved.status == "resolved":
                    return ProductContext(
                        goods_id=resolved.goods_id,
                        product_name=resolved.product_name,
                        shop_id=resolved.shop_id,
                        source="history",
                        confidence=0.72,
                        candidates_summary=resolved.candidates_summary,
                        status="resolved",
                        inherited=True,
                        age_messages=age_messages,
                    )
        return ProductContext(shop_id=str(context.shop_id or ""), status="none", source="none")

    def _load_product_records(self, shop_id: str) -> list[Any]:
        if not self.knowledge_repository:
            return []
        try:
            loader = getattr(self.knowledge_repository, "load_shop_products", None)
            if callable(loader):
                return list(loader(shop_id))
            load_records = getattr(self.knowledge_repository, "load_records", None)
            if callable(load_records):
                return list(load_records(shop_id=shop_id))
        except Exception:
            return []
        return []

    @staticmethod
    def _parse_raw_product_payload(raw_data: Any) -> dict[str, Any]:
        if not raw_data:
            return {}
        value = raw_data
        if isinstance(raw_data, str):
            try:
                value = json.loads(raw_data)
            except (TypeError, ValueError):
                return {}
        if not isinstance(value, Mapping):
            return {}
        info = value.get("info") if isinstance(value.get("info"), Mapping) else {}
        data = info.get("data") if isinstance(info.get("data"), Mapping) else {}
        merged = {**info, **data}
        result: dict[str, Any] = {}
        for source, target in (
            ("goodsID", "goods_id"),
            ("goodsId", "goods_id"),
            ("goods_id", "goods_id"),
            ("goodsName", "goods_name"),
            ("goods_name", "goods_name"),
            ("goodsPrice", "goods_price"),
            ("goodsThumbUrl", "goods_thumb_url"),
            ("linkUrl", "link_url"),
            ("spec", "spec"),
        ):
            if merged.get(source):
                result[target] = merged.get(source)
        return result

    @staticmethod
    def _parse_product_anchor_text(content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {}
        result: dict[str, Any] = {}
        goods_id_match = re.search(
            r"(?:goods[_\s-]*id|商品\s*ID|商品ID|goodsID|goodsId)\s*[:：=]\s*([A-Za-z0-9_-]{4,})",
            text,
            flags=re.IGNORECASE,
        )
        if goods_id_match:
            result["goods_id"] = goods_id_match.group(1).strip()
        name_match = re.search(
            r"(?:商品|商品名称|goods[_\s-]*name|goodsName|Product)\s*[:：=]\s*([^，,。;\n\r]{2,80})",
            text,
            flags=re.IGNORECASE,
        )
        if name_match:
            result["goods_name"] = name_match.group(1).strip()
        price_match = re.search(r"(?:价格|价钱|goodsPrice|Price)\s*[:：=]\s*([^，,。;\n\r]{1,40})", text, flags=re.IGNORECASE)
        if price_match:
            result["goods_price"] = price_match.group(1).strip()
        spec_match = re.search(r"(?:规格|spec)\s*[:：=]\s*([^，,。;\n\r]{1,80})", text, flags=re.IGNORECASE)
        if spec_match:
            result["spec"] = spec_match.group(1).strip()
        return result

    @staticmethod
    def _first_candidate_value(candidate: Mapping[str, Any], keys: Iterable[str]) -> str:
        for key in keys:
            value = str(candidate.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _candidate_summary(goods_id: str, product_name: str, source: str) -> list[dict[str, Any]]:
        return [
            {
                "goods_id_hash": stable_hash(goods_id) if goods_id else "",
                "product_name_hash": stable_hash(product_name) if product_name else "",
                "source": source,
            }
        ]

    @staticmethod
    def _safe_product_candidate(item: Mapping[str, Any]) -> dict[str, Any]:
        goods_id = str(item.get("goods_id") or "")
        product_name = str(item.get("product_name") or item.get("goods_name") or "")
        return {
            "goods_id_hash": stable_hash(goods_id) if goods_id else "",
            "product_name_hash": stable_hash(product_name) if product_name else "",
        }

    @staticmethod
    def _requires_product_context(content: str) -> bool:
        text = str(content or "")
        product_question = any(
            keyword in text
            for keyword in (
                "多少钱",
                "价格",
                "价钱",
                "规格",
                "型号",
                "款式",
                "颜色",
                "味道",
                "香型",
                "怎么用",
                "用法",
                "成分",
                "保质期",
                "功效",
                "适合",
                "新品",
                "库存",
                "推荐",
                "怎么选",
                "区别",
            )
        )
        product_question = product_question or any(
            keyword in text
            for keyword in ("这个", "这款", "它", "多少钱", "价格", "规格", "怎么用", "用法", "成分", "保质期")
        )
        return bool(product_question)

    @staticmethod
    def _merge_product_context_trace(trace: dict[str, object], product_context: ProductContext) -> dict[str, object]:
        return {
            **trace,
            "product_context_status": product_context.status,
            "current_product_id_hash": stable_hash(product_context.goods_id) if product_context.goods_id else "",
            "current_product_name_hash": stable_hash(product_context.product_name) if product_context.product_name else "",
            "product_context_source": product_context.source,
            "product_anchor_source": product_context.source if product_context.status == "resolved" else "none",
            "product_context_candidate_count": len(product_context.candidates_summary),
            "product_context_inherited": bool(product_context.inherited),
            "product_context_age_messages": int(product_context.age_messages or 0),
        }

    @staticmethod
    def _product_context_from_metadata(context: WorkflowContext) -> ProductContext:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        value = metadata.get("product_context")
        if isinstance(value, Mapping):
            return ProductContext(
                goods_id=str(value.get("goods_id") or ""),
                product_name=str(value.get("product_name") or value.get("goods_name") or ""),
                shop_id=str(value.get("shop_id") or context.shop_id or ""),
                source=str(value.get("source") or "none"),
                confidence=float(value.get("confidence") or 0.0),
                candidates_summary=list(value.get("candidates_summary") or []),
                status=str(value.get("status") or "none"),
                inherited=bool(value.get("inherited")),
                age_messages=int(value.get("age_messages") or value.get("product_context_age_messages") or 0),
            )
        return ProductContext(shop_id=str(context.shop_id or ""), status="none", source="none")

    def _knowledge_source(self) -> str:
        if self.knowledge_retriever:
            return "retriever"
        if self.knowledge_repository:
            return "repository"
        return "none"

    def _product_cache_stats(self) -> dict[str, object]:
        stats = self._read_optional_stats(self.knowledge_repository) or self._read_optional_stats(self.knowledge_retriever)
        if stats is None:
            return {"product_cache_hit": None, "product_cache_ttl_seconds": None}
        cache_hit = self._stats_value(
            stats,
            ("product_cache_hit", "cache_hit", "hit"),
        )
        ttl_seconds = self._stats_value(
            stats,
            ("product_cache_ttl_seconds", "cache_ttl_seconds", "ttl_seconds", "ttl"),
        )
        return {
            "product_cache_hit": self._optional_bool(cache_hit),
            "product_cache_ttl_seconds": self._optional_float(ttl_seconds),
        }

    @staticmethod
    def _read_optional_stats(source: Any) -> Any | None:
        if source is None:
            return None
        getter = getattr(source, "get_last_stats", None)
        if callable(getter):
            return getter()
        for attr_name in ("last_stats", "stats", "cache_stats", "last_cache_stats"):
            if hasattr(source, attr_name):
                return getattr(source, attr_name)
        return None

    @staticmethod
    def _stats_value(stats: Any, keys: Iterable[str]) -> object:
        for key in keys:
            if isinstance(stats, dict) and key in stats:
                return stats.get(key)
            if hasattr(stats, key):
                return getattr(stats, key)
        return None

    @staticmethod
    def _optional_bool(value: object) -> bool | None:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "hit"}:
            return True
        if normalized in {"0", "false", "no", "miss"}:
            return False
        return None

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_product_query(self, context: WorkflowContext, content: str) -> str:
        del content
        return format_conversation_text(context)

    def _goods_context_terms(self, goods_context: Any) -> list[str]:
        if not goods_context:
            return []
        if isinstance(goods_context, dict):
            return [
                str(goods_context.get(key) or "")
                for key in ("goods_name", "goods_id", "product_name", "title")
                if goods_context.get(key)
            ]
        return [str(goods_context)]

    def _render_product_reply(self, content: str, hit: KnowledgeHit) -> str:
        fields = hit.metadata.get("fields") if isinstance(hit.metadata, dict) else {}
        fields = fields if isinstance(fields, dict) else {}

        if self._matches(content, ("多少钱", "价格")):
            price = self._field(fields, "price")
            if price:
                return f"这款商品页面参考价为 {price}，实际价格请以商品页面和结算页显示为准。"
            return "这款商品价格请以商品页面和结算页显示为准。"

        if self._matches(content, ("规格", "什么规格")):
            value = self._first_field(fields, ("specifications", "sku_summary"))
            if value:
                return f"这款商品规格信息：{value}。具体以商品页面为准。"
            return "这款商品规格请以商品页面展示为准。"

        if self._matches(content, ("怎么用", "用法", "使用")):
            value = self._field(fields, "usage_method")
            if value:
                return f"用法参考：{value}。如有特殊情况可转人工确认。"
            return "这款商品用法请以商品页面说明为准，如需确认可转人工。"

        if self._matches(content, ("成分",)):
            value = self._field(fields, "ingredients")
            if value:
                return f"成分信息：{value}。具体以商品页面说明为准。"
            return "这款商品成分请以商品页面说明为准。"

        if self._matches(content, ("保质期", "多久")):
            value = self._field(fields, "shelf_life")
            if value:
                return f"保质期信息：{value}。具体以商品包装或商品页面说明为准。"
            return "这款商品保质期请以商品包装或商品页面说明为准。"

        warning = self._field(fields, "warnings")
        if warning:
            return f"商品注意事项：{warning}。具体以商品页面说明为准。"
        summary = self._first_field(
            fields,
            ("usage_method", "specifications", "sku_summary", "ingredients", "shelf_life", "manual_notes"),
        )
        if summary:
            return f"商品信息参考：{summary}。具体以商品页面说明为准。"
        return "这款商品信息请以商品页面说明为准，如需进一步确认可转人工。"

    @staticmethod
    def _knowledge_ref(hit: KnowledgeHit) -> dict[str, object]:
        metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
        return {
            "source": hit.source,
            "domain": hit.domain,
            "title": hit.title,
            "score": round(hit.score, 3),
            "metadata": {"goods_id": metadata.get("goods_id") or ""},
        }

    def _retrieve_rag(
        self,
        context: WorkflowContext,
        intent: str,
        domain: str,
        query: str,
        trace: dict[str, object],
    ) -> list[RetrievalHit]:
        retrieval_started_at = time.perf_counter()
        self._attach_active_version_filters(context, intent, domain, trace)
        if self.rag_retriever is None:
            trace.update(
                {
                    "rag_enabled": False,
                    "rag_status": "disabled",
                    "rag_hit_count": 0,
                    "selected_domain": domain,
                    "selected_knowledge_base": domain,
                    "rag_query_source": "conversation_text",
                    "question_optimization_used": False,
                    "retrieval_mode": "hybrid",
                    "semantic_weight": 0.5,
                    "fulltext_weight": 0.5,
                    "rrf_used": True,
                    "rerank_used": False,
                }
            )
            self._set_stage_timing_value(trace, "embedding_ms", 0)
            self._set_stage_timing_value(trace, "vector_search_ms", 0)
            self._set_stage_timing_value(trace, "rag_total_ms", self._elapsed_ms(retrieval_started_at))
            return []
        retrieve = getattr(self.rag_retriever, "retrieve", None)
        if not callable(retrieve):
            trace.update(
                {
                    "rag_enabled": False,
                    "rag_status": "disabled",
                    "rag_hit_count": 0,
                    "selected_domain": domain,
                    "selected_knowledge_base": domain,
                    "rag_query_source": "conversation_text",
                    "question_optimization_used": False,
                    "retrieval_mode": "hybrid",
                    "semantic_weight": 0.5,
                    "fulltext_weight": 0.5,
                    "rrf_used": True,
                    "rerank_used": False,
                }
            )
            self._set_stage_timing_value(trace, "embedding_ms", 0)
            self._set_stage_timing_value(trace, "vector_search_ms", 0)
            self._set_stage_timing_value(trace, "rag_total_ms", self._elapsed_ms(retrieval_started_at))
            return []
        try:
            hits = list(retrieve(context, intent, domain, query, top_k=3))
        except Exception:
            hits = []
        write_private_trace(
            context.trace_id,
            "rag",
            {
                "intent": intent,
                "domain": domain,
                "query": query,
                "top_k": 3,
                "hits": [self._private_hit(hit) for hit in hits[:3]],
            },
        )
        stats = self._read_optional_stats(self.rag_retriever) or {}
        self._set_stage_timing_value(trace, "embedding_ms", int(self._stats_value(stats, ("embedding_ms",)) or 0))
        self._set_stage_timing_value(trace, "vector_search_ms", int(self._stats_value(stats, ("vector_search_ms", "search_ms")) or 0))
        self._set_stage_timing_value(trace, "rag_total_ms", int(self._stats_value(stats, ("rag_total_ms",)) or self._elapsed_ms(retrieval_started_at)))
        self._merge_rag_stats(trace, stats, hits)
        trace.update(
            {
                "selected_domain": domain,
                "selected_knowledge_base": domain,
                "rag_top_k": 3,
                "rag_query_source": "conversation_text",
                "question_optimization_used": False,
                "retrieval_mode": "hybrid",
                "semantic_weight": 0.5,
                "fulltext_weight": 0.5,
                "rrf_used": True,
                "rerank_used": False,
            }
        )
        if domain in {"product_catalog", "product_basic"}:
            product_context = self._product_context_from_metadata(context)
            if not trace.get("retrieval_mode"):
                trace["retrieval_mode"] = str(self._stats_value(stats, ("retrieval_mode",)) or "hybrid")
            if not trace.get("product_anchor_source"):
                trace["product_anchor_source"] = product_context.source if product_context.status == "resolved" else "none"
            if not trace.get("exact_hit_count"):
                trace["exact_hit_count"] = int(self._stats_value(stats, ("exact_hit_count",)) or (1 if product_context.goods_id and hits else 0))
            if not trace.get("semantic_hit_count"):
                trace["semantic_hit_count"] = int(self._stats_value(stats, ("semantic_hit_count",)) or len(hits))
            if not trace.get("hybrid_merged_count"):
                trace["hybrid_merged_count"] = int(self._stats_value(stats, ("hybrid_merged_count",)) or len(hits))
            if not trace.get("top_hit_source"):
                trace["top_hit_source"] = str(self._stats_value(stats, ("top_hit_source",)) or ("exact" if product_context.goods_id and hits else ""))
            if not trace.get("top_hit_goods_id_hash"):
                trace["top_hit_goods_id_hash"] = str(self._stats_value(stats, ("top_hit_goods_id_hash",)) or (stable_hash(product_context.goods_id) if product_context.goods_id and hits else ""))
        return hits

    def _attach_active_version_filters(
        self,
        context: WorkflowContext,
        intent: str,
        domain: str,
        trace: dict[str, object],
    ) -> None:
        if not isinstance(context.metadata, dict):
            context.metadata = {}
        context.metadata.pop("active_rag_filters", None)
        resolver = self.active_version_resolver
        if resolver is None:
            trace.update(
                {
                    "active_version_resolved": False,
                    "active_version_fallback": False,
                    "active_version_missing_reason": "resolver_not_configured",
                }
            )
            return

        product_context = self._product_context_from_metadata(context)
        source_type = "product" if domain in {"product_catalog", "product_basic"} else "sop"
        goods_id = product_context.goods_id if source_type == "product" else ""
        try:
            resolve = getattr(resolver, "resolve_rag_filters", None)
            if callable(resolve):
                active = resolve(
                    shop_id=context.shop_id,
                    intent=intent,
                    domain=domain,
                    source_type=source_type,
                    goods_id=goods_id,
                )
            else:
                active = resolver.get_active_version(
                    context.shop_id,
                    source_type=source_type,
                    domain="product_catalog" if source_type == "product" else domain,
                    source_id=goods_id if source_type == "product" else None,
                )
        except Exception as exc:  # noqa: BLE001 - active lookup must not block legacy RAG fallback.
            trace.update(
                {
                    "active_version_resolved": False,
                    "active_version_fallback": True,
                    "active_version_missing_reason": f"resolver_error:{exc.__class__.__name__}",
                    "active_source_type": source_type,
                    "active_source_id": goods_id,
                    "active_domain": domain,
                }
            )
            return

        active_dict = self._active_version_to_dict(active)
        trace.update(
            {
                "active_version_resolved": bool(active_dict.get("resolved")),
                "active_version_id": active_dict.get("version_id"),
                "active_version": str(active_dict.get("version") or ""),
                "active_source_type": str(active_dict.get("source_type") or source_type),
                "active_source_id": str(active_dict.get("source_id") or goods_id),
                "active_domain": str(active_dict.get("domain") or domain),
                "active_version_fallback": bool(active_dict.get("fallback")),
                "active_version_missing_reason": str(active_dict.get("missing_reason") or ""),
            }
        )
        filters = active_dict.get("filters")
        if bool(active_dict.get("resolved")) and isinstance(filters, dict) and filters:
            context.metadata["active_rag_filters"] = {
                str(key): str(value)
                for key, value in filters.items()
                if str(value or "").strip()
            }

    @staticmethod
    def _active_version_to_dict(active: Any) -> dict[str, Any]:
        if isinstance(active, dict):
            return dict(active)
        return {
            "resolved": bool(getattr(active, "resolved", False)),
            "version_id": getattr(active, "version_id", None),
            "version": getattr(active, "version", ""),
            "source_type": getattr(active, "source_type", ""),
            "source_id": getattr(active, "source_id", ""),
            "domain": getattr(active, "domain", ""),
            "filters": getattr(active, "filters", {}),
            "fallback": bool(getattr(active, "fallback", False)),
            "missing_reason": getattr(active, "missing_reason", ""),
        }

    def _merge_rag_stats(self, trace: dict[str, object], stats: Any, hits: list[RetrievalHit]) -> None:
        domains = sorted({hit.domain for hit in hits})
        trace.update(
            {
                "rag_enabled": True,
                "rag_status": str(self._stats_value(stats, ("rag_status", "status")) or ("hit" if hits else "empty")),
                "rag_hit_count": int(self._stats_value(stats, ("rag_hit_count", "hit_count")) or len(hits)),
                "rag_domains": list(self._stats_value(stats, ("rag_domains", "domains")) or domains),
                "rag_top_score": self._optional_float(self._stats_value(stats, ("rag_top_score", "top_score"))) or (round(float(hits[0].score), 4) if hits else 0.0),
                "rag_version_pinned": bool(self._stats_value(stats, ("rag_version_pinned",)) or False),
                "rag_hit_versions": list(self._stats_value(stats, ("rag_hit_versions",)) or self._rag_versions(hits)),
                "rag_hit_version_ids": list(self._stats_value(stats, ("rag_hit_version_ids",)) or self._rag_version_ids(hits)),
                "rag_hit_content_hashes": list(self._stats_value(stats, ("rag_hit_content_hashes",)) or self._rag_content_hashes(hits)),
                "rag_hit_source_types": list(self._stats_value(stats, ("rag_hit_source_types",)) or self._rag_source_types(hits)),
                "rag_hit_source_ids_hash": list(self._stats_value(stats, ("rag_hit_source_ids_hash",)) or self._rag_source_id_hashes(hits)),
                "rag_hit_shop_ids_hash": list(self._stats_value(stats, ("rag_hit_shop_ids_hash",)) or self._rag_shop_id_hashes(hits)),
                "vector_store": str(self._stats_value(stats, ("vector_store",)) or ""),
                "embedding_model": str(self._stats_value(stats, ("embedding_model",)) or ""),
                "embedding_latency_ms": int(self._stats_value(stats, ("embedding_latency_ms", "embedding_ms")) or 0),
                "pgvector_query_latency_ms": int(self._stats_value(stats, ("pgvector_query_latency_ms", "vector_search_ms", "search_ms")) or 0),
                "rag_total_latency_ms": int(self._stats_value(stats, ("rag_total_latency_ms", "rag_total_ms")) or 0),
                "retrieval_source": str(self._stats_value(stats, ("retrieval_source",)) or ""),
                "retrieval_mode": str(self._stats_value(stats, ("retrieval_mode",)) or "hybrid"),
                "rag_query_source": "conversation_text",
                "question_optimization_used": False,
                "semantic_weight": 0.5,
                "fulltext_weight": 0.5,
                "rrf_used": True,
                "rerank_used": False,
                "exact_hit_count": int(self._stats_value(stats, ("exact_hit_count",)) or 0),
                "keyword_hit_count": int(self._stats_value(stats, ("keyword_hit_count",)) or 0),
                "fulltext_hit_count": int(self._stats_value(stats, ("fulltext_hit_count", "keyword_hit_count")) or 0),
                "semantic_hit_count": int(self._stats_value(stats, ("semantic_hit_count",)) or 0),
                "hybrid_merged_count": int(self._stats_value(stats, ("hybrid_merged_count",)) or 0),
                "top_hit_source": str(self._stats_value(stats, ("top_hit_source",)) or ""),
                "top_hit_goods_id_hash": str(self._stats_value(stats, ("top_hit_goods_id_hash",)) or ""),
            }
        )

    def _trace_with_rag(self, trace: dict[str, object], hits: list[RetrievalHit]) -> dict[str, object]:
        first_version = hits[0].version if hits else None
        return {
            **trace,
            "knowledge_source": "rag",
            "knowledge_hit_count": len(hits),
            "knowledge_version": first_version,
            "selected_domain": hits[0].domain if hits else trace.get("selected_domain", ""),
            "selected_knowledge_base": hits[0].domain if hits else trace.get("selected_knowledge_base", ""),
            "rag_enabled": True,
            "rag_hit_count": len(hits),
            "rag_domains": sorted({hit.domain for hit in hits}),
            "rag_top_score": round(float(hits[0].score), 4) if hits else 0.0,
            "rag_hit_versions": self._rag_versions(hits),
            "rag_hit_version_ids": self._rag_version_ids(hits),
            "rag_hit_content_hashes": self._rag_content_hashes(hits),
            "rag_hit_source_types": self._rag_source_types(hits),
            "rag_hit_source_ids_hash": self._rag_source_id_hashes(hits),
            "rag_hit_shop_ids_hash": self._rag_shop_id_hashes(hits),
            "retrieved_chunks": [self._private_hit(hit) for hit in hits[:3]],
            "rag_top_k": 3,
        }

    @staticmethod
    def _rag_ref(hit: RetrievalHit) -> dict[str, object]:
        return {
            "source": "rag",
            "domain": hit.domain,
            "title": hit.title,
            "score": round(hit.score, 3),
            "metadata": {
                "source_type": hit.source_type,
                "source_id_hash": hashlib.sha256(str(hit.source_id or "").encode("utf-8")).hexdigest()[:16] if hit.source_id else "",
                "content_hash": hit.content_hash,
                "version": hit.version,
            },
        }

    @staticmethod
    def _rag_record(hit: RetrievalHit) -> dict[str, object]:
        return {
            "id": hit.chunk_id,
            "domain": hit.domain,
            "title": hit.title,
            "approved_answer": hit.content_summary,
            "version": hit.version,
            "content_hash": hit.content_hash,
            "source": "rag",
        }

    def _render_rag_policy_reply(self, intent: str, domain: str) -> str:
        if domain == "logistics_policy":
            return self._LOGISTICS_REPLY
        if domain == "after_sales_evidence":
            return self._EVIDENCE_REPLY
        if domain == "promotion_policy":
            return self._PROMOTION_REPLY
        if domain == "sensitive_user_safety":
            return self._SENSITIVE_USER_REPLY
        return "已为您记录当前问题，如需进一步处理可转人工客服核实。"

    @staticmethod
    def _action_hint_for_policy_intent(intent: str) -> WorkflowAction:
        if intent in {AFTER_SALES_EVIDENCE_COLLECTION, "after_sales_evidence_collection"}:
            return WorkflowAction.REQUEST_EVIDENCE
        if intent in {HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST, "human_escalation_redline", "explicit_human_request"}:
            return WorkflowAction.TRANSFER_HUMAN
        return WorkflowAction.REPLY

    @staticmethod
    def _risk_flags_for_policy_intent(intent: str) -> list[str]:
        if intent in {AFTER_SALES_EVIDENCE_COLLECTION, "after_sales_evidence_collection"}:
            return ["needs_evidence"]
        if intent in {LOGISTICS_ORDER_STATUS, LOGISTICS_POLICY, "logistics_order_status", "logistics_policy"}:
            return ["order_context_required"]
        if intent in {PROMOTION_POLICY, "promotion_policy"}:
            return ["no_private_discount"]
        if intent in {SENSITIVE_USER_SAFETY, "sensitive_user_safety"}:
            return ["sensitive_user_safety"]
        return []

    @staticmethod
    def _field(fields: dict[str, Any], key: str) -> str:
        return str(fields.get(key) or "").strip()

    def _first_field(self, fields: dict[str, Any], keys: Iterable[str]) -> str:
        for key in keys:
            value = self._field(fields, key)
            if value:
                return value
        return ""

    @staticmethod
    def _matches(content: str, keywords: Iterable[str]) -> bool:
        return any(keyword in content for keyword in keywords)

    @staticmethod
    def _safe_trace(content: str) -> dict[str, object]:
        return {
            "workflow_version": INTERNAL_WORKFLOW_VERSION,
            "sop_version": None,
            "knowledge_version": None,
            "sop_domains": [],
            "sop_record_count": 0,
            "rag_enabled": False,
            "rag_status": "disabled",
            "rag_hit_count": 0,
            "rag_top_k": 0,
            "rag_domains": [],
            "rag_top_score": 0.0,
            "rag_version_pinned": False,
            "rag_hit_versions": [],
            "rag_hit_version_ids": [],
            "rag_hit_content_hashes": [],
            "rag_hit_source_types": [],
            "rag_hit_source_ids_hash": [],
            "rag_hit_shop_ids_hash": [],
            "vector_store": "",
            "embedding_model": "",
            "retrieval_source": "",
            "rag_query_source": "",
            "question_optimization_used": False,
            "retrieval_mode": "",
            "semantic_weight": 0.0,
            "fulltext_weight": 0.0,
            "rrf_used": False,
            "rerank_used": False,
            "semantic_hit_count": 0,
            "fulltext_hit_count": 0,
            "answer_generator": "",
            "answer_generator_present": False,
            "answer_generator_type": "",
            "answer_generator_called": False,
            "llm_answer_called": False,
            "answer_generation_source": "",
            "answer_generation_status": "",
            "answer_error_type": "",
            "answer_error_raw_type": "",
            "answer_error_message_short": "",
            "answer_http_status": None,
            "answer_provider_host": "",
            "answer_timeout_ms": 0,
            "answer_raw_response_length": 0,
            "answer_text_length": 0,
            "answer_empty_reason": "",
            "answer_prompt_hash": "",
            "answer_used_rag_hit_count": 0,
            "answer_used_history_count": 0,
            "answer_fallback_reason": "",
            "answer_failure_policy": "",
            "answer_confidence": 0.0,
            "answer_length": 0,
            "answer_hash": "",
            "answer_preview_truncated": "",
            "used_history_count": 0,
            "used_rag_hit_count": 0,
            "prompt_hash": "",
            "intent_source": "",
            "intent_classifier_called": False,
            "intent_classifier_status": "",
            "llm_intent_called": False,
            "selected_domain": "",
            "selected_knowledge_base": "",
            "product_context_status": "none",
            "current_product_id_hash": "",
            "current_product_name_hash": "",
            "product_context_source": "none",
            "product_context_candidate_count": 0,
            "message_has_product_card": False,
            "message_type": "",
            "active_version_resolved": False,
            "active_version_id": None,
            "active_version": "",
            "active_source_type": "",
            "active_source_id": "",
            "active_domain": "",
            "active_version_fallback": False,
            "active_version_missing_reason": "",
            "guardrail_status": "safe",
            "final_action": "",
            "transfer_reason": "",
            "sets_pending_human": False,
            "calls_llm": False,
            "content_length": len(content),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        }

    @staticmethod
    def _rag_versions(hits: list[RetrievalHit]) -> list[str]:
        return _unique_text(hit.version for hit in hits)

    @staticmethod
    def _rag_version_ids(hits: list[RetrievalHit]) -> list[str]:
        return _unique_text((hit.metadata or {}).get("version_id") for hit in hits)

    @staticmethod
    def _rag_content_hashes(hits: list[RetrievalHit]) -> list[str]:
        return _unique_text(hit.content_hash for hit in hits)

    @staticmethod
    def _rag_source_types(hits: list[RetrievalHit]) -> list[str]:
        return _unique_text(hit.source_type for hit in hits)

    @staticmethod
    def _rag_source_id_hashes(hits: list[RetrievalHit]) -> list[str]:
        return _unique_text(
            hashlib.sha256(str(hit.source_id or "").encode("utf-8")).hexdigest()[:16]
            for hit in hits
            if hit.source_id
        )

    @staticmethod
    def _rag_shop_id_hashes(hits: list[RetrievalHit]) -> list[str]:
        return _unique_text(
            hashlib.sha256(str(hit.shop_id or "").encode("utf-8")).hexdigest()[:16]
            for hit in hits
            if hit.shop_id
        )

    def _finalize(self, result: WorkflowResult, context: WorkflowContext) -> WorkflowResult:
        guardrail_started_at = time.perf_counter()
        if not self.output_guardrail:
            trace = dict(result.trace) if isinstance(result.trace, dict) else {}
            self._set_stage_timing_value(trace, "guardrail_ms", 0)
            result.trace = trace
            return self._with_final_trace(result)
        checker = getattr(self.output_guardrail, "check", None)
        if callable(checker):
            checked = checker(result, context)
            trace = dict(checked.trace) if isinstance(checked.trace, dict) else {}
            self._set_stage_timing_value(trace, "guardrail_ms", self._elapsed_ms(guardrail_started_at))
            checked.trace = trace
            return self._with_final_trace(checked)
        if callable(self.output_guardrail):
            checked = self.output_guardrail(result, context)
            trace = dict(checked.trace) if isinstance(checked.trace, dict) else {}
            self._set_stage_timing_value(trace, "guardrail_ms", self._elapsed_ms(guardrail_started_at))
            checked.trace = trace
            return self._with_final_trace(checked)
        trace = dict(result.trace) if isinstance(result.trace, dict) else {}
        self._set_stage_timing_value(trace, "guardrail_ms", 0)
        result.trace = trace
        return self._with_final_trace(result)

    @staticmethod
    def _with_final_trace(result: WorkflowResult) -> WorkflowResult:
        trace = dict(result.trace) if isinstance(result.trace, dict) else {}
        internal_started_at = trace.pop("_internal_started_at", None)
        if isinstance(internal_started_at, (int, float)):
            InternalWorkflowEngine._set_stage_timing_value(
                trace,
                "internal_total_ms",
                InternalWorkflowEngine._elapsed_ms(float(internal_started_at)),
            )
        InternalWorkflowEngine._ensure_stage_timing(trace)
        blocked = result.reason == "output_guardrail_policy_violation" or "policy_violation" in set(result.risk_flags or [])
        trace["guardrail_status"] = "blocked" if blocked else "safe"
        trace["final_action"] = result.action.value if isinstance(result.action, WorkflowAction) else str(result.action or "")
        trace["sets_pending_human"] = result.action == WorkflowAction.TRANSFER_HUMAN
        if result.action == WorkflowAction.TRANSFER_HUMAN:
            trace["transfer_reason"] = result.reason or ""
        else:
            trace["transfer_reason"] = ""
        result.trace = trace
        write_private_trace(
            str(trace.get("trace_id") or ""),
            "final_result",
            {
                "action": result.action.value if isinstance(result.action, WorkflowAction) else str(result.action or ""),
                "intent": result.intent,
                "reason": result.reason,
                "reply_text": result.reply_text,
                "guardrail_status": trace.get("guardrail_status"),
                "risk_flags": list(result.risk_flags or []),
                "trace": trace,
            },
        )
        return result

    @staticmethod
    def _private_hit(hit: Any) -> dict[str, Any]:
        getter = hit.get if isinstance(hit, Mapping) else lambda key, default=None: getattr(hit, key, default)
        metadata = getter("metadata", {}) or {}
        return {
            "chunk_id": str(getter("chunk_id", "") or ""),
            "domain": str(getter("domain", "") or ""),
            "source_type": str(getter("source_type", "") or getter("source", "") or ""),
            "source_id": str(getter("source_id", "") or ""),
            "title": str(getter("title", "") or getter("goods_name", "") or ""),
            "score": getter("score", 0),
            "version": str(getter("version", "") or ""),
            "content_hash": str(getter("content_hash", "") or ""),
            "content": str(getter("content", "") or getter("content_summary", "") or ""),
            "metadata": metadata if isinstance(metadata, Mapping) else {},
        }

    @staticmethod
    def _private_record(record: Any) -> dict[str, Any]:
        getter = record.get if isinstance(record, Mapping) else lambda key, default=None: getattr(record, key, default)
        return {
            "domain": str(getter("domain", "") or ""),
            "version": str(getter("version", "") or ""),
            "title": str(getter("title", "") or ""),
            "content": str(getter("content", "") or getter("content_summary", "") or getter("approved_answer", "") or ""),
        }

    def _domain_policy_or_default(
        self,
        context: WorkflowContext,
        content: str,
        trace: dict[str, object],
        *,
        intent: str,
        domain: str,
        default: WorkflowResult,
    ) -> WorkflowResult:
        domain_result = self._domain_policy_result(context, content, trace, intent, domain)
        return domain_result if domain_result is not None else default

    def _domain_policy_result(
        self,
        context: WorkflowContext,
        content: str,
        trace: dict[str, object],
        intent: str,
        domain: str,
        include_missing: bool = False,
    ) -> WorkflowResult | None:
        rag_hits: list[RetrievalHit] = []
        query_started_at = time.perf_counter()
        rag_query = format_conversation_text(context)
        self._set_stage_timing_value(trace, "rag_query_build_ms", self._elapsed_ms(query_started_at))
        if intent not in {HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST, "human_escalation_redline", "explicit_human_request"}:
            rag_hits = self._retrieve_rag(context, intent, domain, rag_query, trace)
        if rag_hits:
            rag_trace = self._trace_with_rag(trace, rag_hits)
            generated = self._answer_generation_result(
                context=context,
                content=content,
                trace=rag_trace,
                intent=intent,
                action_hint=self._action_hint_for_policy_intent(intent),
                product_hits=[],
                sop_records=[self._rag_record(hit) for hit in rag_hits],
                fallback_reason="rag_policy_answer_generated",
            )
            if generated is not None:
                generated.knowledge_refs = [self._rag_ref(hit) for hit in rag_hits]
                return generated
            return self._answer_generator_unavailable_result(
                intent=intent,
                trace=rag_trace,
                risk_flags=self._risk_flags_for_policy_intent(intent),
                knowledge_refs=[self._rag_ref(hit) for hit in rag_hits],
            )

        records = self._get_sop_records(context.shop_id, domain, rag_query)
        effective_domain = domain
        if not records and domain != intent:
            legacy_records = self._get_sop_records(context.shop_id, intent, rag_query)
            if legacy_records:
                records = legacy_records
                effective_domain = intent
        if not records and not include_missing:
            return None
        if not records and include_missing:
            result = WorkflowResult(
                action=self._action_hint_for_policy_intent(intent),
                reply_text=self._render_rag_policy_reply(intent, domain),
                intent=intent,
                reason="domain_policy_missing_sop",
                risk_flags=self._risk_flags_for_policy_intent(intent),
                trace=self._merge_trace(trace, {}, records),
            )
            generated = self._answer_generation_result(
                context=context,
                content=content,
                trace=result.trace,
                intent=intent,
                action_hint=result.action,
                product_hits=[],
                sop_records=[],
                fallback_reason="domain_policy_answer_generated",
            )
            if generated is not None:
                generated.risk_flags = self._merge_flags(result.risk_flags, generated.risk_flags)
                return generated
            if result.action == WorkflowAction.TRANSFER_HUMAN:
                return result
            return self._answer_generator_unavailable_result(
                intent=intent,
                trace=result.trace,
                risk_flags=result.risk_flags,
                knowledge_refs=list(result.knowledge_refs or []),
            )

        responder = self.domain_policy_responder or DomainPolicyResponder()
        result = responder.respond_workflow(
            intent=intent,
            domain=effective_domain,
            sop_records=records,
            query_summary=content,
        )
        result.trace = self._merge_trace(trace, result.trace, records)
        generated = self._answer_generation_result(
            context=context,
            content=content,
            trace=result.trace,
            intent=intent,
            action_hint=result.action,
            product_hits=[],
            sop_records=records,
            fallback_reason="domain_policy_answer_generated",
        )
        if generated is not None:
            generated.knowledge_refs = list(result.knowledge_refs)
            generated.risk_flags = self._merge_flags(result.risk_flags, generated.risk_flags)
            return generated
        if result.action == WorkflowAction.TRANSFER_HUMAN:
            return result
        return self._answer_generator_unavailable_result(
            intent=intent,
            trace=result.trace,
            risk_flags=result.risk_flags,
            knowledge_refs=list(result.knowledge_refs or []),
        )

    def _answer_generator_unavailable_result(
        self,
        *,
        intent: str,
        trace: dict[str, object],
        risk_flags: list[str],
        knowledge_refs: list[dict[str, object]] | None = None,
    ) -> WorkflowResult:
        error_type = str(trace.get("answer_error_type") or "")
        if not error_type:
            error_type = classify_answer_error(str(trace.get("answer_error_raw_type") or ""), str(trace.get("answer_error_message_short") or ""))
        if not error_type:
            error_type = "answer_generator_exception"

        action = WorkflowAction.REPLY
        reply_text = PRODUCT_ANSWER_SAFE_FALLBACK_REPLY
        reason = "answer_generator_safe_fallback"
        failure_policy = "safe_fallback_reply"
        extra_flags: list[str] = ["answer_generator_unavailable", error_type]

        if intent in {AFTER_SALES_EVIDENCE_COLLECTION, "after_sales_evidence_collection"}:
            action = WorkflowAction.REQUEST_EVIDENCE
            reply_text = AFTER_SALES_ANSWER_SAFE_FALLBACK_REPLY
            reason = "answer_generator_safe_template"
            failure_policy = "safe_template_reply"
        elif intent in {SENSITIVE_USER_SAFETY, "sensitive_user_safety"}:
            action = WorkflowAction.REPLY
            reply_text = SENSITIVE_ANSWER_SAFE_FALLBACK_REPLY
            reason = "answer_generator_safe_template"
            failure_policy = "safe_template_reply"
        elif intent in {LOGISTICS_ORDER_STATUS, LOGISTICS_POLICY, "logistics_order_status", "logistics_policy"}:
            action = WorkflowAction.REPLY
            reply_text = LOGISTICS_ANSWER_SAFE_FALLBACK_REPLY
            reason = "answer_generator_safe_template"
            failure_policy = "safe_template_reply"
        elif intent in {PROMOTION_POLICY, "promotion_policy"}:
            action = WorkflowAction.REPLY
            reply_text = PROMOTION_ANSWER_SAFE_FALLBACK_REPLY
            reason = "answer_generator_safe_template"
            failure_policy = "safe_template_reply"
        elif intent in {HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST, "human_escalation_redline", "explicit_human_request"}:
            action = WorkflowAction.TRANSFER_HUMAN
            reply_text = ""
            reason = "answer_generator_unavailable"
            failure_policy = "transfer_human"

        updated_trace = {
            **trace,
            "answer_generator_called": bool(trace.get("answer_generator_called") or trace.get("llm_answer_called")),
            "answer_generation_status": str(trace.get("answer_generation_status") or "error"),
            "answer_error_type": error_type,
            "fallback_reason": reason,
            "answer_fallback_reason": reason,
            "answer_failure_policy": failure_policy,
            "sets_pending_human": action == WorkflowAction.TRANSFER_HUMAN,
            "transfer_reason": reason if action == WorkflowAction.TRANSFER_HUMAN else "",
        }
        return WorkflowResult(
            action=action,
            reply_text=reply_text,
            intent=intent,
            reason=reason,
            risk_flags=self._merge_flags(risk_flags, extra_flags),
            knowledge_refs=list(knowledge_refs or []),
            trace=updated_trace,
        )

    def _answer_generation_result(
        self,
        *,
        context: WorkflowContext,
        content: str,
        trace: dict[str, object],
        intent: str,
        action_hint: WorkflowAction,
        product_hits: list[Any],
        sop_records: list[Any],
        fallback_reason: str,
    ) -> WorkflowResult | None:
        trace["answer_generator_present"] = self.answer_generator is not None
        trace["answer_generator_type"] = self.answer_generator.__class__.__name__ if self.answer_generator is not None else ""
        trace["answer_used_rag_hit_count"] = int(trace.get("rag_hit_count") or 0)
        trace["answer_used_history_count"] = len(context.history or [])
        if self.answer_generator is None:
            trace.update(
                {
                    "answer_generator_called": False,
                    "answer_generation_status": "error",
                    "answer_error_type": "answer_generator_not_configured",
                    "answer_error_raw_type": "not_configured",
                    "answer_error_message_short": "answer generator is not configured",
                    "answer_failure_policy": "pending",
                }
            )
            return None
        if intent in {HUMAN_ESCALATION_REDLINE, EXPLICIT_HUMAN_REQUEST, "human_escalation_redline", "explicit_human_request"}:
            return None
        prompt_started_at = time.perf_counter()
        prompt_payload = build_prompt_payload(
            intent=intent,
            query_summary=content,
            history_window=context.history,
            product_hits=product_hits,
            sop_records=sop_records,
            product_context=(context.metadata or {}).get("product_context") if isinstance(context.metadata, dict) else {},
            constraints=[],
            forbidden_phrases=[],
        )
        self._set_stage_timing_value(trace, "prompt_build_ms", self._elapsed_ms(prompt_started_at))
        draft_context = AnswerGenerationContext(
            intent=intent,
            action_hint=action_hint.value if isinstance(action_hint, WorkflowAction) else str(action_hint or ""),
            query_summary=content,
            history_window=list(context.history or []),
            product_hits=list(product_hits or []),
            sop_records=list(sop_records or []),
            product_context=(context.metadata or {}).get("product_context") if isinstance(context.metadata, dict) else {},
            constraints=list(prompt_payload.system_instructions),
            forbidden_phrases=[],
            workflow_version=str(trace.get("workflow_version") or INTERNAL_WORKFLOW_VERSION),
            sop_version=str(trace.get("sop_version") or ""),
            knowledge_version=str(trace.get("knowledge_version") or ""),
            trace_id=context.trace_id,
            prompt_hash=prompt_payload.prompt_hash,
            conversation_text=prompt_payload.conversation_text,
        )
        generator = getattr(self.answer_generator, "generate", None)
        if not callable(generator):
            trace.update(
                {
                    "answer_generator_called": False,
                    "answer_generation_status": "error",
                    "answer_error_type": "answer_generator_not_configured",
                    "answer_error_raw_type": "not_callable",
                    "answer_error_message_short": "answer generator has no callable generate",
                    "answer_failure_policy": "pending",
                }
            )
            return None
        write_private_trace(
            context.trace_id,
            "answer_generation_input",
            {
                "intent": intent,
                "action_hint": action_hint.value if isinstance(action_hint, WorkflowAction) else str(action_hint or ""),
                "conversation_text": prompt_payload.conversation_text,
                "system_instructions": list(prompt_payload.system_instructions),
                "context_blocks": list(prompt_payload.context_blocks),
                "user_task": prompt_payload.user_task,
                "output_format": prompt_payload.output_format,
                "prompt_hash": prompt_payload.prompt_hash,
                "product_hits": [self._private_hit(hit) for hit in list(product_hits or [])[:3]],
                "sop_records": [self._private_record(record) for record in list(sop_records or [])[:3]],
            },
        )
        llm_answer_started_at = time.perf_counter()
        try:
            draft = generator(draft_context)
        except Exception as exc:
            self._set_stage_timing_value(trace, "llm_answer_ms", self._elapsed_ms(llm_answer_started_at))
            classified_error = classify_answer_error(type(exc).__name__, str(exc))
            trace.update(
                {
                    "answer_generator_called": True,
                    "answer_generation_status": "error",
                    "answer_error_type": classified_error,
                    "answer_error_raw_type": type(exc).__name__,
                    "answer_error_message_short": self._short_error(str(exc)),
                    "fallback_reason": "answer_generator_exception",
                    "answer_fallback_reason": "answer_generator_exception",
                    "answer_failure_policy": "pending",
                    "answer_prompt_hash": prompt_payload.prompt_hash,
                    "prompt_hash": prompt_payload.prompt_hash,
                }
            )
            return None
        self._set_stage_timing_value(trace, "llm_answer_ms", self._elapsed_ms(llm_answer_started_at))
        text = str(getattr(draft, "text", "") or "")
        text, answer_calibrated, answer_calibration_reason = self._calibrate_product_answer_text(
            intent=intent,
            query=content,
            answer_text=text,
            product_hits=product_hits,
        )
        source = str(getattr(draft, "source", "") or "unknown")
        raw_error_type = str(getattr(draft, "raw_error_type", "") or "")
        raw_error_summary = str(getattr(draft, "raw_error_summary", "") or "")
        classified_error = classify_answer_error(raw_error_type, raw_error_summary) if raw_error_type or not text else ""
        empty_reason = self._answer_empty_reason(raw_error_type, raw_error_summary) if not text else ""
        write_private_trace(
            context.trace_id,
            "answer_generation_output",
            {
                "source": source,
                "answer_text": text,
                "confidence": float(getattr(draft, "confidence", 0.0) or 0.0),
                "error_type": str(getattr(draft, "raw_error_type", "") or ""),
                "error_summary": str(getattr(draft, "raw_error_summary", "") or ""),
            },
        )
        generated_trace = {
            **trace,
            "answer_generator": source,
            "answer_generator_present": True,
            "answer_generator_type": self.answer_generator.__class__.__name__,
            "answer_generator_called": True,
            "llm_answer_called": source == "openai_compatible",
            "llm_provider": source,
            "llm_model": str(getattr(draft, "provider_model", "") or ""),
            "llm_http_status": getattr(draft, "http_status", None),
            "llm_latency_ms": int(getattr(draft, "latency_ms", 0) or trace.get("llm_answer_ms") or 0),
            "llm_prompt_tokens": int(getattr(draft, "prompt_tokens", 0) or 0),
            "llm_completion_tokens": int(getattr(draft, "completion_tokens", 0) or 0),
            "llm_total_tokens": int(getattr(draft, "total_tokens", 0) or 0),
            "answer_generation_source": source,
            "answer_generation_status": "ok" if text else "error",
            "answer_error_type": classified_error,
            "answer_error_raw_type": raw_error_type,
            "answer_error_message_short": self._short_error(raw_error_summary),
            "answer_http_status": getattr(draft, "http_status", None),
            "answer_provider_host": str(getattr(draft, "provider_host", "") or ""),
            "answer_timeout_ms": int(getattr(draft, "timeout_ms", 0) or 0),
            "answer_raw_response_length": int(getattr(draft, "response_length", 0) or getattr(draft, "raw_response_length", 0) or 0),
            "answer_text_length": len(text),
            "answer_empty_reason": empty_reason,
            "answer_confidence": round(float(getattr(draft, "confidence", 0.0) or 0.0), 3),
            "answer_length": len(text),
            "answer_hash": answer_hash(text),
            "answer_preview_truncated": answer_preview(text),
            "answer_calibrated": answer_calibrated,
            "answer_calibration_reason": answer_calibration_reason,
            "used_history_count": int(getattr(draft, "used_history_count", len(context.history or [])) or 0),
            "used_rag_hit_count": int(trace.get("rag_hit_count") or 0),
            "answer_used_history_count": int(getattr(draft, "used_history_count", len(context.history or [])) or 0),
            "answer_used_rag_hit_count": int(trace.get("rag_hit_count") or 0),
            "answer_prompt_hash": prompt_payload.prompt_hash,
            "prompt_hash": prompt_payload.prompt_hash,
            "calls_llm": source == "openai_compatible",
        }
        if not text:
            trace.update(generated_trace)
            return None
        return WorkflowResult(
            action=action_hint if isinstance(action_hint, WorkflowAction) else WorkflowAction.REPLY,
            reply_text=text,
            intent=intent,
            reason=fallback_reason,
            risk_flags=list(getattr(draft, "risk_flags", []) or []),
            trace=generated_trace,
            raw_error_type=str(getattr(draft, "raw_error_type", "") or ""),
            raw_error_summary=str(getattr(draft, "raw_error_summary", "") or ""),
        )

    def _calibrate_product_answer_text(
        self,
        *,
        intent: str,
        query: str,
        answer_text: str,
        product_hits: list[Any],
    ) -> tuple[str, bool, str]:
        if intent not in {PRODUCT_BASIC, "product_basic", "product_catalog"}:
            return answer_text, False, ""
        if not self._is_boundary_only_product_answer(answer_text):
            return answer_text, False, ""

        if self._is_price_query(query):
            price = self._extract_product_hit_value(product_hits, ("price", "价格", "价钱", "参考价"))
            if price and not self._answer_contains_price(answer_text, price):
                return (
                    f"当前商品信息显示价格为 {price}，实际以商品页面和下单结算页为准。",
                    True,
                    "price_from_rag_context",
                )

        if self._is_specs_query(query):
            specs = self._extract_product_hit_value(
                product_hits,
                ("specs", "specifications", "sku_summary", "sku_options", "规格"),
            )
            if specs and not self._answer_contains_substantive_value(answer_text, specs, generic_terms={"规格", "款式"}):
                return (
                    f"当前商品信息显示规格为 {specs}，具体以商品页面为准。",
                    True,
                    "specs_from_rag_context",
                )

        if self._is_usage_query(query):
            usage = self._extract_product_hit_value(
                product_hits,
                ("usage", "usage_method", "使用方法", "用法"),
            )
            if usage and not self._answer_contains_substantive_value(answer_text, usage, generic_terms={"使用方法", "用法"}):
                suffix = "" if "商品详情页" in usage or "详情页" in usage else " 具体以商品详情页说明为准。"
                return f"用法参考：{usage}{suffix}", True, "usage_from_rag_context"

        return answer_text, False, ""

    @staticmethod
    def _is_boundary_only_product_answer(answer_text: str) -> bool:
        text = str(answer_text or "")
        if not text:
            return False
        boundary_terms = ("以商品页面", "以页面", "结算页", "详情页", "显示为准", "说明为准", "为准")
        return any(term in text for term in boundary_terms)

    @staticmethod
    def _is_price_query(query: str) -> bool:
        return any(term in query for term in ("多少钱", "多少錢", "价格", "價錢", "价钱"))

    @staticmethod
    def _is_specs_query(query: str) -> bool:
        return any(term in query for term in ("规格", "規格", "什么规格", "哪种规格", "款式", "几瓶"))

    @staticmethod
    def _is_usage_query(query: str) -> bool:
        return any(term in query for term in ("怎么用", "如何用", "使用方法", "用法", "咋用", "怎么使用"))

    def _extract_product_hit_value(self, product_hits: list[Any], labels: Iterable[str]) -> str:
        label_set = tuple(str(label).lower() for label in labels)
        for hit in product_hits or []:
            metadata = getattr(hit, "metadata", None)
            if isinstance(metadata, dict):
                fields = metadata.get("fields")
                if isinstance(fields, dict):
                    value = self._extract_value_from_mapping(fields, label_set)
                    if value:
                        return value
            hit_text = "\n".join(
                str(value or "")
                for value in (
                    getattr(hit, "content_summary", ""),
                    getattr(hit, "content", ""),
                    getattr(hit, "title", ""),
                )
                if value
            )
            value = self._extract_labeled_value(hit_text, label_set)
            if value:
                return value
        return ""

    def _extract_value_from_mapping(self, fields: Mapping[str, Any], labels: Iterable[str]) -> str:
        label_set = tuple(str(label).lower() for label in labels)
        for key, raw_value in fields.items():
            key_text = str(key).lower()
            if any(label in key_text for label in label_set):
                if isinstance(raw_value, Mapping):
                    raw_value = raw_value.get("value")
                value = self._compact_product_value(raw_value)
                if value:
                    return value
        return ""

    def _extract_labeled_value(self, text: str, labels: Iterable[str]) -> str:
        label_set = tuple(str(label).lower() for label in labels)
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lower = line.lower()
            if not any(label in lower for label in label_set):
                continue
            if ":" in line:
                value = line.split(":", 1)[1]
            elif "：" in line:
                value = line.split("：", 1)[1]
            else:
                value = line
            value = self._compact_product_value(value)
            if value:
                return value
        return ""

    @staticmethod
    def _compact_product_value(value: Any, *, max_chars: int = 120) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"[\[\]\"']", "", text)
        text = re.sub(r"\s*,\s*", "、", text)
        text = re.sub(r"\s+", " ", text).strip(" 、，。")
        if len(text) > max_chars:
            return text[:max_chars].rstrip() + "..."
        return text

    @staticmethod
    def _answer_contains_price(answer_text: str, price: str) -> bool:
        answer = str(answer_text or "")
        for number in re.findall(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", str(price or "")):
            if number and number in answer:
                return True
        return bool(price and price in answer)

    @staticmethod
    def _answer_contains_substantive_value(answer_text: str, value: str, *, generic_terms: set[str] | None = None) -> bool:
        answer = str(answer_text or "")
        generic_terms = generic_terms or set()
        terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9.:-]+", str(value or ""))
        for term in terms:
            term = term.strip(" :-")
            if len(term) < 2 or term in generic_terms:
                continue
            if term in answer:
                return True
        return False

    @staticmethod
    def _short_error(value: str, *, max_chars: int = 120) -> str:
        text = str(value or "")
        text = re.sub(
            r"(?i)(token|cookie|access_token|authorization|api_key|secret)\s*[:=]\s*[^,\s]+",
            r"\1=<redacted>",
            text,
        )
        text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._\-]+", "Bearer <redacted>", text)
        text = re.sub(r"ark-[A-Za-z0-9._\-]+", "ark-<redacted>", text)
        text = re.sub(r"postgresql://[^\s]+", "postgresql://<redacted>", text)
        return text.strip()[:max_chars]

    @staticmethod
    def _answer_empty_reason(raw_error_type: str, raw_error_summary: str) -> str:
        if str(raw_error_type or "").lower() == "empty_answer":
            return "provider_returned_empty_text"
        if raw_error_summary:
            return "provider_returned_error_without_text"
        return "provider_returned_empty_text"

    def _get_sop_records(self, shop_id: str, domain: str, query: str) -> list[Any]:
        provider = self.sop_provider
        if provider is not None:
            provider_records = getattr(provider, "records", None)
            if isinstance(provider_records, list):
                return [
                    record
                    for record in provider_records
                    if str(self._record_value(record, "shop_id") or "").strip() == str(shop_id or "").strip()
                    and str(self._record_value(record, "domain") or "").strip() == str(domain or "").strip()
                ]
            getter = getattr(provider, "get_records", None)
            if callable(getter):
                try:
                    return list(getter(shop_id, domain))
                except Exception:
                    return []

        retriever = getattr(self, "sop_retriever", None)
        if retriever is not None:
            search = getattr(retriever, "search", None)
            if callable(search):
                try:
                    return list(search(shop_id=shop_id, domain=domain, query=query, limit=3))
                except Exception:
                    return []
        return []

    def _sop_source_available(self) -> bool:
        return self.sop_provider is not None or getattr(self, "sop_retriever", None) is not None

    @staticmethod
    def _policy_domain_for_intent(intent: str) -> str:
        return {
            LOGISTICS_ORDER_STATUS: "logistics_policy",
            LOGISTICS_POLICY: "logistics_policy",
            AFTER_SALES_EVIDENCE_COLLECTION: "after_sales_evidence",
            PROMOTION_POLICY: "promotion_policy",
            HUMAN_ESCALATION_REDLINE: "redline_escalation",
            EXPLICIT_HUMAN_REQUEST: "redline_escalation",
            SENSITIVE_USER_SAFETY: "sensitive_user_safety",
        }.get(str(intent or ""), "")

    def _merge_trace(self, base: dict[str, object], extra: object, records: list[Any]) -> dict[str, object]:
        trace = dict(base)
        if isinstance(extra, dict):
            trace.update(extra)
        trace["sop_record_count"] = len(records)
        trace["sop_domains"] = sorted({str(self._record_value(record, "domain") or "") for record in records if self._record_value(record, "domain")})
        trace["sop_version"] = self._first_record_value(records, "version") or None
        if records:
            domain = str(self._record_value(records[0], "domain") or "")
            trace["selected_domain"] = domain
            trace["selected_knowledge_base"] = domain
        return trace

    @staticmethod
    def _record_value(record: Any, key: str) -> Any:
        if isinstance(record, dict):
            return record.get(key)
        return getattr(record, key, None)

    def _first_record_value(self, records: list[Any], key: str) -> str:
        for record in records:
            value = self._record_value(record, key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _classification_metadata(context: WorkflowContext) -> dict[str, object]:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        return {
            "trace_id": context.trace_id,
            "shop_id": context.shop_id,
            "user_id": context.user_id,
            "session_id": context.session_id,
            "message_type": context.message_type,
            "risk_flags": metadata.get("risk_flags", []),
            "signals": metadata.get("signals", []),
            "sensitive": bool(metadata.get("sensitive", False)),
            "redline": bool(metadata.get("redline", False)),
            "product_context": metadata.get("product_context", {}),
            "history_count": len(context.history or []),
        }

    @staticmethod
    def _merge_flags(existing: Iterable[str], additions: Iterable[str]) -> list[str]:
        merged: list[str] = []
        for flag in (*tuple(existing or ()), *tuple(additions or ())):
            value = str(flag or "").strip()
            if value and value not in merged:
                merged.append(value)
        return merged

    def _load_conversation_context(self, context: WorkflowContext) -> ConversationContext | None:
        repository = self.conversation_context_repository
        if repository is None:
            return None
        loader = getattr(repository, "load_context", None)
        if not callable(loader):
            return None
        buyer_id = context.buyer_id or context.customer_uid
        try:
            return loader(
                shop_id=context.shop_id,
                user_id=context.user_id,
                buyer_id=buyer_id,
                session_id=context.session_id,
                limit=40,
            )
        except Exception:
            return None

    @staticmethod
    def _merge_conversation_trace(
        trace: dict[str, object],
        conversation_context: ConversationContext | None,
    ) -> dict[str, object]:
        if conversation_context is None:
            return {
                **trace,
                "history_message_count": 0,
                "history_window_size": 0,
                "pending_human": False,
                "history_source": "",
            }
        return {
            **trace,
            "history_message_count": conversation_context.history_message_count,
            "history_window_size": len(conversation_context.history_window),
            "pending_human": bool(conversation_context.pending_human),
            "conversation_id_hash": conversation_context.conversation_id,
            "session_id_hash": stable_hash(conversation_context.session_id),
            "buyer_id_hash": stable_hash(conversation_context.buyer_id),
            "user_id_hash": stable_hash(conversation_context.user_id),
            "history_source": conversation_context.history_source,
        }

    @staticmethod
    def _attach_history(
        context: WorkflowContext,
        conversation_context: ConversationContext | None,
    ) -> None:
        if conversation_context is None:
            return
        context.history = [
            {
                "role": message.role,
                "message_type": message.message_type,
                "content": message.content,
                "content_summary": message.content_summary,
                "content_hash": message.content_hash,
                "created_at": message.created_at,
                "source": message.source,
            }
            for message in conversation_context.history_window
        ]


class _NullIntentClassifier:
    async def classify(self, content: str, content_metadata: dict[str, object] | None = None) -> IntentClassification:
        del content, content_metadata
        return IntentClassification(intent=FALLBACK, confidence=0.0, reason="no_rule_matched")


def _unique_text(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
