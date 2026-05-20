"""消息处理管道 - 串联关键词、FastGPT 和回复发送。"""
import asyncio
import hashlib
import time
from datetime import datetime
from typing import Any, Dict

from core.constants import TRANSFER_HUMAN_REPLY
from Message.handlers.fastgpt_handler import SYSTEM_PROMPT_TEMPLATE
from utils.logger_loguru import get_logger

logger = get_logger("MessagePipeline")


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


class MessagePipeline:
    def __init__(self, db_manager, session_manager, keyword_handler, fastgpt_handler, config):
        self.db = db_manager
        self.session_mgr = session_manager
        self.keyword_handler = keyword_handler
        self.fastgpt = fastgpt_handler
        self.config = config
        self._product_cache: Dict[str, str] = {}

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

            cached_products = self._product_cache.get(session_id, "")
            messages = self.session_mgr.build_context_messages(
                session_id,
                shop["shop_name"],
                SYSTEM_PROMPT_TEMPLATE,
                buyer_text,
                cached_products,
            )

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
            result = await self._call_fastgpt_async(
                messages,
                dataset_id,
                chat_id=chat_id,
                shop_id=str(shop.get("shop_id") or shop_platform_id),
                shop_name=str(shop.get("shop_name") or ""),
            )
            latency_ms = (datetime.now() - t0).total_seconds() * 1000

            if result["success"] and result["content"]:
                self.fastgpt.reset_failures(session_id)
                self.session_mgr.reset_fallback_state(session_id)
                reply = result["content"][:200]
                self.session_mgr.add_message(session_id, "assistant", reply)
                reply_length, reply_hash = _fingerprint(reply)
                logger.info(
                    "event=pdd.ai.request.succeeded "
                    + _trace_fields(
                        trace,
                        action="fastgpt_reply",
                        duration_ms=int(latency_ms),
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )

                if self.fastgpt.contains_transfer_intent(reply):
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
                            action="ai_transfer_human",
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    logger.info(
                        "event=pdd.pipeline.completed "
                        + _trace_fields(
                            trace,
                            action="ai_transfer_human",
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
                        "tokens": result.get("tokens", 0),
                    }

                duration_ms = int((time.perf_counter() - process_started_at) * 1000)
                logger.info(
                    "event=pdd.pipeline.completed "
                    + _trace_fields(
                        trace,
                        action="ai_reply",
                        duration_ms=duration_ms,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                return {
                    "action": "reply",
                    "text": reply,
                    "session_id": session_id,
                    "latency_ms": latency_ms,
                    "tokens": result.get("tokens", 0),
                }

            failed = result["success"] is False or result["content"] is None
            logger.warning(
                "event=pdd.ai.request.failed "
                + _trace_fields(
                    trace,
                    action="fastgpt_failed",
                    duration_ms=int(latency_ms),
                    error_type=str(result.get("error_type") or "EmptyContent"),
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
