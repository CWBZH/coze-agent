"""消息处理管道 - 串联关键词、FastGPT 和回复发送。"""
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any, Dict

from core.constants import TRANSFER_HUMAN_REPLY
from Message.handlers.fastgpt_handler import SYSTEM_PROMPT_TEMPLATE
from Message.workflow.router import create_ai_workflow_engine
from Message.workflow.types import WorkflowAction, WorkflowContext, action_value
from utils.logger_loguru import get_logger

logger = get_logger("MessagePipeline")

_INTERNAL_STAGE_TIMING_KEYS = (
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


def _fingerprint(value: Any) -> tuple[int, str]:
    value_text = "" if value is None else str(value)
    value_hash = hashlib.sha256(value_text.encode("utf-8")).hexdigest()[:12]
    return len(value_text), value_hash


def _trace_fields(trace: Dict[str, Any], **extra: Any) -> str:
    fields = {
        "trace_id": trace.get("trace_id", ""),
        "source_message_id": trace.get("source_message_id", ""),
        "queue_message_id": trace.get("queue_message_id", ""),
        "session_id": trace.get("session_id", ""),
        "shop_id": trace.get("shop_id", ""),
        "user_id": trace.get("user_id", ""),
        "customer_uid": trace.get("customer_uid", ""),
    }
    fields.update(extra)
    return " ".join(f"{key}={value}" for key, value in fields.items())


def _stage_timing_fields(trace: Dict[str, Any]) -> Dict[str, int]:
    timings = trace.get("stage_timing", {})
    if not isinstance(timings, dict):
        timings = {}
    result: Dict[str, int] = {}
    for key in _INTERNAL_STAGE_TIMING_KEYS:
        value = timings.get(key, trace.get(key, 0))
        try:
            result[key] = max(0, int(value or 0))
        except (TypeError, ValueError):
            result[key] = 0
    return result


def _contains_human_service_phrase(text: str) -> bool:
    value = str(text or "").lower()
    return any(term in value for term in ("人工", "客服", "human service", "manual service"))


def _extract_product_card_context(message: Dict[str, Any], buyer_text: Any) -> Dict[str, Any]:
    """Extract product card fields for the internal workflow only."""
    payload: Dict[str, Any] = {}
    if isinstance(message.get("metadata"), dict):
        payload.update(message["metadata"])
    for key in (
        "goods_id",
        "goods_name",
        "goods_price",
        "goods_thumb_url",
        "link_url",
        "spec",
        "sku_id",
        "sub_type",
        "raw_data",
    ):
        if message.get(key) is not None:
            payload[key] = message.get(key)

    content_payload = message.get("content")
    if isinstance(content_payload, dict):
        payload.update(content_payload)
    elif isinstance(buyer_text, str) and buyer_text.strip().startswith("{"):
        try:
            parsed = json.loads(buyer_text)
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            payload.update(parsed)

    raw_data = payload.get("raw_data")
    if isinstance(raw_data, str) and raw_data.strip().startswith("{"):
        try:
            raw_data = json.loads(raw_data)
        except (TypeError, ValueError):
            raw_data = {}
    if isinstance(raw_data, dict):
        info = raw_data.get("info") if isinstance(raw_data.get("info"), dict) else {}
        data = info.get("data") if isinstance(info.get("data"), dict) else {}
        for source, target in (
            ("goodsID", "goods_id"),
            ("goodsId", "goods_id"),
            ("goodsName", "goods_name"),
            ("goodsPrice", "goods_price"),
            ("goodsThumbUrl", "goods_thumb_url"),
            ("linkUrl", "link_url"),
            ("spec", "spec"),
        ):
            value = data.get(source) if source in data else info.get(source)
            if value is not None and not payload.get(target):
                payload[target] = value

    result = {
        "goods_id": payload.get("goods_id") or payload.get("goodsID") or payload.get("goodsId") or "",
        "goods_name": payload.get("goods_name") or payload.get("goodsName") or "",
        "goods_price": payload.get("goods_price") or payload.get("goodsPrice") or "",
        "goods_thumb_url": payload.get("goods_thumb_url") or payload.get("goodsThumbUrl") or "",
        "link_url": payload.get("link_url") or payload.get("linkUrl") or "",
        "spec": payload.get("spec") or payload.get("goods_spec") or "",
        "sku_id": payload.get("sku_id") or payload.get("skuId") or "",
        "sub_type": payload.get("sub_type") or payload.get("subType") or "",
        "raw_data": payload.get("raw_data") or "",
    }
    return {key: value for key, value in result.items() if value not in (None, "")}


def _extract_product_anchor_from_text(content: Any) -> Dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    result: Dict[str, Any] = {}
    goods_id = re.search(
        r"(?:goods[_\s-]*id|商品\s*ID|商品ID|goodsID|goodsId)\s*[:：=]\s*([A-Za-z0-9_-]{4,})",
        text,
        flags=re.IGNORECASE,
    )
    if goods_id:
        result["goods_id"] = goods_id.group(1).strip()
    goods_name = re.search(
        r"(?:商品|商品名称|goods[_\s-]*name|goodsName|Product)\s*[:：=]\s*([^，,。;\n\r]{2,80})",
        text,
        flags=re.IGNORECASE,
    )
    if goods_name:
        result["goods_name"] = goods_name.group(1).strip()
    goods_price = re.search(r"(?:价格|价钱|goodsPrice|Price)\s*[:：=]\s*([^，,。;\n\r]{1,40})", text, flags=re.IGNORECASE)
    if goods_price:
        result["goods_price"] = goods_price.group(1).strip()
    spec = re.search(r"(?:规格|spec)\s*[:：=]\s*([^，,。;\n\r]{1,80})", text, flags=re.IGNORECASE)
    if spec:
        result["spec"] = spec.group(1).strip()
    return result


def _safe_history_attr(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


class MessagePipeline:
    def __init__(
        self,
        db_manager,
        session_manager,
        keyword_handler,
        fastgpt_handler,
        config,
        workflow_engine=None,
    ):
        self.db = db_manager
        self.session_mgr = session_manager
        self.keyword_handler = keyword_handler
        self.fastgpt = fastgpt_handler
        self.workflow_engine = workflow_engine or create_ai_workflow_engine(fastgpt_handler=fastgpt_handler)
        if self.fastgpt is None and hasattr(self.workflow_engine, "fastgpt_handler"):
            self.fastgpt = self.workflow_engine.fastgpt_handler
        self.config = config
        self._product_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _product_cache_key(shop_id: Any, user_id: Any, buyer_id: Any, session_id: Any) -> str:
        return "|".join(str(part or "") for part in (shop_id, user_id, buyer_id, session_id))

    @staticmethod
    def _product_prompt_summary(product_context: Any) -> str:
        if not isinstance(product_context, dict) or not product_context:
            return ""
        parts = []
        if product_context.get("goods_name"):
            parts.append(str(product_context["goods_name"]))
        if product_context.get("goods_id"):
            parts.append(f"goods_id={product_context['goods_id']}")
        if product_context.get("spec"):
            parts.append(f"spec={product_context['spec']}")
        return " ".join(parts)

    def _workflow_history(self, session_id: str, product_context: Dict[str, Any] | None = None) -> list[Dict[str, Any]]:
        get_recent = getattr(self.session_mgr, "get_recent_messages", None)
        if not callable(get_recent):
            return []
        try:
            recent = list(get_recent(session_id, limit=40))
        except TypeError:
            recent = list(get_recent(session_id))
        except Exception:
            return []
        history: list[Dict[str, Any]] = []
        for item in recent:
            raw_metadata = _safe_history_attr(item, "metadata")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            entry = {
                "role": str(_safe_history_attr(item, "role") or ""),
                "content": str(_safe_history_attr(item, "content") or ""),
            }
            for key in (
                "message_type",
                "sub_type",
                "goods_id",
                "goods_name",
                "goods_price",
                "goods_thumb_url",
                "link_url",
                "spec",
                "sku_id",
                "raw_data",
                "product_metadata",
                "created_at",
            ):
                value = _safe_history_attr(item, key)
                if value in (None, "") and metadata:
                    value = metadata.get(key)
                if value not in (None, ""):
                    entry[key] = value

            parsed_anchor = _extract_product_anchor_from_text(entry.get("content", ""))
            for key, value in parsed_anchor.items():
                if value not in (None, "") and not entry.get(key):
                    entry[key] = value

            if metadata and "product_metadata" not in entry:
                product_metadata = {
                    key: metadata.get(key)
                    for key in (
                        "message_type",
                        "sub_type",
                        "goods_id",
                        "goods_name",
                        "goods_price",
                        "goods_thumb_url",
                        "link_url",
                        "spec",
                        "sku_id",
                    )
                    if metadata.get(key) not in (None, "")
                }
                if product_metadata:
                    entry["product_metadata"] = product_metadata

            has_product_card = bool(
                entry.get("goods_id")
                or entry.get("goods_name")
                or str(entry.get("message_type") or "") == "64"
                or entry.get("product_metadata")
                or entry.get("raw_data")
            )
            if has_product_card:
                entry["history_has_product_card"] = True
                product_entry = {
                    key: entry.get(key)
                    for key in (
                        "goods_id",
                        "goods_name",
                        "goods_price",
                        "goods_thumb_url",
                        "link_url",
                        "spec",
                        "sku_id",
                    )
                    if entry.get(key) not in (None, "")
                }
                if product_entry:
                    product_entry.setdefault("source", "history")
                    entry["product_context"] = product_entry
            history.append(entry)
        if product_context and history:
            for entry in reversed(history):
                if entry.get("role") == "user":
                    entry["product_context"] = dict(product_context)
                    entry["goods_id"] = product_context.get("goods_id", "")
                    entry["goods_name"] = product_context.get("goods_name", "")
                    entry["history_has_product_card"] = True
                    break
        return history

    @staticmethod
    def _workflow_history_summary(history: list[Dict[str, Any]]) -> Dict[str, Any]:
        latest_goods_id = ""
        latest_goods_name = ""
        history_has_product_card = False
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if entry.get("history_has_product_card"):
                history_has_product_card = True
            if entry.get("goods_id") or entry.get("goods_name"):
                latest_goods_id = str(entry.get("goods_id") or "")
                latest_goods_name = str(entry.get("goods_name") or "")
        return {
            "history_message_count": len(history),
            "history_has_product_card": history_has_product_card,
            "latest_history_goods_id_hash": hashlib.sha256(latest_goods_id.encode("utf-8")).hexdigest()[:12]
            if latest_goods_id
            else "",
            "latest_history_goods_name_hash": hashlib.sha256(latest_goods_name.encode("utf-8")).hexdigest()[:12]
            if latest_goods_name
            else "",
        }

    def _alert_transfer_human(
        self,
        shop_id: str,
        buyer_id: str,
        session_id: str,
        reason: str,
        alert_level: str = "high",
        metadata: Dict[str, Any] = None,
    ) -> None:
        """触发转人工 UI 告警和提示音。"""
        try:
            from core.di_container import container
            from core.notification import NotificationService

            notification_service = container.get(NotificationService)
            if notification_service:
                alert_metadata = dict(metadata or {})
                alert_metadata.setdefault("session_id", session_id)
                alert_metadata.setdefault("shop_id", shop_id)
                alert_metadata.setdefault("customer_uid", buyer_id)
                alert_metadata.setdefault("action", "transfer_human")
                try:
                    notification_service.alert_human_fallback(
                        shop_id=shop_id,
                        user_id=buyer_id,
                        reason=reason,
                        alert_level=alert_level,
                        metadata=alert_metadata,
                    )
                except TypeError:
                    notification_service.alert_human_fallback(
                        shop_id=shop_id,
                        user_id=buyer_id,
                        reason=reason,
                        alert_level=alert_level,
                    )
        except Exception as e:
            logger.warning(f"转人工通知触发失败: {e}")

    async def process(
        self,
        message: Dict[str, Any],
        trace_id: str = None,
        source_message_id: str = None,
        queue_message_id: str = None,
    ) -> Dict[str, Any]:
        process_started_at = time.perf_counter()
        buyer_id = message.get("buyer_id")
        shop_platform_id = message.get("shop_platform_id")
        buyer_text = message.get("content", "")
        user_id = message.get("user_id", "")
        content_length, content_hash = _fingerprint(buyer_text)
        trace = {
            "trace_id": str(trace_id or message.get("trace_id") or ""),
            "source_message_id": str(source_message_id or message.get("source_message_id") or ""),
            "queue_message_id": str(queue_message_id or message.get("queue_message_id") or ""),
            "session_id": str(message.get("session_id") or ""),
            "shop_id": str(shop_platform_id or "unknown"),
            "user_id": str(user_id or ""),
            "customer_uid": str(buyer_id or ""),
        }

        def alert_metadata(action: str, reply: Any = None, final_status: str = "") -> Dict[str, Any]:
            metadata = dict(trace)
            metadata.update(
                {
                    "action": action,
                    "message_type": str(message.get("message_type") or "text"),
                    "content_length": content_length,
                    "content_hash": content_hash,
                    "buyer_message_preview": buyer_text,
                }
            )
            if final_status:
                metadata["final_status"] = final_status
            if reply is not None:
                reply_length, reply_hash = _fingerprint(reply)
                metadata["seller_or_ai_reply_preview"] = reply
                metadata["reply_length"] = reply_length
                metadata["reply_hash"] = reply_hash
            return metadata

        if not buyer_id or not buyer_text:
            duration_ms = int((time.perf_counter() - process_started_at) * 1000)
            logger.info(
                "event=pdd.message.skipped "
                + _trace_fields(
                    trace,
                    action="missing_buyer_or_content",
                    duration_ms=duration_ms,
                    content_length=content_length,
                    content_hash=content_hash,
                )
            )
            logger.warning("消息缺少 buyer_id 或 content")
            return {"action": "skip"}

        shop = self.db.get_shop_by_platform_id("pinduoduo", shop_platform_id)
        if not shop:
            duration_ms = int((time.perf_counter() - process_started_at) * 1000)
            logger.info(
                "event=pdd.message.skipped "
                + _trace_fields(
                    trace,
                    action="shop_not_found",
                    duration_ms=duration_ms,
                    content_length=content_length,
                    content_hash=content_hash,
                )
            )
            logger.error(f"店铺未找到: {shop_platform_id}")
            return {"action": "skip"}

        session_id = None
        try:
            conv = await self.session_mgr.get_or_create_conversation(shop["id"], buyer_id, user_id)
            session_id = conv.session_id
            trace["session_id"] = str(session_id or "")
            trace["shop_id"] = str(shop.get("shop_id") or shop_platform_id or "unknown")

            if conv.status in ("pending_human", "human_handling"):
                fallback_state = self.session_mgr.get_fallback_state(session_id)
                reminder_stage = self.session_mgr.should_send_fallback(session_id)
                if (
                    conv.status == "pending_human"
                    and fallback_state.get("first_sent_at")
                    and reminder_stage == "second"
                ):
                    reminder = self.fastgpt.get_fallback(session_id, already_failed=False)
                    self.session_mgr.mark_fallback_sent(session_id, reminder_stage)
                    self.session_mgr.add_message(session_id, "assistant", reminder)
                    reply_length, reply_hash = _fingerprint(reminder)
                    duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                    logger.info(
                        "event=pdd.pipeline.completed "
                        + _trace_fields(
                            trace,
                            action=f"pending_human_{reminder_stage}_fallback",
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    logger.info(
                        f"会话 {session_id[:8]} 处于人工状态，发送第 {reminder_stage} 次 fallback 提醒"
                    )
                    return {
                        "action": "reply",
                        "text": reminder,
                        "session_id": session_id,
                        "source": f"pending_human_{reminder_stage}_fallback",
                    }
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.human_lock.skipped "
                    + _trace_fields(
                        trace,
                        action=str(conv.status),
                        duration_ms=duration_ms,
                    )
                )
                logger.info(
                    "event=pdd.message.skipped "
                    + _trace_fields(
                        trace,
                        action=str(conv.status),
                        duration_ms=duration_ms,
                    )
                )
                logger.info(f"会话 {session_id[:8]} 处于人工状态，跳过自动回复")
                return {"action": "skip", "session_id": session_id, "status": conv.status}

            product_card_context = _extract_product_card_context(message, buyer_text)
            product_cache_key = self._product_cache_key(
                shop.get("shop_id") or shop_platform_id,
                user_id,
                buyer_id,
                session_id,
            )
            cached_product_context = dict(self._product_cache.get(product_cache_key) or {})
            product_context_inherited = False
            product_context_age_messages = 0
            if product_card_context:
                cached_product_context = {
                    **product_card_context,
                    "source": "message_card",
                    "_age_messages": 0,
                }
                self._product_cache[product_cache_key] = dict(cached_product_context)
            elif cached_product_context:
                product_context_inherited = True
                product_context_age_messages = int(cached_product_context.get("_age_messages") or 0) + 1
                cached_product_context["_age_messages"] = product_context_age_messages
                cached_product_context["source"] = "memory_cache"
                cached_product_context["inherited"] = True
                cached_product_context["age_messages"] = product_context_age_messages
                self._product_cache[product_cache_key] = dict(cached_product_context)

            workflow_product_context = product_card_context or cached_product_context
            workflow_product_context_public = {
                key: value
                for key, value in dict(workflow_product_context or {}).items()
                if not str(key).startswith("_")
            }

            self.session_mgr.add_message(session_id, "user", buyer_text)

            kw_result = self.keyword_handler.check(shop["id"], buyer_text)
            if kw_result["matched"]:
                action = kw_result["action"]
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.static_rule.matched "
                    + _trace_fields(
                        trace,
                        action=action,
                        duration_ms=duration_ms,
                    )
                )
                if action == "auto_reply":
                    reply = kw_result["reply_text"] or "亲，谢谢您的咨询~"
                    self.session_mgr.add_message(session_id, "assistant", reply)
                    reply_length, reply_hash = _fingerprint(reply)
                    duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                    logger.info(
                        "event=pdd.reply.generated "
                        + _trace_fields(
                            trace,
                            action="keyword_reply",
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    return {"action": "reply", "text": reply, "session_id": session_id, "source": "keyword"}
                if action == "transfer_human":
                    self.session_mgr.set_status(session_id, "pending_human")
                    reply = TRANSFER_HUMAN_REPLY
                    self.session_mgr.add_message(session_id, "assistant", reply)
                    self._alert_transfer_human(
                        str(shop["shop_id"]),
                        buyer_id,
                        session_id,
                        f"关键词: {kw_result['keyword']}",
                        "high",
                        metadata=alert_metadata("keyword_transfer_human", reply),
                    )
                    reply_length, reply_hash = _fingerprint(reply)
                    duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                    logger.warning(
                        "event=pdd.transfer_human.triggered "
                        + _trace_fields(
                            trace,
                            action="keyword_transfer_human",
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    logger.info(
                        "event=pdd.pipeline.completed "
                        + _trace_fields(
                            trace,
                            action="keyword_transfer_human",
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    return {
                        "action": "transfer_human",
                        "text": reply,
                        "session_id": session_id,
                        "reason": f"关键词: {kw_result['keyword']}",
                    }
                if action == "block":
                    duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                    logger.info(
                        "event=pdd.message.skipped "
                        + _trace_fields(
                            trace,
                            action="keyword_block",
                            duration_ms=duration_ms,
                        )
                    )
                    return {"action": "block", "session_id": session_id}

            cached_products = self._product_prompt_summary(workflow_product_context_public)
            messages = self.session_mgr.build_context_messages(
                session_id,
                shop["shop_name"],
                SYSTEM_PROMPT_TEMPLATE,
                buyer_text,
                cached_products,
            )
            workflow_history = self._workflow_history(
                session_id,
                workflow_product_context_public if workflow_product_context_public else None,
            )
            workflow_history_summary = self._workflow_history_summary(workflow_history)

            chat_id = f"{shop_platform_id}_{buyer_id}_{session_id}"
            dataset_id = (shop.get("fastgpt_dataset_id") or "").strip()
            if not dataset_id:
                logger.error(
                    f"[FastGPTRoute] missing dataset_id: shop_id={shop.get('shop_id')}, "
                    f"shop_name={shop.get('shop_name')}, buyer_id={buyer_id}"
                )
                self.session_mgr.set_status(session_id, "pending_human")
                self.session_mgr.add_message(session_id, "assistant", TRANSFER_HUMAN_REPLY)
                self._alert_transfer_human(
                    str(shop["shop_id"]),
                    buyer_id,
                    session_id,
                    "店铺未配置 FastGPT 知识库ID",
                    "high",
                    metadata=alert_metadata("missing_fastgpt_dataset_id", TRANSFER_HUMAN_REPLY),
                )
                reply_length, reply_hash = _fingerprint(TRANSFER_HUMAN_REPLY)
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.warning(
                    "event=pdd.transfer_human.triggered "
                    + _trace_fields(
                        trace,
                        action="missing_fastgpt_dataset_id",
                        duration_ms=duration_ms,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                return {
                    "action": "transfer_human",
                    "text": TRANSFER_HUMAN_REPLY,
                    "session_id": session_id,
                    "reason": "missing_fastgpt_dataset_id",
                }

            t0 = datetime.now()
            logger.debug(
                "event=pdd.ai.request.started "
                + _trace_fields(
                    trace,
                    action="fastgpt_call",
                    duration_ms=0,
                    content_length=content_length,
                    content_hash=content_hash,
                    )
                )
            workflow_result = await self.workflow_engine.run(
                # Product card metadata is only consumed by the explicit internal
                # workflow path; FastGPT default behavior remains unchanged.
                # Keep raw values out of logs and artifacts.
                WorkflowContext(
                    trace_id=trace["trace_id"],
                    shop_id=str(shop.get("shop_id") or shop_platform_id),
                    user_id=str(user_id or ""),
                    customer_uid=str(buyer_id or ""),
                    buyer_id=str(buyer_id or ""),
                    session_id=str(session_id or ""),
                    chat_id=chat_id,
                    dataset_id=dataset_id,
                    message_type=str(message.get("message_type") or "text"),
                    content=buyer_text,
                    messages=messages,
                    goods_context=workflow_product_context_public or None,
                    history=workflow_history,
                    metadata={
                        "shop_db_id": shop.get("id"),
                        "shop_platform_id": shop_platform_id,
                        "shop_name": str(shop.get("shop_name") or ""),
                        "source_message_id": trace["source_message_id"],
                        "queue_message_id": trace["queue_message_id"],
                        "product_card": product_card_context,
                        "product_context": workflow_product_context_public,
                        "product_context_inherited": product_context_inherited,
                        "product_context_age_messages": product_context_age_messages,
                        **workflow_history_summary,
                    },
                )
            )
            latency_ms = (datetime.now() - t0).total_seconds() * 1000
            workflow_action = action_value(workflow_result.action)

            if workflow_action == WorkflowAction.SKIP.value:
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.message.skipped "
                    + _trace_fields(
                        trace,
                        action=str(workflow_result.reason or "workflow_skip"),
                        duration_ms=duration_ms,
                    )
                )
                return {"action": "skip", "session_id": session_id, "source": "workflow_skip"}

            if workflow_action == WorkflowAction.BLOCK.value:
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.message.skipped "
                    + _trace_fields(
                        trace,
                        action=str(workflow_result.reason or "workflow_block"),
                        duration_ms=duration_ms,
                    )
                )
                return {"action": "block", "session_id": session_id}

            if workflow_action == WorkflowAction.TRANSFER_HUMAN.value:
                self.session_mgr.set_status(session_id, "pending_human")
                reply = TRANSFER_HUMAN_REPLY
                self.session_mgr.add_message(session_id, "assistant", reply)
                reason = str(workflow_result.reason or "workflow_transfer_human")
                self._alert_transfer_human(
                    str(shop["shop_id"]),
                    buyer_id,
                    session_id,
                    reason,
                    "high",
                    metadata=alert_metadata(reason, reply),
                )
                reply_length, reply_hash = _fingerprint(reply)
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.warning(
                    "event=pdd.transfer_human.triggered "
                    + _trace_fields(
                        trace,
                        action=reason,
                        duration_ms=duration_ms,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                return {
                    "action": "transfer_human",
                    "text": reply,
                    "session_id": session_id,
                    "reason": reason,
                    "latency_ms": latency_ms,
                }

            if workflow_action == WorkflowAction.REQUEST_EVIDENCE.value and workflow_result.reply_text:
                reply = workflow_result.reply_text[:200]
                self.session_mgr.add_message(session_id, "assistant", reply)
                reply_length, reply_hash = _fingerprint(reply)
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.pipeline.completed "
                    + _trace_fields(
                        trace,
                        action="workflow_request_evidence",
                        duration_ms=duration_ms,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                return {
                    "action": "reply",
                    "text": reply,
                    "session_id": session_id,
                    "source": "workflow_request_evidence",
                    "latency_ms": latency_ms,
                }

            if workflow_action == WorkflowAction.REPLY.value and workflow_result.reply_text:
                self.fastgpt.reset_failures(session_id)
                self.session_mgr.reset_fallback_state(session_id)
                reply = workflow_result.reply_text[:200]
                self.session_mgr.add_message(session_id, "assistant", reply)
                reply_length, reply_hash = _fingerprint(reply)
                is_internal_workflow = bool(workflow_result.trace.get("workflow_version"))
                reply_action = "internal_reply" if is_internal_workflow else "fastgpt_reply"
                completed_action = "internal_reply" if is_internal_workflow else "ai_reply"
                logger.info(
                    "event=pdd.ai.request.succeeded "
                    + _trace_fields(
                        trace,
                        action=reply_action,
                        duration_ms=int(latency_ms),
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                        intent=workflow_result.intent,
                        rag_hit_count=workflow_result.trace.get("rag_hit_count", 0),
                        answer_generation_status=workflow_result.trace.get("answer_generation_status", ""),
                        answer_generator_called=workflow_result.trace.get("answer_generator_called", False),
                        calls_llm=workflow_result.trace.get("calls_llm", False),
                        guardrail_status=workflow_result.trace.get("guardrail_status", ""),
                        history_message_count=workflow_history_summary.get("history_message_count", 0),
                        history_has_product_card=workflow_history_summary.get("history_has_product_card", False),
                        latest_history_goods_id_hash=workflow_history_summary.get("latest_history_goods_id_hash", ""),
                        latest_history_goods_name_hash=workflow_history_summary.get("latest_history_goods_name_hash", ""),
                    )
                )
                if is_internal_workflow:
                    logger.info(
                        "event=internal.pipeline.stage_timing "
                        + _trace_fields(
                            trace,
                            action=reply_action,
                            **_stage_timing_fields(workflow_result.trace),
                        )
                    )

                guardrail_status = str(workflow_result.trace.get("guardrail_status") or "")
                internal_human_phrase = is_internal_workflow and _contains_human_service_phrase(reply)
                skip_legacy_transfer_scan = (
                    is_internal_workflow
                    and guardrail_status != "blocked"
                    and not internal_human_phrase
                )
                if skip_legacy_transfer_scan:
                    logger.info(
                        "event=pdd.transfer_decision "
                        + _trace_fields(
                            trace,
                            transfer_decision_source="workflow_result",
                            legacy_transfer_scan_skipped=True,
                            legacy_transfer_scan_skip_reason="internal_safe_reply_uses_workflow_action",
                            guardrail_status=guardrail_status,
                        )
                    )

                should_transfer_from_text = (
                    internal_human_phrase
                    or self.fastgpt.contains_transfer_intent(reply)
                )
                if (not skip_legacy_transfer_scan) and should_transfer_from_text:
                    self.session_mgr.set_status(session_id, "pending_human")
                    reply = TRANSFER_HUMAN_REPLY
                    reply_length, reply_hash = _fingerprint(reply)
                    self._alert_transfer_human(
                        str(shop["shop_id"]),
                        buyer_id,
                        session_id,
                        "AI 判断需要转人工",
                        "high",
                        metadata=alert_metadata("ai_transfer_human", reply),
                    )
                    duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                    logger.warning(
                        "event=pdd.transfer_human.triggered "
                        + _trace_fields(
                            trace,
                            action=(
                                "internal_reply_human_phrase"
                                if internal_human_phrase
                                else "ai_transfer_human"
                            ),
                            transfer_decision_source=(
                                "internal_reply_human_phrase"
                                if internal_human_phrase
                                else "legacy_transfer_scan"
                            ),
                            legacy_transfer_scan_skipped=False,
                            guardrail_status=guardrail_status,
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    logger.info(
                        "event=pdd.pipeline.completed "
                        + _trace_fields(
                            trace,
                            action=(
                                "internal_reply_human_phrase"
                                if internal_human_phrase
                                else "ai_transfer_human"
                            ),
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    return {
                        "action": "transfer_human",
                        "text": reply,
                        "session_id": session_id,
                        "reason": "AI 判断",
                        "latency_ms": latency_ms,
                        "tokens": workflow_result.trace.get("tokens", 0),
                    }

                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.pipeline.completed "
                    + _trace_fields(
                        trace,
                        action=completed_action,
                        duration_ms=duration_ms,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                        intent=workflow_result.intent,
                        rag_hit_count=workflow_result.trace.get("rag_hit_count", 0),
                        answer_generation_status=workflow_result.trace.get("answer_generation_status", ""),
                        answer_generator_called=workflow_result.trace.get("answer_generator_called", False),
                        calls_llm=workflow_result.trace.get("calls_llm", False),
                        guardrail_status=workflow_result.trace.get("guardrail_status", ""),
                        **(_stage_timing_fields(workflow_result.trace) if is_internal_workflow else {}),
                    )
                )
                return {
                    "action": "reply",
                    "text": reply,
                    "session_id": session_id,
                    "latency_ms": latency_ms,
                    "tokens": workflow_result.trace.get("tokens", 0),
                    "stage_timing": _stage_timing_fields(workflow_result.trace) if is_internal_workflow else {},
                }

            if workflow_action == WorkflowAction.FALLBACK.value and workflow_result.trace.get("workflow_version"):
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.message.skipped "
                    + _trace_fields(
                        trace,
                        action=str(workflow_result.reason or "internal_fallback"),
                        duration_ms=duration_ms,
                    )
                )
                return {
                    "action": "skip",
                    "session_id": session_id,
                    "source": "internal_fallback",
                    "reason": str(workflow_result.reason or "internal_fallback"),
                    "latency_ms": latency_ms,
                }

            failed = (
                workflow_result.trace.get("fastgpt_success") is False
                or workflow_result.trace.get("content_is_none") is True
            )
            logger.warning(
                "event=pdd.ai.request.failed "
                + _trace_fields(
                    trace,
                    action="fastgpt_failed",
                    duration_ms=int(latency_ms),
                    error_type=str(workflow_result.raw_error_type or "EmptyContent"),
                )
            )
            fallback = self.fastgpt.get_fallback(session_id, already_failed=failed)
            fallback_stage = self.session_mgr.should_send_fallback(session_id)
            self.session_mgr.set_status(session_id, "pending_human")

            if not fallback_stage:
                logger.info(f"会话 {session_id[:8]} fallback 已发送过，等待人工处理，自动回复静默")
                self._alert_transfer_human(
                    str(shop["shop_id"]),
                    buyer_id,
                    session_id,
                    "FastGPT 失败，fallback 已节流",
                    "high",
                    metadata=alert_metadata("fallback_throttled"),
                )
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.warning(
                    "event=pdd.transfer_human.triggered "
                    + _trace_fields(
                        trace,
                        action="fallback_throttled",
                        duration_ms=duration_ms,
                    )
                )
                logger.info(
                    "event=pdd.message.skipped "
                    + _trace_fields(
                        trace,
                        action="fallback_throttled",
                        duration_ms=duration_ms,
                    )
                )
                return {
                    "action": "skip",
                    "session_id": session_id,
                    "source": "fallback_throttled",
                    "latency_ms": latency_ms,
                }

            self.session_mgr.mark_fallback_sent(session_id, fallback_stage)
            self.session_mgr.add_message(session_id, "assistant", fallback)
            fallback_length, fallback_hash = _fingerprint(fallback)
            self._alert_transfer_human(
                str(shop["shop_id"]),
                buyer_id,
                session_id,
                f"FastGPT 失败，已发送第 {fallback_stage} 次 fallback",
                "high",
                metadata=alert_metadata(f"fastgpt_failed_fallback_{fallback_stage}", fallback),
            )
            duration_ms = int((time.perf_counter() - process_started_at) * 1000)
            logger.warning(
                "event=pdd.transfer_human.triggered "
                + _trace_fields(
                    trace,
                    action=f"fastgpt_failed_fallback_{fallback_stage}",
                    duration_ms=duration_ms,
                    reply_length=fallback_length,
                    reply_hash=fallback_hash,
                )
            )

            if self.fastgpt.should_transfer(session_id):
                self._alert_transfer_human(
                    str(shop["shop_id"]),
                    buyer_id,
                    session_id,
                    "FastGPT 连续失败",
                    "high",
                    metadata=alert_metadata("fastgpt_repeated_failure_transfer", fallback),
                )
                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.pipeline.completed "
                    + _trace_fields(
                        trace,
                        action="fastgpt_repeated_failure_transfer",
                        duration_ms=duration_ms,
                        reply_length=fallback_length,
                        reply_hash=fallback_hash,
                    )
                )
                return {
                    "action": "transfer_human",
                    "text": fallback,
                    "session_id": session_id,
                    "reason": "FastGPT 连续失败",
                    "latency_ms": latency_ms,
                }

            duration_ms = int((time.perf_counter() - process_started_at) * 1000)
            logger.info(
                "event=pdd.pipeline.completed "
                + _trace_fields(
                    trace,
                    action="fallback_reply",
                    duration_ms=duration_ms,
                    reply_length=fallback_length,
                    reply_hash=fallback_hash,
                )
            )
            return {
                "action": "reply",
                "text": fallback,
                "session_id": session_id,
                "source": "fallback",
                "latency_ms": latency_ms,
            }

        except Exception as e:
            duration_ms = int((time.perf_counter() - process_started_at) * 1000)
            logger.error(
                "event=pdd.pipeline.failed "
                + _trace_fields(
                    trace,
                    action="pipeline_exception",
                    duration_ms=duration_ms,
                    error_type=type(e).__name__,
                )
            )
            logger.error(f"消息处理异常: {e}")
            if session_id:
                try:
                    self.session_mgr.set_status(session_id, "pending_human")
                    self.session_mgr.add_message(session_id, "assistant", TRANSFER_HUMAN_REPLY)
                except Exception as status_error:
                    logger.warning(f"Pipeline 异常转人工状态更新失败: {status_error}")
            self._alert_transfer_human(
                str(shop.get("shop_id") if "shop" in locals() and shop else shop_platform_id or "unknown"),
                str(buyer_id or "unknown"),
                str(session_id or ""),
                f"Pipeline 异常: {e}",
                "high",
                metadata=alert_metadata("pipeline_exception", TRANSFER_HUMAN_REPLY),
            )
            reply_length, reply_hash = _fingerprint(TRANSFER_HUMAN_REPLY)
            logger.warning(
                "event=pdd.transfer_human.triggered "
                + _trace_fields(
                    trace,
                    action="pipeline_exception",
                    duration_ms=duration_ms,
                    reply_length=reply_length,
                    reply_hash=reply_hash,
                    error_type=type(e).__name__,
                )
            )
            return {
                "action": "transfer_human",
                "text": TRANSFER_HUMAN_REPLY,
                "error": str(e),
                "session_id": session_id,
                "reason": "Pipeline 异常",
            }
        finally:
            if session_id:
                await self.session_mgr.check_and_compress(session_id)

    async def _call_fastgpt_async(
        self,
        messages,
        dataset_id: str,
        chat_id: str = "",
        shop_id: str = "",
        shop_name: str = "",
    ) -> Dict[str, Any]:
        """Run the blocking FastGPT HTTP client outside the websocket event loop."""
        return await asyncio.to_thread(
            self.fastgpt.call,
            messages,
            dataset_id,
            chat_id=chat_id,
            shop_id=shop_id,
            shop_name=shop_name,
        )
