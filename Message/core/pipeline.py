"""消息处理管道 — 串联关键词 → FastGPT → 回复"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
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

    async def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        buyer_id = message.get("buyer_id")
        shop_platform_id = message.get("shop_platform_id")
        buyer_text = message.get("content", "")
        user_id = message.get("user_id", "")

        if not buyer_id or not buyer_text:
            logger.warning("消息缺少 buyer_id 或 content")
            return {"action": "skip"}

        # 获取店铺信息
        shop = self.db.get_shop_by_platform_id("pinduoduo", shop_platform_id)
        if not shop:
            logger.error(f"店铺未找到: {shop_platform_id}")
            return {"action": "skip"}

        session_id = None
        try:
            conv = await self.session_mgr.get_or_create_conversation(shop['id'], buyer_id, user_id)
            session_id = conv.session_id

            # 检查会话状态
            if conv.status in ('pending_human', 'human_handling'):
                logger.info(f"会话 {session_id[:8]} 处于人工状态，跳过自动回复")
                return {"action": "skip", "session_id": session_id, "status": conv.status}

            # 记录用户消息
            self.session_mgr.add_message(session_id, "user", buyer_text)

            # Step 3: 关键词预检
            kw_result = self.keyword_handler.check(shop['id'], buyer_text)
            if kw_result["matched"]:
                action = kw_result["action"]
                if action == "auto_reply":
                    reply = kw_result["reply_text"] or "亲，谢谢您的咨询~"
                    self.session_mgr.add_message(session_id, "assistant", reply)
                    return {"action": "reply", "text": reply, "session_id": session_id, "source": "keyword"}
                elif action == "transfer_human":
                    self.session_mgr.set_status(session_id, "pending_human")
                    reply = "亲，您的问题已转接人工客服，请稍等~"
                    self.session_mgr.add_message(session_id, "assistant", reply)
                    return {"action": "transfer_human", "text": reply, "session_id": session_id,
                            "reason": f"关键词: {kw_result['keyword']}"}
                elif action == "block":
                    return {"action": "block", "session_id": session_id}

            # Step 4: 构建上下文
            cached_products = self._product_cache.get(session_id, "")
            messages = self.session_mgr.build_context_messages(
                session_id, shop['shop_name'], SYSTEM_PROMPT_TEMPLATE, buyer_text, cached_products
            )

            # Step 5: FastGPT 调用（chatId 实现多店铺多用户会话隔离）
            chat_id = f"{shop_platform_id}_{buyer_id}_{session_id}"
            t0 = datetime.now()
            result = self.fastgpt.call(messages, shop.get('fastgpt_dataset_id') or "", chat_id=chat_id)
            latency_ms = (datetime.now() - t0).total_seconds() * 1000

            if result["success"] and result["content"]:
                self.fastgpt.reset_failures(session_id)
                reply = result["content"][:200]
                self.session_mgr.add_message(session_id, "assistant", reply)

                # 检查转人工意图
                if self.fastgpt.contains_transfer_intent(reply):
                    self.session_mgr.set_status(session_id, "pending_human")
                    return {"action": "transfer_human", "text": reply, "session_id": session_id,
                            "reason": "AI 判断", "latency_ms": latency_ms, "tokens": result.get("tokens", 0)}

                return {"action": "reply", "text": reply, "session_id": session_id,
                        "latency_ms": latency_ms, "tokens": result.get("tokens", 0)}
            else:
                failed = result["success"] is False or result["content"] is None
                fallback = self.fastgpt.get_fallback(session_id, already_failed=failed)
                self.session_mgr.add_message(session_id, "assistant", fallback)

                if self.fastgpt.should_transfer(session_id):
                    self.session_mgr.set_status(session_id, "pending_human")
                    return {"action": "transfer_human", "text": fallback, "session_id": session_id,
                            "reason": "FastGPT 连续失败", "latency_ms": latency_ms}

                return {"action": "reply", "text": fallback, "session_id": session_id,
                        "source": "fallback", "latency_ms": latency_ms}

        except Exception as e:
            logger.error(f"消息处理异常: {e}")
            return {"action": "error", "error": str(e), "session_id": session_id}
        finally:
            # 上下文压缩（post-process）
            if session_id:
                await self.session_mgr.check_and_compress(session_id)
