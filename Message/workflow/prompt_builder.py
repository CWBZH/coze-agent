"""Metadata-safe prompt builder for internal answer generation.

The builder prepares a structured prompt payload for an LLM adapter, but this
module does not call any provider. Callers must keep the payload out of normal
logs and artifacts; only the stable ``prompt_hash`` is meant for trace output.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


INTENT_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "logistics_order_status": (
        "物流订单查询：不要编造具体物流状态、快递单号或预计到达时间。",
        "可以引导买家查看订单物流页，必要时转人工核实。",
    ),
    "logistics_policy": (
        "物流订单查询：只回答通用物流规则，不要编造具体物流状态。",
    ),
    "after_sales_evidence_collection": (
        "售后取证处理：引导买家提供问题照片、外包装照片、订单信息和问题描述。",
        "不要承诺退款、补发、赔偿或换货结果。",
    ),
    "promotion_policy": (
        "优惠活动咨询：以商品页、活动页、优惠券页和结算页展示为准。",
        "不要承诺私下优惠、赠品、返差价或额外改价。",
    ),
    "human_escalation_redline": (
        "红线转人工：不要判断真假、责任、赔偿、投诉或平台处理结果。",
        "回复必须包含转人工含义。",
    ),
    "explicit_human_request": (
        "明确要求人工：直接转人工，不要继续自动劝说。",
    ),
    "sensitive_user_safety": (
        "敏感人群安全：用保守话术，不要做医疗、功效或绝对安全承诺。",
        "可以建议查看成分说明、咨询专业人士或转人工确认。",
    ),
    "product_basic": (
        "商品基础咨询：必须根据知识库结果回答商品价格、规格、用法、成分、保质期、香味等问题。",
        "价格必须以商品页面或结算页为准，不要编造商品事实或活动利益。",
        "\u7528\u6237\u95ee\u201c\u8fd9\u4e2a\u591a\u5c11\u94b1\u201d\u201c\u4ef7\u683c\u591a\u5c11\u201d\u65f6\uff0c\u5982\u679c\u5bf9\u8bdd\u4e0a\u4e0b\u6587\u6216\u77e5\u8bc6\u5e93\u660e\u786e\u6709 raw price / \u4ef7\u683c\uff0c\u53ef\u4ee5\u56de\u590d\u201c\u5f53\u524d\u5546\u54c1\u4fe1\u606f\u663e\u793a\u4ef7\u683c\u4e3a X\uff0c\u5b9e\u9645\u4ee5\u5546\u54c1\u9875\u9762\u548c\u4e0b\u5355\u7ed3\u7b97\u9875\u4e3a\u51c6\u201d\u3002",
        "\u7528\u6237\u95ee\u201c\u4ec0\u4e48\u89c4\u683c\u201d\u201c\u8fd9\u6b3e\u89c4\u683c\u201d\u65f6\uff0c\u5982\u679c\u6709 raw specs / sku \u4fe1\u606f\uff0c\u53ef\u4ee5\u56de\u590d\u201c\u5f53\u524d\u5546\u54c1\u4fe1\u606f\u663e\u793a\u89c4\u683c\u4e3a X\uff0c\u5177\u4f53\u4ee5\u5546\u54c1\u9875\u9762\u4e3a\u51c6\u201d\u3002",
        "\u7528\u6237\u95ee\u201c\u600e\u4e48\u7528\u201d\u201c\u7528\u6cd5\u201d\u65f6\uff0c\u5982\u679c\u6709 usage/manual_override \u6216\u7528\u6cd5\u8bf4\u660e\uff0c\u5fc5\u987b\u5148\u590d\u8ff0\u8be5\u7528\u6cd5\uff0c\u4e0d\u8981\u53ea\u56de\u590d\u201c\u4ee5\u5546\u54c1\u8be6\u60c5\u9875\u4e3a\u51c6\u201d\uff1b\u53ef\u5728\u672b\u5c3e\u8865\u5145\u5177\u4f53\u4ee5\u5546\u54c1\u8be6\u60c5\u9875\u8bf4\u660e\u4e3a\u51c6\u3002",
        "\u4e0d\u5141\u8bb8\u627f\u8bfa\u6700\u7ec8\u6210\u4ea4\u4ef7\u3001\u79c1\u4e0b\u4f18\u60e0\u3001\u8d60\u54c1\u3001\u5305\u90ae\u6216\u8fd4\u5dee\u4ef7\u3002",
    ),
}


@dataclass(frozen=True)
class PromptPayload:
    system_instructions: tuple[str, ...] = field(default_factory=tuple)
    context_blocks: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    user_task: str = ""
    conversation_text: str = ""
    output_format: str = "输出就是要发给买家的客服回复。"
    redaction_summary: dict[str, Any] = field(default_factory=dict)
    prompt_hash: str = ""
    context_block_count: int = 0
    constraint_count: int = 0
    used_history_count: int = 0
    used_rag_hit_count: int = 0


def build_prompt_payload(
    *,
    intent: str,
    query_summary: str = "",
    history_window: Iterable[Mapping[str, Any]] | None = None,
    product_hits: Iterable[Any] | None = None,
    sop_records: Iterable[Any] | None = None,
    product_context: Mapping[str, Any] | None = None,
    constraints: Iterable[str] | None = None,
    forbidden_phrases: Iterable[str] | None = None,
) -> PromptPayload:
    """Build a deterministic prompt payload from sanitized summaries."""

    history = list(history_window or [])
    hits = list(product_hits or [])
    records = list(sop_records or [])
    conversation_history = list(history)
    if product_context:
        conversation_history = [dict(product_context, role="buyer", message_type="product_context")] + conversation_history
    conversation_text = format_conversation_text(history=conversation_history, current_message=query_summary)
    all_constraints = _unique(
        (
            "你是拼多多店铺客服助手，请根据【对话上下文】和【知识库结果】回答【当前消息】。",
            "只回答当前消息，不顺带回答其它问题。",
            "优先根据知识库和上下文回答，不要编造具体事实。",
            "商品咨询可以结合商品标题、规格和知识库内容做自然介绍；如果标题中包含功效、适用场景、香型、颜色、规格等信息，可以适当转述和推荐，但不要做绝对承诺，例如“保证有效”“一定适合”“百分百安全”“一定不过敏”。",
            "价格、优惠以商品页面或结算页为准；物流以订单物流页为准；使用方法以商品详情页说明为准。",
            "售后问题先引导用户提供照片、包装、订单信息和问题描述，不承诺退款、补发、赔偿或换货结果。",
            "孕妇、儿童、过敏、敏感肌等安全问题，不做确定性承诺，可建议查看成分说明、咨询专业人士或转人工确认。",
            "遇到假货、投诉、差评、赔偿、12315、法律责任、明确要求人工，回复“亲亲，这个问题我帮您转人工处理哦”。",
            "如果上下文和知识库都无法支持安全回答，再转人工确认。",
            "回复要像真人客服，亲切、自然、简洁，30字以内。",
            "不要暴露AI，不要提知识库/RAG/prompt，不要输出Product/Goods ID/Specifications等工程字段。",
            *INTENT_CONSTRAINTS.get(str(intent or ""), ()),
            *(str(item) for item in (constraints or ()) if str(item or "").strip()),
        )
    )
    context_blocks = (
        {
            "type": "history",
            "count": len(history),
            "items": [
                {
                    "role": str(item.get("role") or ""),
                    "message_type": str(item.get("message_type") or ""),
                    "content": str(item.get("content") or "")[:1200],
                    "content_summary": str(item.get("content_summary") or ""),
                    "content_hash": str(item.get("content_hash") or ""),
                }
                for item in history[-6:]
            ],
        },
        {
            "type": "product_context",
            "count": 1 if product_context else 0,
            "items": [_safe_product_context(product_context)] if product_context else [],
        },
        {
            "type": "product_knowledge",
            "count": len(hits),
            "items": [_safe_hit_ref(hit) for hit in hits[:3]],
        },
        {
            "type": "sop",
            "count": len(records),
            "items": [_safe_sop_ref(record) for record in records[:3]],
        },
    )
    redaction_summary = {
        "query_summary_length": len(str(query_summary or "")),
        "query_summary_hash": _short_hash(str(query_summary or "")) if query_summary else "",
        "history_count": len(history),
        "product_context_status": str((product_context or {}).get("status") or "") if isinstance(product_context, Mapping) else "",
        "product_hit_count": len(hits),
        "sop_record_count": len(records),
        "forbidden_phrase_count": len([item for item in (forbidden_phrases or ()) if str(item or "").strip()]),
    }
    payload_without_hash = {
        "system_instructions": all_constraints,
        "context_blocks": context_blocks,
        "conversation_text": conversation_text,
        "user_task": str(query_summary or ""),
        "output_format": "输出就是要发给买家的客服回复。不要输出引用标记、Markdown表格、工程字段或分析。",
        "redaction_summary": redaction_summary,
    }
    prompt_hash = _short_hash(json.dumps(payload_without_hash, ensure_ascii=False, sort_keys=True))
    return PromptPayload(
        system_instructions=all_constraints,
        context_blocks=context_blocks,
        user_task=str(query_summary or ""),
        conversation_text=conversation_text,
        output_format="输出就是要发给买家的客服回复。不要输出引用标记、Markdown表格、工程字段或分析。",
        redaction_summary=redaction_summary,
        prompt_hash=prompt_hash,
        context_block_count=len(context_blocks),
        constraint_count=len(all_constraints),
        used_history_count=len(history),
        used_rag_hit_count=len(hits) + len(records),
    )


def format_conversation_text(
    context: Any | None = None,
    *,
    history: Iterable[Mapping[str, Any]] | None = None,
    current_message: str = "",
    max_history: int = 20,
    compress_early_count: int = 10,
) -> str:
    """Render FastGPT-style Chinese conversation text for prompts and RAG.

    This string may contain buyer wording and product card text. It is for
    provider prompts only and must not be written to normal logs or artifacts.
    """

    if context is not None:
        if history is None:
            history = getattr(context, "history", None)
        if not current_message:
            current_message = str(getattr(context, "content", "") or "")

    items = [item for item in list(history or []) if isinstance(item, Mapping)]
    context_product = _context_product_item(context) if context is not None else {}
    if context_product and not _has_same_product(items, context_product):
        items = [context_product, *items]
    if max_history > 0 and len(items) > max_history:
        count = max(1, int(compress_early_count or 10))
        early = items[:count]
        rest = items[count:]
        items = [_compressed_history_item(early), *rest]
    lines = ["前文摘要:"]
    if not items:
        lines.append("无")
    else:
        for item in items:
            rendered = _render_history_line(item)
            if rendered:
                lines.append(rendered)
    lines.append("")
    lines.append(f"当前消息: {_content_with_prefix(current_message)}")
    return "\n".join(lines)


def _compressed_history_item(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    product_lines: list[str] = []
    buyer_lines: list[str] = []
    service_lines: list[str] = []
    for item in items:
        product_line = _product_line(item)
        if product_line and product_line not in product_lines:
            product_lines.append(product_line)
        rendered = _render_history_line(item)
        if not rendered:
            continue
        if rendered.startswith("客服:"):
            service_lines.append(rendered.replace("客服:", "", 1).strip())
        elif not product_line:
            buyer_lines.append(rendered.replace("买家:", "", 1).strip())

    parts = [f"较早对话摘要：共{len(items)}条。"]
    if product_lines:
        parts.append("商品信息：" + "；".join(product_lines[:3]) + "。")
    if buyer_lines:
        parts.append("买家曾提到：" + "；".join(buyer_lines[:3]) + "。")
    if service_lines:
        parts.append("客服曾回复：" + "；".join(service_lines[:2]) + "。")
    return {
        "role": "system",
        "message_type": "history_summary",
        "content": "".join(parts),
    }


def _render_history_line(item: Mapping[str, Any]) -> str:
    role = _role_name(str(item.get("role") or ""))
    product_line = _product_line(item)
    if product_line:
        return f"{role}: {product_line}"
    content = str(item.get("content") or item.get("message") or item.get("text") or "").strip()
    if not content:
        return ""
    if role == "买家":
        return f"{role}: {_content_with_prefix(content)}"
    return f"{role}: {content}"


def _context_product_item(context: Any) -> dict[str, Any]:
    metadata = getattr(context, "metadata", None)
    metadata = metadata if isinstance(metadata, Mapping) else {}
    goods_context = getattr(context, "goods_context", None)
    candidates = []
    if isinstance(goods_context, Mapping):
        candidates.append(goods_context)
    product_context = metadata.get("product_context")
    if isinstance(product_context, Mapping):
        candidates.append(product_context)
    for candidate in candidates:
        goods_id = str(candidate.get("goods_id") or candidate.get("goodsID") or candidate.get("goodsId") or "").strip()
        goods_name = str(candidate.get("goods_name") or candidate.get("product_name") or candidate.get("goodsName") or "").strip()
        if goods_id or goods_name:
            return {
                "role": "buyer",
                "message_type": "product_context",
                "goods_id": goods_id,
                "goods_name": goods_name,
                "goods_price": str(candidate.get("goods_price") or candidate.get("price") or "").strip(),
                "spec": str(candidate.get("spec") or candidate.get("specifications") or "").strip(),
            }
    return {}


def _has_same_product(items: list[Mapping[str, Any]], product: Mapping[str, Any]) -> bool:
    product_id = str(product.get("goods_id") or "").strip()
    product_name = str(product.get("goods_name") or "").strip()
    for item in items:
        item_id = str(item.get("goods_id") or item.get("goodsID") or item.get("goodsId") or "").strip()
        item_name = str(item.get("goods_name") or item.get("product_name") or "").strip()
        if product_id and item_id == product_id:
            return True
        if product_name and item_name == product_name:
            return True
    return False


def _product_line(item: Mapping[str, Any]) -> str:
    content = str(item.get("content") or "").strip()
    goods_name = str(item.get("goods_name") or item.get("product_name") or "").strip()
    goods_id = str(item.get("goods_id") or item.get("goodsID") or item.get("goodsId") or "").strip()
    goods_price = str(item.get("goods_price") or item.get("price") or "").strip()
    spec = str(item.get("spec") or item.get("sku") or "").strip()
    if not goods_name and content.startswith("商品："):
        return content
    if not goods_name and not goods_id:
        return ""
    parts = [f"商品：{goods_name}" if goods_name else "商品："]
    if spec:
        parts.append(f"规格：{spec}")
    if goods_price:
        parts.append(f"价格：{goods_price}")
    if goods_id:
        parts.append(f"商品ID：{goods_id}")
    return "，".join(parts)


def _role_name(role: str) -> str:
    text = str(role or "").strip().lower()
    if text in {"assistant", "seller", "service", "客服", "cs"}:
        return "客服"
    return "买家"


def _content_with_prefix(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return "内容："
    if text.startswith("内容：") or text.startswith("商品："):
        return text
    return f"内容：{text}"


def _safe_hit_ref(hit: Any) -> dict[str, Any]:
    if isinstance(hit, Mapping):
        title = str(hit.get("title") or hit.get("goods_name") or "")
        source = str(hit.get("source") or "")
        domain = str(hit.get("domain") or "")
    else:
        title = str(getattr(hit, "title", "") or "")
        source = str(getattr(hit, "source", "") or "")
        domain = str(getattr(hit, "domain", "") or "")
    return {
        "source": source,
        "domain": domain,
        "title_hash": _short_hash(title) if title else "",
        "content": str(_record_value(hit, "content_summary") or _record_value(hit, "approved_answer") or _record_value(hit, "content") or "")[:1200],
    }


def _safe_product_context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        return {}
    product_name = str(context.get("product_name") or context.get("goods_name") or "")
    goods_id = str(context.get("goods_id") or "")
    return {
        "status": str(context.get("status") or ""),
        "source": str(context.get("source") or ""),
        "goods_id_hash": _short_hash(goods_id) if goods_id else "",
        "product_name_hash": _short_hash(product_name) if product_name else "",
    }


def _safe_sop_ref(record: Any) -> dict[str, Any]:
    return {
        "id": str(_record_value(record, "id") or _record_value(record, "record_id") or _record_value(record, "kb_item_id") or ""),
        "domain": str(_record_value(record, "domain") or ""),
        "version": str(_record_value(record, "version") or ""),
    }


def _record_value(record: Any, key: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(key)
    return getattr(record, key, None)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]
