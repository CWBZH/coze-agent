"""Offline answer generation primitives for the internal workflow backend."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass
class AnswerGenerationContext:
    intent: str = ""
    action_hint: str = ""
    query_summary: str = ""
    history_window: list[dict[str, Any]] = field(default_factory=list)
    product_hits: list[Any] = field(default_factory=list)
    sop_records: list[Any] = field(default_factory=list)
    product_context: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    forbidden_phrases: list[str] = field(default_factory=list)
    workflow_version: str = ""
    sop_version: str = ""
    knowledge_version: str = ""
    trace_id: str = ""
    prompt_hash: str = ""
    conversation_text: str = ""


@dataclass
class AnswerDraft:
    text: str = ""
    confidence: float = 0.0
    source: str = ""
    used_knowledge_refs: list[dict[str, Any]] = field(default_factory=list)
    used_sop_domains: list[str] = field(default_factory=list)
    used_history_count: int = 0
    risk_flags: list[str] = field(default_factory=list)
    raw_error_type: str = ""
    raw_error_summary: str = ""
    http_status: int | None = None
    provider_host: str = ""
    provider_model: str = ""
    timeout_ms: int = 0
    response_length: int = 0
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AnswerGenerator:
    def generate(self, context: AnswerGenerationContext) -> AnswerDraft:
        raise NotImplementedError


class NullAnswerGenerator(AnswerGenerator):
    def generate(self, context: AnswerGenerationContext) -> AnswerDraft:
        del context
        return AnswerDraft(source="null", raw_error_type="answer_generator_disabled")


class FakeAnswerGenerator(AnswerGenerator):
    """Deterministic fake generator for no-send tests and acceptance only."""

    def __init__(self, *, style: str = "conservative", dangerous: bool = False):
        self.style = style
        self.dangerous = dangerous
        self.calls: list[AnswerGenerationContext] = []

    def generate(self, context: AnswerGenerationContext) -> AnswerDraft:
        self.calls.append(context)
        if self.dangerous:
            text = "今天一定给您赔偿并补发。"
            risks = ["synthetic_dangerous_draft"]
        else:
            text = self._safe_text(context)
            risks = []
        return AnswerDraft(
            text=text,
            confidence=0.82,
            source="fake",
            used_knowledge_refs=self._knowledge_refs(context),
            used_sop_domains=self._sop_domains(context),
            used_history_count=len(context.history_window),
            risk_flags=risks,
        )

    def _safe_text(self, context: AnswerGenerationContext) -> str:
        intent = str(context.intent or "")
        query = str(context.query_summary or "")
        if intent in {"logistics_order_status", "logistics_policy"}:
            return "亲亲，具体物流进度请以订单物流页为准，如需核实订单可以帮您转人工确认。"
        if intent == "after_sales_evidence_collection":
            return "亲亲，请先提供破损照片、外包装照片和订单信息，我们会按凭证为您核实处理。"
        if intent == "promotion_policy":
            return "亲亲，优惠以商品页、活动页和结算页显示为准，暂不承诺额外私下优惠哦。"
        if intent in {"product_basic", "product_catalog"}:
            if any(token in query for token in ("多少钱", "价格", "价钱")):
                return "亲亲，这款商品价格请以商品页面和结算页显示为准哦。"
            if any(token in query for token in ("怎么用", "用法", "使用")):
                return "亲亲，这款商品的使用方法请以商品详情页说明为准，按页面提示使用就可以哦。"
            return "亲亲，这款商品信息请以商品页面说明为准，您也可以继续问我具体想了解的内容。"
        if intent == "sensitive_user_safety":
            return "亲亲，孕妇、儿童或敏感肌建议先查看成分说明，必要时咨询专业人士或转人工确认。"
        return "亲亲，这个问题我先帮您记录，如需进一步核实可以转人工处理。"

    @staticmethod
    def _knowledge_refs(context: AnswerGenerationContext) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for item in context.product_hits[:3]:
            if isinstance(item, dict):
                refs.append({"source": str(item.get("source") or ""), "title_hash": str(item.get("title_hash") or "")})
            else:
                refs.append({"source": str(getattr(item, "source", "") or ""), "title_hash": ""})
        return refs

    @staticmethod
    def _sop_domains(context: AnswerGenerationContext) -> list[str]:
        domains: list[str] = []
        for record in context.sop_records:
            domain = record.get("domain") if isinstance(record, dict) else getattr(record, "domain", "")
            domain_text = str(domain or "")
            if domain_text and domain_text not in domains:
                domains.append(domain_text)
        return domains


Transport = Callable[..., Mapping[str, Any]]


class OpenAICompatibleAnswerGenerator(AnswerGenerator):
    """OpenAI-compatible chat-completions adapter for explicit internal use."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env: str = "AI_WORKFLOW_LLM_API_KEY",
        timeout_seconds: float = 20,
        transport: Transport | None = None,
    ):
        self.base_url = str(base_url or "").rstrip("/")
        self.model = str(model or "")
        self.api_key_env = str(api_key_env or "AI_WORKFLOW_LLM_API_KEY")
        self.timeout_seconds = float(timeout_seconds or 20)
        self.transport = transport

    def generate(self, context: AnswerGenerationContext) -> AnswerDraft:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            return self._error("missing_api_key", "configured API key environment variable is missing")
        if not self.base_url or not self.model:
            return self._error("invalid_config", "LLM base URL and model are required")

        body = self._request_body(context)
        url = f"{self.base_url}/chat/completions"
        provider_host = _safe_provider_host(self.base_url)
        timeout_ms = int(self.timeout_seconds * 1000)
        started_at = time.perf_counter()
        try:
            if self.transport is not None:
                response = self.transport(
                    url=url,
                    headers={"Authorization": "<redacted>", "Content-Type": "application/json"},
                    body=body,
                    timeout_seconds=self.timeout_seconds,
                )
                http_status = _usage_int(response, "http_status") or 200
            else:
                response, http_status = self._post_json(url, api_key, body)
            text = self._extract_text(response)
            raw_response_length = len(json.dumps(response, ensure_ascii=False))
            usage = response.get("usage") if isinstance(response, Mapping) else {}
            usage = usage if isinstance(usage, Mapping) else {}
            prompt_tokens = _usage_int(usage, "prompt_tokens", "input_tokens")
            completion_tokens = _usage_int(usage, "completion_tokens", "output_tokens", "output_tokens_total")
            total_tokens = _usage_int(usage, "total_tokens") or (prompt_tokens + completion_tokens)
            return AnswerDraft(
                text=text,
                confidence=0.78 if text else 0.0,
                source="openai_compatible",
                used_history_count=len(context.history_window or []),
                raw_error_type="" if text else "empty_answer",
                raw_error_summary="" if text else "provider returned no answer text",
                http_status=http_status,
                provider_host=provider_host,
                provider_model=self.model,
                timeout_ms=timeout_ms,
                response_length=raw_response_length,
                latency_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except urllib.error.HTTPError as exc:
            return self._error(
                "HTTPError",
                f"provider http error status={int(getattr(exc, 'code', 0) or 0)}",
                http_status=int(getattr(exc, "code", 0) or 0) or None,
            )
        except (TimeoutError, socket.timeout) as exc:
            return self._error(type(exc).__name__, "provider request timed out")
        except (
            urllib.error.URLError,
            http.client.RemoteDisconnected,
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
        ) as exc:
            return self._error(type(exc).__name__, "provider disconnected during request")
        except Exception as exc:
            return self._error(type(exc).__name__, "provider request failed")

    def _request_body(self, context: AnswerGenerationContext) -> dict[str, Any]:
        system = "\n".join(str(item) for item in (context.constraints or []) if str(item or "").strip())
        knowledge_refs = [_safe_ref(item) for item in list(context.product_hits or [])[:5]]
        sop_refs = [_safe_ref(item) for item in list(context.sop_records or [])[:5]]
        conversation_text = str(context.conversation_text or "").strip() or str(context.query_summary or "").strip()
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system
                    or (
                        "你是拼多多店铺客服助手，请根据对话上下文和知识库结果回答当前消息。"
                        "回复要像真人客服，亲切、自然、简洁，30字以内。"
                        "商品咨询可结合标题和规格自然介绍，但不要做绝对承诺。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"【对话上下文】\n{conversation_text}\n\n"
                        f"【知识库结果】\n{_format_knowledge_results([*knowledge_refs, *sop_refs])}\n\n"
                        "【当前任务】\n"
                        "请只回答“当前消息”的问题。\n"
                        "可以在安全范围内结合商品标题、规格和知识库内容自然回答；如果上下文和知识库都无法支持安全回答，再转人工确认。\n\n"
                        "输出要求：\n"
                        "- 不要输出引用标记。\n"
                        "- 不要输出Markdown表格。\n"
                        "- 不要输出工程字段。\n"
                        "- 不要输出Product / Goods ID / Specifications这种英文工程文本。\n"
                        "- 输出就是要发给买家的客服回复。\n"
                    ),
                },
            ],
            "temperature": 0.2,
            "stream": False,
        }

    def _post_json(self, url: str, api_key: str, body: Mapping[str, Any]) -> tuple[Mapping[str, Any], int]:
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            return json.loads(response.read().decode("utf-8")), status

    @staticmethod
    def _extract_text(response: Mapping[str, Any]) -> str:
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, Mapping):
                message = first.get("message")
                if isinstance(message, Mapping):
                    return str(message.get("content") or "").strip()
                return str(first.get("text") or "").strip()
        return ""

    def _error(self, error_type: str, summary: str, *, http_status: int | None = None) -> AnswerDraft:
        return AnswerDraft(
            confidence=0.0,
            source="openai_compatible",
            raw_error_type=_sanitize_error_type(error_type),
            raw_error_summary=_sanitize_text(summary),
            http_status=http_status,
            provider_host=_safe_provider_host(self.base_url),
            provider_model=self.model,
            timeout_ms=int(self.timeout_seconds * 1000),
        )


def classify_answer_error(error_type: str, summary: str = "") -> str:
    """Map provider adapter errors to stable trace-safe categories."""
    value = _sanitize_error_type(error_type).lower()
    text = _sanitize_text(summary).lower()
    if not value:
        return "answer_generator_exception"
    if value in {"answer_generator_disabled", "not_configured", "disabled"}:
        return "answer_generator_not_configured"
    if value in {"missing_api_key", "invalid_config", "config_missing"}:
        return "answer_generator_config_missing"
    if value in {"empty_answer", "no_answer"}:
        return "answer_generator_empty_answer"
    if "timeout" in value or "timed out" in text:
        return "answer_generator_timeout"
    if value in {"httperror", "httpstatuserror"} or "http error" in text or "status=" in text:
        return "answer_generator_http_error"
    if (
        value in {"urlerror", "remotedisconnected", "connectionreseterror", "connectionabortederror", "brokenpipeerror"}
        or "disconnected" in text
        or "connection" in value
    ):
        return "answer_generator_provider_disconnected"
    if "json" in value or "parse" in value or "parser" in value:
        return "answer_generator_parser_error"
    return "answer_generator_exception"


def answer_hash(text: str) -> str:
    value = str(text or "")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else ""


def answer_preview(text: str, *, max_chars: int = 160) -> str:
    sanitized = _sanitize_text(str(text or ""))
    max_length = max(0, int(max_chars or 0))
    if not sanitized or max_length <= 0:
        return ""
    preview_length = min(max_length, 80, max(1, len(sanitized) // 2))
    return sanitized[:preview_length]


def _safe_ref(value: Any) -> dict[str, Any]:
    getter = value.get if isinstance(value, Mapping) else lambda key, default=None: getattr(value, key, default)
    title = str(getter("title", "") or getter("goods_name", "") or "")
    source_id = str(getter("source_id", "") or getter("goods_id", "") or "")
    return {
        "chunk_id": str(getter("chunk_id", "") or ""),
        "domain": str(getter("domain", "") or ""),
        "source_type": str(getter("source_type", "") or getter("source", "") or ""),
        "source_id_hash": answer_hash(source_id),
        "title_hash": answer_hash(title),
        "version": str(getter("version", "") or ""),
        "content_hash": str(getter("content_hash", "") or ""),
        "content": str(getter("content_summary", "") or getter("approved_answer", "") or getter("content", "") or "")[:400],
    }


def _format_knowledge_results(items: list[dict[str, Any]]) -> str:
    if not items:
        return "无"
    lines: list[str] = []
    for index, item in enumerate(items[:5], start=1):
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        domain = str(item.get("domain") or "")
        lines.append(f"{index}. domain={domain} 内容：{content[:400]}")
    return "\n".join(lines) if lines else "无"


def _safe_provider_host(base_url: str) -> str:
    parsed = urllib.parse.urlparse(str(base_url or ""))
    return parsed.hostname or ""


def _usage_int(source: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            value = source.get(key)
        except AttributeError:
            value = None
        if value is None or isinstance(value, bool):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _sanitize_error_type(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "error"))[:64] or "error"


def _sanitize_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?i)(token|cookie|access_token|authorization|api_key|secret)\s*[:=]\s*[^,\s]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._\-]+", "Bearer <redacted>", text)
    text = re.sub(r"ark-[A-Za-z0-9._\-]+", "ark-<redacted>", text)
    text = re.sub(r"fastgpt-[A-Za-z0-9._\-]+", "fastgpt-<redacted>", text)
    text = re.sub(r"postgresql://[^\s]+", "postgresql://<redacted>", text)
    return text.strip()
