"""消息处理管道 - 串联关键词、FastGPT 和回复发送。"""
import asyncio
from datetime import datetime
from typing import Any, Dict

from core.constants import TRANSFER_HUMAN_REPLY
from Message.handlers.fastgpt_handler import SYSTEM_PROMPT_TEMPLATE
from utils.logger_loguru import get_logger

logger = get_logger("MessagePipeline")


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
    ) -> None:
        """触发转人工 UI 告警和提示音。"""
        try:
            from core.di_container import container
            from core.notification import NotificationService

            notification_service = container.get(NotificationService)
            if notification_service:
                notification_service.alert_human_fallback(
                    shop_id=shop_id,
                    user_id=buyer_id,
                    reason=reason,
                    alert_level=alert_level,
                )
        except Exception as e:
            logger.warning(f"转人工通知触发失败: {e}")

    async def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        buyer_id = message.get("buyer_id")
        shop_platform_id = message.get("shop_platform_id")
        buyer_text = message.get("content", "")
        user_id = message.get("user_id", "")

        if not buyer_id or not buyer_text:
            logger.warning("消息缺少 buyer_id 或 content")
            return {"action": "skip"}

        shop = self.db.get_shop_by_platform_id("pinduoduo", shop_platform_id)
        if not shop:
            logger.error(f"店铺未找到: {shop_platform_id}")
            return {"action": "skip"}

        session_id = None
        try:
            conv = await self.session_mgr.get_or_create_conversation(shop["id"], buyer_id, user_id)
            session_id = conv.session_id

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
                    logger.info(
                        f"会话 {session_id[:8]} 处于人工状态，发送第 {reminder_stage} 次 fallback 提醒"
                    )
                    return {
                        "action": "reply",
                        "text": reminder,
                        "session_id": session_id,
                        "source": f"pending_human_{reminder_stage}_fallback",
                    }
                logger.info(f"会话 {session_id[:8]} 处于人工状态，跳过自动回复")
                return {"action": "skip", "session_id": session_id, "status": conv.status}

            self.session_mgr.add_message(session_id, "user", buyer_text)

            kw_result = self.keyword_handler.check(shop["id"], buyer_text)
            if kw_result["matched"]:
                action = kw_result["action"]
                if action == "auto_reply":
                    reply = kw_result["reply_text"] or "亲，谢谢您的咨询~"
                    self.session_mgr.add_message(session_id, "assistant", reply)
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
                    )
                    return {
                        "action": "transfer_human",
                        "text": reply,
                        "session_id": session_id,
                        "reason": f"关键词: {kw_result['keyword']}",
                    }
                if action == "block":
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
                )
                return {
                    "action": "transfer_human",
                    "text": TRANSFER_HUMAN_REPLY,
                    "session_id": session_id,
                    "reason": "missing_fastgpt_dataset_id",
                }

            t0 = datetime.now()
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

                if self.fastgpt.contains_transfer_intent(reply):
                    self.session_mgr.set_status(session_id, "pending_human")
                    reply = TRANSFER_HUMAN_REPLY
                    self._alert_transfer_human(
                        str(shop["shop_id"]),
                        buyer_id,
                        session_id,
                        "AI 判断需要转人工",
                        "high",
                    )
                    return {
                        "action": "transfer_human",
                        "text": reply,
                        "session_id": session_id,
                        "reason": "AI 判断",
                        "latency_ms": latency_ms,
                        "tokens": result.get("tokens", 0),
                    }

                return {
                    "action": "reply",
                    "text": reply,
                    "session_id": session_id,
                    "latency_ms": latency_ms,
                    "tokens": result.get("tokens", 0),
                }

            failed = result["success"] is False or result["content"] is None
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
                )
                return {
                    "action": "skip",
                    "session_id": session_id,
                    "source": "fallback_throttled",
                    "latency_ms": latency_ms,
                }

            self.session_mgr.mark_fallback_sent(session_id, fallback_stage)
            self.session_mgr.add_message(session_id, "assistant", fallback)
            self._alert_transfer_human(
                str(shop["shop_id"]),
                buyer_id,
                session_id,
                f"FastGPT 失败，已发送第 {fallback_stage} 次 fallback",
                "high",
            )

            if self.fastgpt.should_transfer(session_id):
                self._alert_transfer_human(
                    str(shop["shop_id"]),
                    buyer_id,
                    session_id,
                    "FastGPT 连续失败",
                    "high",
                )
                return {
                    "action": "transfer_human",
                    "text": fallback,
                    "session_id": session_id,
                    "reason": "FastGPT 连续失败",
                    "latency_ms": latency_ms,
                }

            return {
                "action": "reply",
                "text": fallback,
                "session_id": session_id,
                "source": "fallback",
                "latency_ms": latency_ms,
            }

        except Exception as e:
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
