from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from web_api.schemas.live_chat import LiveChatMessageRequest, LiveChatMessageResponse, LiveChatSession
from web_api.services.internal_engine_adapter import WebInternalEngineAdapter
from web_api.services.trace_service import TraceService


PRODUCT_CLARIFICATION_REPLY = "请问您要咨询哪一款商品？可以发一下商品卡片或商品名称。"


@dataclass
class LiveChatSessionState:
    shop_id: str
    buyer_id: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    current_product_context: dict[str, Any] | None = None
    last_intent: str | None = None
    last_action: str | None = None


class LiveChatService:
    """No-send InternalEngine live chat service for Web Admin."""

    def __init__(self, trace_service: TraceService, engine_adapter: WebInternalEngineAdapter | None = None) -> None:
        self._trace_service = trace_service
        self._engine_adapter = engine_adapter or WebInternalEngineAdapter()
        self._sessions: dict[str, LiveChatSessionState] = {}

    def create_session(self, shop_id: str, buyer_id: str | None = None) -> LiveChatSession:
        session_id = f"session-{uuid4().hex[:10]}"
        self._sessions[session_id] = LiveChatSessionState(shop_id=shop_id, buyer_id=buyer_id)
        return LiveChatSession(session_id=session_id, no_send=True, engine="internal", shop_id=shop_id, buyer_id=buyer_id)

    def send_message(self, session_id: str, payload: LiveChatMessageRequest) -> LiveChatMessageResponse:
        state = self._sessions.setdefault(
            session_id,
            LiveChatSessionState(shop_id=payload.shop_id, buyer_id=payload.buyer_id),
        )
        state.shop_id = payload.shop_id or state.shop_id
        state.buyer_id = payload.buyer_id or state.buyer_id

        message = str(payload.message or "").strip()
        buyer_id = state.buyer_id or payload.buyer_id or "web-admin-buyer"
        metadata = dict(payload.metadata or {})
        product_context, product_anchor_source = self._resolve_product_context(state, metadata)
        if product_context:
            state.current_product_context = product_context

        adapter_trace_patch: dict[str, Any] = {
            "smoke_profile": str(payload.smoke_profile or "facade"),
            "engine_mode": "facade",
            "engine_adapter_status": "skipped",
            "engine_adapter_error_type": "",
            "real_engine_called": False,
            "use_real_engine": bool(payload.use_real_engine),
            "use_real_pgvector": bool(payload.use_real_pgvector),
            "use_real_ollama": bool(payload.use_real_ollama),
            "use_real_llm": bool(payload.use_real_llm),
            "use_real_intent_classifier": bool(payload.use_real_intent_classifier),
            "use_real_answer_generator": bool(payload.use_real_answer_generator),
            "provider_status": _fallback_provider_status(payload),
            "provider_error_type": "",
            "provider_error_summary": "",
            "stage_status": _fallback_stage_status(),
            "latency_ms": _fallback_latency(),
        }
        if payload.use_real_engine or _profile_requests_real_engine(payload.smoke_profile):
            attempt = self._engine_adapter.run_message(
                session_id=session_id,
                payload=payload,
                session_state=state,
                product_context=state.current_product_context,
                product_anchor_source=product_anchor_source,
            )
            if attempt.response is not None:
                self._record_exchange(state, message, metadata, attempt.response.reply, attempt.response.intent, attempt.response.action)
                self._trace_service.add_trace(
                    payload.shop_id,
                    buyer_id,
                    session_id,
                    message,
                    attempt.response.reply,
                    attempt.response.intent,
                    attempt.response.domain,
                    attempt.response.action,
                )
                return attempt.response
            adapter_trace_patch.update(attempt.trace_patch or {})

        trace_id = f"web-live-{uuid4().hex[:12]}"
        intent, domain, action, reply, rag_status, retrieved_chunks, answer_status = self._classify_and_reply(
            message=message,
            product_context=state.current_product_context,
            payload=payload,
        )
        product_context_status = "resolved" if state.current_product_context else (
            "missing_required" if intent == "ask_product_clarification" else "none"
        )
        prompt = self._build_debug_prompt(message, state, retrieved_chunks, intent, domain)
        trace = {
            "trace_id": trace_id,
            "engine": "internal",
            "buyer_message": message,
            "ai_reply": reply,
            "prompt": prompt,
            "raw_response": reply,
            "retrieved_chunks": retrieved_chunks,
            "rag_query": self._build_rag_query(message, state.current_product_context, state.history),
            "product_context": state.current_product_context or {},
            "product_context_status": product_context_status,
            "product_anchor_source": product_anchor_source,
            "history_message_count": len(state.history),
            "intent_classifier_called": False,
            "intent_classifier_status": "skipped" if not payload.use_real_llm else "provider_not_configured",
            "rag_status": rag_status,
            "rag_hit_count": len(retrieved_chunks),
            "rag_domains": [domain] if domain else [],
            "answer_generation_status": answer_status,
            "guardrail_status": "safe",
            "calls_llm": False,
            "calls_ollama": False,
            "connects_pgvector": False,
            "sends_pdd": False,
            "no_send": True,
            "product_version": payload.product_version,
            "sop_version": payload.sop_version,
            "rag_top_k": payload.rag_top_k,
            "created_at": datetime.utcnow().isoformat(timespec="seconds"),
            **adapter_trace_patch,
        }

        self._record_exchange(state, message, metadata, reply, intent, action)
        self._trace_service.add_trace(payload.shop_id, buyer_id, session_id, message, reply, intent, domain, action)
        return LiveChatMessageResponse(
            reply=reply,
            action=action,
            intent=intent,
            domain=domain,
            session_id=session_id,
            no_send=True,
            trace=trace,
        )

    def _record_exchange(
        self,
        state: LiveChatSessionState,
        message: str,
        metadata: dict[str, Any],
        reply: str,
        intent: str,
        action: str,
    ) -> None:
        state.history.append(self._history_message("buyer", message, metadata, state.current_product_context))
        state.history.append(self._history_message("assistant", reply, {}, None))
        state.last_intent = intent
        state.last_action = action

    def _resolve_product_context(
        self,
        state: LiveChatSessionState,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        goods_id = _first_text(metadata, "goods_id", "goodsID")
        goods_name = _first_text(metadata, "goods_name", "goodsName", "product_name")
        goods_price = _first_text(metadata, "goods_price", "goodsPrice", "price")
        spec = _first_text(metadata, "spec", "sku", "specification")
        if goods_id or goods_name:
            return (
                {
                    "goods_id": goods_id,
                    "goods_name": goods_name,
                    "product_name": goods_name,
                    "goods_price": goods_price,
                    "spec": spec,
                    "source": "message_metadata",
                    "status": "resolved",
                },
                "message_metadata",
            )
        if state.current_product_context:
            return state.current_product_context, "session"
        for item in reversed(state.history):
            product = item.get("product_context") if isinstance(item, dict) else None
            if isinstance(product, dict) and (product.get("goods_id") or product.get("goods_name")):
                return {**product, "source": "history", "status": "resolved"}, "history"
        return None, "none"

    def _classify_and_reply(
        self,
        *,
        message: str,
        product_context: dict[str, Any] | None,
        payload: LiveChatMessageRequest,
    ) -> tuple[str, str | None, str, str, str, list[dict[str, Any]], str]:
        if _contains_any(message, ("人工", "真人客服", "转人工")):
            return ("explicit_human_request", "redline_escalation", "transfer_human", "已为您转人工处理。", "skipped", [], "skipped")
        if _contains_any(message, ("假货", "投诉", "12315", "赔偿", "差评")):
            return ("human_escalation_redline", "redline_escalation", "transfer_human", "已为您转人工处理。", "skipped", [], "skipped")
        if _is_product_question(message):
            if not product_context:
                return ("ask_product_clarification", "product_basic", "reply", PRODUCT_CLARIFICATION_REPLY, "skipped", [], "skipped")
            chunks = self._product_chunks(product_context, payload.rag_top_k)
            return (
                "product_basic",
                "product_catalog",
                "reply",
                self._product_reply(message, product_context),
                "session_context_hit" if payload.use_rag else "disabled",
                chunks if payload.use_rag else [],
                "internal_no_send",
            )
        if _contains_any(message, ("发货", "物流", "快递", "到货", "什么时候到", "运费")):
            return (
                "logistics_order_status",
                "logistics_policy",
                "reply",
                "亲，发货和物流进度请以订单页显示为准，有异常我可以帮您转人工核实。",
                "builtin_policy_hit" if payload.use_rag else "disabled",
                self._policy_chunks("logistics_policy") if payload.use_rag else [],
                "internal_no_send",
            )
        if _contains_any(message, ("破损", "坏了", "漏液", "少发", "错发", "质量问题")):
            return (
                "after_sales_evidence_collection",
                "after_sales_evidence",
                "reply",
                "亲，请先提供问题照片、外包装照片和订单信息，客服会为您核实处理。",
                "builtin_policy_hit" if payload.use_rag else "disabled",
                self._policy_chunks("after_sales_evidence") if payload.use_rag else [],
                "internal_no_send",
            )
        if _contains_any(message, ("便宜", "优惠", "赠品", "差价", "活动", "优惠券")):
            return (
                "promotion_policy",
                "promotion_policy",
                "reply",
                "亲，优惠以商品页、活动页和结算页显示为准，暂不承诺额外私下优惠。",
                "builtin_policy_hit" if payload.use_rag else "disabled",
                self._policy_chunks("promotion_policy") if payload.use_rag else [],
                "internal_no_send",
            )
        if _contains_any(message, ("孕妇", "宝宝", "小孩", "儿童", "过敏", "敏感肌")):
            return (
                "sensitive_user_safety",
                "sensitive_user_safety",
                "reply",
                "亲，孕妇、儿童或敏感肌建议先看成分说明，必要时咨询专业人士或转人工确认。",
                "builtin_policy_hit" if payload.use_rag else "disabled",
                self._policy_chunks("sensitive_user_safety") if payload.use_rag else [],
                "internal_no_send",
            )
        if product_context:
            chunks = self._product_chunks(product_context, payload.rag_top_k)
            return (
                "product_basic",
                "product_catalog",
                "reply",
                self._product_reply(message, product_context),
                "session_context_hit" if payload.use_rag else "disabled",
                chunks if payload.use_rag else [],
                "internal_no_send",
            )
        return (
            "fallback",
            None,
            "reply",
            "亲，这个问题我先帮您记录，如需进一步确认可以转人工处理。",
            "skipped",
            [],
            "internal_no_send",
        )

    @staticmethod
    def _product_reply(message: str, product_context: dict[str, Any]) -> str:
        name = str(product_context.get("goods_name") or product_context.get("product_name") or "这款商品")
        price = str(product_context.get("goods_price") or "").strip()
        if _contains_any(message, ("多少钱", "价格", "价钱")):
            if price:
                return f"亲，这款{name}页面价格约{price}，实际以商品页和结算页为准哦。"
            return f"亲，这款{name}价格请以商品页和结算页显示为准哦。"
        if _contains_any(message, ("怎么用", "用法", "使用")):
            return f"亲，这款{name}按商品详情页说明使用即可，具体用量以页面提示为准哦。"
        if _contains_any(message, ("规格", "几张", "多少张", "成分", "保质期")):
            spec = str(product_context.get("spec") or "").strip()
            if spec:
                return f"亲，这款{name}规格是{spec}，实际以商品页展示为准哦。"
            return f"亲，这款{name}具体规格请以商品页展示为准哦。"
        return f"亲，这款{name}可以看商品页详情，价格和规格以页面显示为准哦。"

    @staticmethod
    def _product_chunks(product_context: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
        parts = [
            f"商品：{product_context.get('goods_name') or product_context.get('product_name') or ''}",
            f"价格：{product_context.get('goods_price') or ''}",
            f"商品ID：{product_context.get('goods_id') or ''}",
            f"规格：{product_context.get('spec') or ''}",
        ]
        content = "；".join(part for part in parts if not part.endswith("："))
        return [
            {
                "chunk_id": f"web-live-product-{_hash(product_context.get('goods_id') or content)}",
                "domain": "product_catalog",
                "source_type": "session_product_context",
                "source_id": str(product_context.get("goods_id") or ""),
                "content": content or "当前会话商品上下文",
                "score": 1.0,
                "metadata": {
                    "goods_id": product_context.get("goods_id"),
                    "goods_name": product_context.get("goods_name") or product_context.get("product_name"),
                },
            }
        ][: max(1, int(top_k or 3))]

    @staticmethod
    def _policy_chunks(domain: str) -> list[dict[str, Any]]:
        content_by_domain = {
            "logistics_policy": "物流状态以订单页为准，不编造具体运输进度，可转人工核实异常订单。",
            "after_sales_evidence": "售后问题先收集问题照片、外包装照片、订单信息和具体情况，不承诺处理结果。",
            "promotion_policy": "优惠以商品页、活动页和结算页为准，不承诺私下优惠、赠品或返差价。",
            "sensitive_user_safety": "敏感人群不做确定性安全承诺，建议查看成分说明并咨询专业人士。",
        }
        return [
            {
                "chunk_id": f"web-live-{domain}-1",
                "domain": domain,
                "source_type": "builtin_fallback_policy",
                "source_id": domain,
                "content": content_by_domain.get(domain, ""),
                "score": 0.9,
                "metadata": {"domain": domain},
            }
        ]

    @staticmethod
    def _build_debug_prompt(
        message: str,
        state: LiveChatSessionState,
        chunks: list[dict[str, Any]],
        intent: str,
        domain: str | None,
    ) -> str:
        history_preview = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in state.history[-10:]
        ) or "无"
        chunk_text = "\n".join(str(item.get("content") or "") for item in chunks) or "无"
        return (
            "你是 InternalEngine no-send 调试客服助手。\n"
            f"前文摘要:\n{history_preview}\n\n"
            f"当前消息: {message}\n"
            f"意图: {intent}\n"
            f"领域: {domain or 'none'}\n"
            f"商品上下文: {state.current_product_context or {}}\n"
            f"知识库结果:\n{chunk_text}\n"
            "只输出将展示给买家的客服回复。"
        )

    @staticmethod
    def _build_rag_query(message: str, product_context: dict[str, Any] | None, history: list[dict[str, Any]]) -> str:
        history_text = " ".join(str(item.get("content") or "") for item in history[-6:])
        product_text = " ".join(str(value or "") for value in (product_context or {}).values())
        return " ".join(part for part in (history_text, product_text, message) if part).strip()

    @staticmethod
    def _history_message(
        role: str,
        content: str,
        metadata: dict[str, Any],
        product_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "role": role,
            "content": content,
            "metadata": metadata,
            "product_context": product_context or {},
            "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        }


def _first_text(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _is_product_question(text: str) -> bool:
    return _contains_any(
        text,
        (
            "这个",
            "这款",
            "商品",
            "多少钱",
            "价格",
            "价钱",
            "怎么用",
            "用法",
            "规格",
            "成分",
            "保质期",
            "几张",
            "多少张",
        ),
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def _fallback_provider_status(payload: LiveChatMessageRequest) -> dict[str, str]:
    return {
        "real_engine": "skipped",
        "pgvector": "disabled",
        "ollama": "disabled",
        "llm": "disabled",
        "intent_classifier": "disabled" if not payload.use_llm_intent_classifier else "fallback",
        "answer_generator": "disabled" if not payload.use_llm_answer_generator else "fallback",
    }


def _profile_requests_real_engine(smoke_profile: str | None) -> bool:
    return str(smoke_profile or "").strip() in {
        "real_engine_only",
        "real_rag",
        "real_intent",
        "real_answer",
        "real_full",
    }


def _fallback_stage_status() -> dict[str, str]:
    return {
        "context": "ok",
        "routing": "ok",
        "rag": "fallback",
        "intent": "fallback",
        "answer": "fallback",
        "guardrail": "safe",
    }


def _fallback_latency() -> dict[str, int]:
    return {"total": 0, "engine": 0, "rag": 0, "llm": 0, "guardrail": 0}
