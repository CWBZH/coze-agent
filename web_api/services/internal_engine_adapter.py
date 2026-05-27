from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from web_api.schemas.live_chat import LiveChatMessageRequest, LiveChatMessageResponse


EngineFactory = Callable[["WebEngineOptions"], Any]
ChunkLoader = Callable[..., tuple[list[Any], str | None]]


@dataclass(frozen=True)
class WebEngineOptions:
    use_real_engine: bool = False
    use_real_pgvector: bool = False
    use_real_ollama: bool = False
    use_real_llm: bool = False
    use_real_intent_classifier: bool = False
    use_real_answer_generator: bool = False
    product_version: str = "real-product-v1"
    sop_version: str = "sop-test-v1"
    rag_top_k: int = 3
    smoke_profile: str = ""


@dataclass
class WebEngineAttempt:
    response: LiveChatMessageResponse | None = None
    trace_patch: dict[str, Any] | None = None


class WebInternalEngineAdapter:
    """Safe lazy adapter for optional no-send InternalEngine execution."""

    def __init__(self, engine_factory: EngineFactory | None = None, chunk_loader: ChunkLoader | None = None) -> None:
        self._engine_factory = engine_factory
        self._chunk_loader = chunk_loader

    def is_available(self) -> bool:
        try:
            self._load_internal_symbols()
            return True
        except Exception:
            return False

    def run_message(
        self,
        *,
        session_id: str,
        payload: LiveChatMessageRequest,
        session_state: Any,
        product_context: dict[str, Any] | None,
        product_anchor_source: str,
    ) -> WebEngineAttempt:
        options = _options_from_payload(payload)
        missing = self._missing_environment(options)
        if missing:
            return WebEngineAttempt(
                trace_patch=self._trace_patch(
                    status="config_missing",
                    error_type="missing_env",
                    real_engine_called=False,
                    options=options,
                    extra={"missing_env": missing},
                )
            )

        try:
            engine = self._build_engine(options)
            symbols = self._load_internal_symbols()
            context = self._build_context(
                symbols=symbols,
                session_id=session_id,
                payload=payload,
                session_state=session_state,
                product_context=product_context,
            )
            started = time.perf_counter()
            result = asyncio.run(engine.run(context))
            elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
            response = self._response_from_result(
                symbols=symbols,
                result=result,
                session_id=session_id,
                payload=payload,
                session_state=session_state,
                product_context=product_context,
                product_anchor_source=product_anchor_source,
                options=options,
                adapter_latency_ms={"total": elapsed_ms, "engine": elapsed_ms},
            )
            return WebEngineAttempt(response=response)
        except Exception as exc:
            return WebEngineAttempt(
                trace_patch=self._trace_patch(
                    status="error",
                    error_type=type(exc).__name__,
                    real_engine_called=False,
                    options=options,
                    extra={"engine_adapter_error_summary": _sanitize_error(str(exc))},
                )
            )

    def _build_engine(self, options: WebEngineOptions) -> Any:
        if self._engine_factory is not None:
            return self._engine_factory(options)

        symbols = self._load_internal_symbols()
        intent_classifier = None
        answer_generator = None
        rag_retriever = None
        if options.use_real_llm or options.use_real_intent_classifier:
            intent_classifier = symbols["OpenAICompatibleIntentClassifier"](
                base_url=os.environ.get("AI_WORKFLOW_LLM_BASE_URL", ""),
                model=os.environ.get("AI_WORKFLOW_LLM_MODEL", ""),
                api_key_env="AI_WORKFLOW_LLM_API_KEY",
            )
        if options.use_real_llm or options.use_real_answer_generator:
            answer_generator = symbols["OpenAICompatibleAnswerGenerator"](
                base_url=os.environ.get("AI_WORKFLOW_LLM_BASE_URL", ""),
                model=os.environ.get("AI_WORKFLOW_LLM_MODEL", ""),
                api_key_env="AI_WORKFLOW_LLM_API_KEY",
            )
        if options.use_real_pgvector and options.use_real_ollama:
            rag_retriever = symbols["VectorStoreRAGRetriever"](
                embedding_client=symbols["OllamaBgeM3EmbeddingClient"](
                    base_url=os.environ.get("AI_WORKFLOW_OLLAMA_BASE_URL", ""),
                    model=os.environ.get("AI_WORKFLOW_EMBEDDING_MODEL", ""),
                ),
                vector_store=symbols["PgVectorStore"](os.environ.get("AI_WORKFLOW_PGVECTOR_DSN", "")),
                top_k=max(1, int(options.rag_top_k or 3)),
            )
        return symbols["InternalWorkflowEngine"](
            intent_classifier=intent_classifier,
            answer_generator=answer_generator,
            rag_retriever=rag_retriever,
            active_version_resolver=symbols["ActiveVersionResolver"](),
        )

    def _build_context(
        self,
        *,
        symbols: dict[str, Any],
        session_id: str,
        payload: LiveChatMessageRequest,
        session_state: Any,
        product_context: dict[str, Any] | None,
    ) -> Any:
        metadata = {
            **dict(payload.metadata or {}),
            "source": "web_api_live_chat",
            "no_send": True,
            "product_context": product_context or {},
            "product_version": payload.product_version,
            "sop_version": payload.sop_version,
        }
        history, product_card_injected = _history_with_product_card(
            list(getattr(session_state, "history", []) or []),
            product_context,
        )
        metadata["web_product_card_history_injected"] = product_card_injected
        return symbols["WorkflowContext"](
            trace_id=f"web-real-{uuid4().hex[:12]}",
            shop_id=payload.shop_id,
            user_id=str(payload.buyer_id or getattr(session_state, "buyer_id", "") or ""),
            customer_uid=str(payload.buyer_id or getattr(session_state, "buyer_id", "") or ""),
            buyer_id=str(payload.buyer_id or getattr(session_state, "buyer_id", "") or ""),
            session_id=session_id,
            chat_id=session_id,
            message_type="text",
            content=str(payload.message or ""),
            goods_context=product_context or None,
            history=history,
            metadata=metadata,
        )

    def _response_from_result(
        self,
        *,
        symbols: dict[str, Any],
        result: Any,
        session_id: str,
        payload: LiveChatMessageRequest,
        session_state: Any,
        product_context: dict[str, Any] | None,
        product_anchor_source: str,
        options: WebEngineOptions,
        adapter_latency_ms: dict[str, int] | None = None,
    ) -> LiveChatMessageResponse:
        action = symbols["action_value"](getattr(result, "action", "reply"))
        reply = str(getattr(result, "reply_text", "") or "")
        intent = str(getattr(result, "intent", "") or "fallback")
        base_trace = dict(getattr(result, "trace", {}) or {})
        domain = (
            base_trace.get("selected_domain")
            or base_trace.get("domain")
            or _domain_from_intent(intent)
        )
        retrieved_chunks = _safe_chunks(base_trace)
        latency_ms = _merge_latency(_latency_from_trace(base_trace), adapter_latency_ms)
        rag_hit_count = int(base_trace.get("rag_hit_count") or len(retrieved_chunks) or 0)
        session_history = list(getattr(session_state, "history", []) or [])
        _, product_card_injected = _history_with_product_card(session_history, product_context)
        effective_history_count = len(session_history) + (1 if product_card_injected else 0)
        chunk_warning = ""
        if rag_hit_count and not retrieved_chunks and options.use_real_pgvector and product_context:
            retrieved_chunks, chunk_warning = self._load_debug_chunks(
                payload=payload,
                product_context=product_context,
                domain=str(domain or "product_catalog"),
                options=options,
            )
        trace = {
            **base_trace,
            "trace_id": base_trace.get("trace_id") or f"web-real-{uuid4().hex[:12]}",
            "engine": "internal",
            "engine_mode": "real_internal",
            "engine_adapter_status": "ok",
            "engine_adapter_error_type": "",
            "real_engine_called": True,
            "product_context_forwarded": bool(product_context),
            "buyer_message": str(payload.message or ""),
            "ai_reply": reply,
            "prompt": str(base_trace.get("prompt") or base_trace.get("answer_prompt") or ""),
            "raw_response": str(base_trace.get("raw_response") or reply),
            "retrieved_chunks": retrieved_chunks,
            "retrieved_chunks_unavailable": bool(rag_hit_count and not retrieved_chunks),
            "retrieved_chunks_unavailable_reason": (
                chunk_warning or "engine_trace_omitted_chunks" if rag_hit_count and not retrieved_chunks else ""
            ),
            "rag_query": str(base_trace.get("rag_query") or base_trace.get("query") or payload.message or ""),
            "product_context": product_context or {},
            "product_context_status": "resolved" if product_context else "none",
            "product_anchor_source": product_anchor_source,
            "history_message_count": int(base_trace.get("history_message_count") or effective_history_count),
            "history_has_product_card": bool(base_trace.get("history_has_product_card") or bool(product_context)),
            "web_product_card_history_injected": product_card_injected,
            "rag_status": str(base_trace.get("rag_status") or "disabled"),
            "rag_hit_count": rag_hit_count,
            "rag_domains": [domain] if domain else [],
            "answer_generation_status": str(base_trace.get("answer_generation_status") or base_trace.get("llm_answer_status") or ""),
            "guardrail_status": str(base_trace.get("guardrail_status") or "safe"),
            "calls_llm": bool(base_trace.get("calls_llm") or options.use_real_llm or options.use_real_intent_classifier or options.use_real_answer_generator),
            "calls_ollama": bool(base_trace.get("calls_ollama") or options.use_real_ollama),
            "connects_pgvector": bool(base_trace.get("connects_pgvector") or options.use_real_pgvector),
            "sends_pdd": False,
            "no_send": True,
            **self._trace_patch("ok", "", True, options, extra={"latency_ms": latency_ms}),
        }
        return LiveChatMessageResponse(
            reply=reply,
            action=action,
            intent=intent,
            domain=str(domain) if domain else None,
            session_id=session_id,
            no_send=True,
            trace=_strip_secret_keys(trace),
        )

    def _load_debug_chunks(
        self,
        *,
        payload: LiveChatMessageRequest,
        product_context: dict[str, Any],
        domain: str,
        options: WebEngineOptions,
    ) -> tuple[list[dict[str, Any]], str]:
        goods_id = str(product_context.get("goods_id") or "")
        if not goods_id:
            return [], "missing_goods_id_for_chunk_debug"
        try:
            loader = self._chunk_loader or self._default_chunk_loader
            chunks, warning = loader(
                goods_id=goods_id,
                shop_id=payload.shop_id,
                version=options.product_version,
                domain=domain,
                source_type="product",
                limit=max(1, int(options.rag_top_k or 3)),
            )
            return _safe_chunks({"retrieved_chunks": [_model_dump(item) for item in chunks]}), str(warning or "")
        except Exception as exc:
            return [], f"chunk_debug_failed:{type(exc).__name__}"

    @staticmethod
    def _default_chunk_loader(**kwargs: Any) -> tuple[list[Any], str | None]:
        from web_api.services.rag_debug_service import RagDebugService

        return RagDebugService().list_product_chunks(**kwargs)

    @staticmethod
    def _missing_environment(options: WebEngineOptions) -> list[str]:
        missing: list[str] = []
        if options.use_real_pgvector and not os.environ.get("AI_WORKFLOW_PGVECTOR_DSN"):
            missing.append("AI_WORKFLOW_PGVECTOR_DSN")
        if options.use_real_ollama:
            for key in ("AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL"):
                if not os.environ.get(key):
                    missing.append(key)
        if options.use_real_llm or options.use_real_intent_classifier or options.use_real_answer_generator:
            for key in ("AI_WORKFLOW_LLM_BASE_URL", "AI_WORKFLOW_LLM_MODEL", "AI_WORKFLOW_LLM_API_KEY"):
                if not os.environ.get(key):
                    missing.append(key)
        return missing

    @staticmethod
    def _trace_patch(
        status: str,
        error_type: str,
        real_engine_called: bool,
        options: WebEngineOptions,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        patch = {
            "smoke_profile": options.smoke_profile,
            "engine_mode": "real_internal" if real_engine_called else "facade",
            "engine_adapter_status": status,
            "engine_adapter_error_type": error_type,
            "real_engine_called": real_engine_called,
            "use_real_engine": options.use_real_engine,
            "use_real_pgvector": options.use_real_pgvector,
            "use_real_ollama": options.use_real_ollama,
            "use_real_llm": options.use_real_llm,
            "use_real_intent_classifier": options.use_real_intent_classifier,
            "use_real_answer_generator": options.use_real_answer_generator,
            "provider_status": _provider_status(status, real_engine_called, options, list((extra or {}).get("missing_env") or [])),
            "provider_error_type": error_type,
            "provider_error_summary": str((extra or {}).get("engine_adapter_error_summary") or ""),
            "stage_status": _stage_status(status, options),
            "latency_ms": _latency_from_extra(extra),
            "sends_pdd": False,
            "no_send": True,
        }
        if extra:
            patch.update(extra)
        return _strip_secret_keys(patch)

    @staticmethod
    def _load_internal_symbols() -> dict[str, Any]:
        import Session.session_manager  # noqa: F401 - required import order for existing package side effects.
        from Message.workflow.active_version import ActiveVersionResolver
        from Message.workflow.answer_generator import OpenAICompatibleAnswerGenerator
        from Message.workflow.embedding_client import OllamaBgeM3EmbeddingClient
        from Message.workflow.internal_engine import InternalWorkflowEngine
        from Message.workflow.llm_classifier import OpenAICompatibleIntentClassifier
        from Message.workflow.rag_retriever import VectorStoreRAGRetriever
        from Message.workflow.types import WorkflowContext, action_value
        from Message.workflow.vector_store import PgVectorStore

        return {
            "InternalWorkflowEngine": InternalWorkflowEngine,
            "ActiveVersionResolver": ActiveVersionResolver,
            "WorkflowContext": WorkflowContext,
            "OpenAICompatibleAnswerGenerator": OpenAICompatibleAnswerGenerator,
            "OpenAICompatibleIntentClassifier": OpenAICompatibleIntentClassifier,
            "OllamaBgeM3EmbeddingClient": OllamaBgeM3EmbeddingClient,
            "VectorStoreRAGRetriever": VectorStoreRAGRetriever,
            "PgVectorStore": PgVectorStore,
            "action_value": action_value,
        }


def _history_with_product_card(
    history: list[dict[str, Any]],
    product_context: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], bool]:
    if not product_context or not (product_context.get("goods_id") or product_context.get("goods_name")):
        return history, False
    if _has_product_card(history, product_context):
        return history, False
    return [_product_card_history_item(product_context), *history], True


def _has_product_card(history: list[dict[str, Any]], product_context: dict[str, Any]) -> bool:
    goods_id = str(product_context.get("goods_id") or "").strip()
    goods_name = str(product_context.get("goods_name") or product_context.get("product_name") or "").strip()
    for item in history:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        item_goods_id = str(item.get("goods_id") or "").strip()
        item_goods_name = str(item.get("goods_name") or item.get("product_name") or "").strip()
        if goods_id and (item_goods_id == goods_id or goods_id in content):
            return True
        if goods_name and (item_goods_name == goods_name or goods_name in content):
            return True
    return False


def _product_card_history_item(product_context: dict[str, Any]) -> dict[str, Any]:
    goods_id = str(product_context.get("goods_id") or "").strip()
    goods_name = str(product_context.get("goods_name") or product_context.get("product_name") or "").strip()
    goods_price = str(product_context.get("goods_price") or product_context.get("price") or "").strip()
    spec = str(product_context.get("spec") or product_context.get("sku") or product_context.get("specification") or "").strip()
    item = {
        "role": "buyer",
        "message_type": "product_card",
        "sub_type": "product_card",
        "content": _product_card_content(goods_name, goods_price, goods_id, spec),
        "goods_id": goods_id,
        "goods_name": goods_name,
        "product_name": goods_name,
        "goods_price": goods_price,
        "spec": spec,
        "product_context": dict(product_context),
        "source": "web_api_metadata",
    }
    return {key: value for key, value in item.items() if value not in ("", None, {})}


def _product_card_content(goods_name: str, goods_price: str, goods_id: str, spec: str) -> str:
    parts = []
    if goods_name:
        parts.append(f"\u5546\u54c1\uff1a{goods_name}")
    if spec:
        parts.append(f"\u89c4\u683c\uff1a{spec}")
    if goods_price:
        parts.append(f"\u4ef7\u683c\uff1a{goods_price}")
    if goods_id:
        parts.append(f"\u5546\u54c1ID\uff1a{goods_id}")
    return "\uff0c".join(parts)


def _options_from_payload(payload: LiveChatMessageRequest) -> WebEngineOptions:
    profile = str(payload.smoke_profile or "").strip()
    profile_options = _profile_option_overrides(profile)
    return WebEngineOptions(
        use_real_engine=bool(profile_options.get("use_real_engine", payload.use_real_engine)),
        use_real_pgvector=bool(profile_options.get("use_real_pgvector", payload.use_real_pgvector)),
        use_real_ollama=bool(profile_options.get("use_real_ollama", payload.use_real_ollama)),
        use_real_llm=bool(profile_options.get("use_real_llm", payload.use_real_llm)),
        use_real_intent_classifier=bool(profile_options.get("use_real_intent_classifier", payload.use_real_intent_classifier)),
        use_real_answer_generator=bool(profile_options.get("use_real_answer_generator", payload.use_real_answer_generator)),
        product_version=str(payload.product_version or "real-product-v1"),
        sop_version=str(payload.sop_version or "sop-test-v1"),
        rag_top_k=max(1, int(payload.rag_top_k or 3)),
        smoke_profile=profile,
    )


def _profile_option_overrides(profile: str) -> dict[str, bool]:
    if profile == "facade":
        return {}
    if profile == "real_engine_only":
        return {
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": False,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": False,
        }
    if profile == "real_rag":
        return {
            "use_real_engine": True,
            "use_real_pgvector": True,
            "use_real_ollama": True,
            "use_real_llm": False,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": False,
        }
    if profile == "real_intent":
        return {
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": True,
            "use_real_intent_classifier": True,
            "use_real_answer_generator": False,
        }
    if profile == "real_answer":
        return {
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": True,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": True,
        }
    if profile == "real_full":
        return {
            "use_real_engine": True,
            "use_real_pgvector": True,
            "use_real_ollama": True,
            "use_real_llm": True,
            "use_real_intent_classifier": True,
            "use_real_answer_generator": True,
        }
    return {}


def _provider_status(status: str, real_engine_called: bool, options: WebEngineOptions, missing_env: list[str]) -> dict[str, str]:
    missing = set(missing_env)
    llm_missing = bool({"AI_WORKFLOW_LLM_BASE_URL", "AI_WORKFLOW_LLM_MODEL", "AI_WORKFLOW_LLM_API_KEY"} & missing)
    pg_missing = "AI_WORKFLOW_PGVECTOR_DSN" in missing
    ollama_missing = bool({"AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL"} & missing)
    return {
        "real_engine": "ok" if real_engine_called else ("config_missing" if status == "config_missing" else "skipped"),
        "pgvector": "config_missing" if options.use_real_pgvector and pg_missing else ("enabled" if options.use_real_pgvector and real_engine_called else "disabled"),
        "ollama": "config_missing" if options.use_real_ollama and ollama_missing else ("enabled" if options.use_real_ollama and real_engine_called else "disabled"),
        "llm": "config_missing" if (options.use_real_llm or options.use_real_intent_classifier or options.use_real_answer_generator) and llm_missing else ("enabled" if (options.use_real_llm or options.use_real_intent_classifier or options.use_real_answer_generator) and real_engine_called else "disabled"),
        "intent_classifier": "config_missing" if options.use_real_intent_classifier and llm_missing else ("enabled" if options.use_real_intent_classifier and real_engine_called else "disabled"),
        "answer_generator": "config_missing" if options.use_real_answer_generator and llm_missing else ("enabled" if options.use_real_answer_generator and real_engine_called else "disabled"),
    }


def _stage_status(status: str, options: WebEngineOptions) -> dict[str, str]:
    if status == "config_missing":
        return {
            "context": "ok",
            "routing": "fallback",
            "rag": "config_missing" if options.use_real_pgvector or options.use_real_ollama else "skipped",
            "intent": "config_missing" if options.use_real_intent_classifier else "skipped",
            "answer": "config_missing" if options.use_real_answer_generator else "skipped",
            "guardrail": "skipped",
        }
    return {
        "context": "ok",
        "routing": "ok" if status == "ok" else "fallback",
        "rag": "ok" if options.use_real_pgvector or options.use_real_ollama else "skipped",
        "intent": "ok" if options.use_real_intent_classifier else "skipped",
        "answer": "ok" if options.use_real_answer_generator else "skipped",
        "guardrail": "ok" if status == "ok" else "skipped",
    }


def _latency_from_extra(extra: dict[str, Any] | None) -> dict[str, int]:
    latency = (extra or {}).get("latency_ms")
    if isinstance(latency, dict):
        return {str(key): int(value or 0) for key, value in latency.items()}
    return {"total": 0, "engine": 0, "rag": 0, "llm": 0, "guardrail": 0}


def _domain_from_intent(intent: str) -> str | None:
    return {
        "product_basic": "product_catalog",
        "logistics_order_status": "logistics_policy",
        "after_sales_evidence_collection": "after_sales_evidence",
        "promotion_policy": "promotion_policy",
        "sensitive_user_safety": "sensitive_user_safety",
        "human_escalation_redline": "redline_escalation",
        "explicit_human_request": "redline_escalation",
    }.get(str(intent or ""))


def _safe_chunks(trace: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (
        trace.get("retrieved_chunks")
        or trace.get("rag_hits")
        or trace.get("knowledge_hits")
        or trace.get("rag_results")
        or trace.get("retrieval_results")
        or trace.get("chunks")
        or trace.get("top_k_chunks")
        or []
    )
    if not isinstance(raw, list):
        return []
    chunks: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            chunks.append(_strip_secret_keys(item))
    return chunks


def _model_dump(item: Any) -> Any:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    return item


def _latency_from_trace(trace: dict[str, Any]) -> dict[str, int]:
    for key in ("latency_ms", "stage_latency_ms", "latency_breakdown", "stage_latency"):
        latency = trace.get(key)
        if isinstance(latency, dict):
            return {str(item_key): int(item_value or 0) for item_key, item_value in latency.items()}
    return {"total": 0, "engine": 0, "rag": 0, "llm": 0, "guardrail": 0}


def _merge_latency(trace_latency: dict[str, int], adapter_latency: dict[str, int] | None) -> dict[str, int]:
    merged = dict(trace_latency or {})
    adapter_latency = adapter_latency or {}
    adapter_total = int(adapter_latency.get("total") or 0)
    adapter_engine = int(adapter_latency.get("engine") or adapter_total or 0)
    if int(merged.get("total") or 0) <= 0 and adapter_total > 0:
        merged["total"] = adapter_total
    if int(merged.get("engine") or 0) <= 0 and adapter_engine > 0:
        merged["engine"] = adapter_engine
    for key in ("rag", "llm", "guardrail"):
        merged.setdefault(key, 0)
    return {str(key): int(value or 0) for key, value in merged.items()}


def _strip_secret_keys(value: Any) -> Any:
    forbidden = {"api_key", "token", "cookie", "authorization", "password", "dsn", "access_token", "refresh_token"}
    if isinstance(value, dict):
        return {
            key: _strip_secret_keys(item)
            for key, item in value.items()
            if str(key).lower() not in forbidden
        }
    if isinstance(value, list):
        return [_strip_secret_keys(item) for item in value]
    if isinstance(value, str):
        return _sanitize_error(value)
    return value


def _sanitize_error(text: str) -> str:
    redacted = re.sub(r"postgresql://[^@\s]+@", "postgresql://<redacted>@", str(text or ""))
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer <redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"ark-[A-Za-z0-9._\-]+", "ark-<redacted>", redacted)
    return redacted[:4000]
