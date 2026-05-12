"""
AI回复处理器
专注的AI处理，移除复杂预处理和发送逻辑

V2.0 新增：
- 人工静默锁检查：如果用户被人工接管，AI 保持静默

V2.0 战役七：上线预备重构
- 抽离硬编码 TTL 到 core.config
- 抽离硬编码话术到 core.constants

V2.0 地狱级压测修复：
- 后置护栏：检测 LLM 回复中的危险词汇，防止医疗建议泄露
"""
from __future__ import annotations

from typing import Dict, Any, Optional, List
from bridge.context import Context, ContextType
from .base import BaseHandler
from .preprocessor import MessagePreprocessor
from Agent.bot import Bot

# 导入 Redis 管理器
from database.redis_manager import redis_manager

# 导入集中式配置和常量
from core.config import HUMAN_LOCK_TTL, INFERENCE_LOCK_TTL
from core.constants import IMAGE_INTERCEPT_REPLY, FALLBACK_REPLY


class AIReplyHandler(BaseHandler):
    """专注的AI回复处理器"""

    # 危险词汇黑名单（医疗/安全相关）
    DANGEROUS_KEYWORDS = [
        '偏方', '解毒', '催吐', '洗胃', '灌肠',
        '自行用药', '草药治疗', '民间疗法',
        '不用去医院', '自己治疗', '在家治疗'
    ]

    # 安全兜底话术
    SAFETY_FALLBACK = "非常抱歉，我们无法提供相关建议。为安全起见，请您立即停止使用并寻求专业人士/医生的帮助。"

    def __init__(self, bot: Bot = None, auto_reply_types: set = None):
        super().__init__("AIReplyHandler")
        # 从 DI 容器获取 CustomerAgent（如果未传入）
        if bot is None:
            try:
                from core.di_container import container
                from Agent.CustomerAgent.custom.customer_agent import CustomerAgent
                bot = container.get(CustomerAgent)
            except Exception as e:
                from utils.logger_loguru import get_logger
                get_logger("AIReplyHandler").warning(f"从DI容器获取CustomerAgent失败: {e}, 将使用无Bot模式")
        self.bot = bot
        self.preprocessor = MessagePreprocessor()
        self.auto_reply_types = auto_reply_types or {
            ContextType.TEXT,
            ContextType.GOODS_INQUIRY,
            ContextType.GOODS_SPEC,
            ContextType.ORDER_INFO,
            ContextType.IMAGE,
            ContextType.VIDEO,
            ContextType.EMOTION
        }

    def can_handle(self, context: Context) -> bool:
        """检查是否可以处理该消息"""
        # 支持多种消息类型
        return context.type in self.auto_reply_types

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        """处理AI回复"""
        try:
            # =====================================================
            # Step 0: 图片消息前置硬拦截（防大模型懵逼）
            # =====================================================
            # 从 metadata 或 context 中提取用户标识
            from_uid = metadata.get('from_uid') or getattr(context.kwargs, 'from_uid', None)
            session_id = metadata.get('session_id') or f"{metadata.get('shop_id')}_{from_uid}"

            # 检查是否是图片消息
            if context.type == ContextType.IMAGE or (
                context.content and ('[图片]' in str(context.content) or '[Image]' in str(context.content))
            ):
                self.logger.info(f"[图片拦截] 用户 {session_id} 发送了图片，触发人工接管")

                # 1. 设置人工锁（使用集中式配置）
                redis_manager.set_human_lock(session_id, ttl=HUMAN_LOCK_TTL)

                # 2. 发送固定回复（使用集中式常量）
                fixed_reply = IMAGE_INTERCEPT_REPLY
                await self._send_reply(context, fixed_reply, metadata)

                # 3. 触发低危警报
                try:
                    from core.di_container import container
                    from core.notification import NotificationService
                    notification_service = container.get(NotificationService)
                    if notification_service:
                        self.logger.info(
                            f"[图片拦截] 触发 UI 转人工提醒: shop_id={metadata.get('shop_id')}, from_uid={from_uid}"
                        )
                        notification_service.alert_human_fallback(
                            shop_id=str(metadata.get('shop_id') or 'unknown'),
                            user_id=str(from_uid or 'unknown'),
                            reason="用户发送图片",
                            alert_level="low",
                        )
                    else:
                        self.logger.warning("[图片拦截] NotificationService 未注册，无法触发 UI 提醒")
                except Exception as e:
                    self.logger.warning(f"[图片拦截] 触发警报失败: {e}")

                # 4. 终止后续流程，不让图片进入 LangGraph
                return True

            # =====================================================
            # Step 1: 人工静默锁检查（物理拦截）
            # =====================================================
            # 检查是否被人工接管
            if redis_manager.is_human_locked(session_id):
                ttl = redis_manager.get_lock_ttl(session_id)
                self.logger.info(
                    f"[人工静默] 用户 {session_id} 正由人工接管，AI 静默中... "
                    f"(剩余锁时间: {ttl}s)"
                )
                # 直接返回 True，结束消息生命周期，AI 不回复
                return True

            # =====================================================
            # Step 1.5: 关键词管理静态规则拦截（真正的 Level -1）
            # =====================================================
            static_reply = self._match_static_reply(context, metadata)
            if static_reply:
                self.logger.info(
                    f"[静态规则拦截] session_id={session_id}, reply={static_reply[:40]}"
                )
                await self._send_reply(context, static_reply, metadata)
                return True

            # =====================================================
            # Step 2: AI 推理互斥锁检查（防止并发压垮显存）
            # =====================================================
            if not redis_manager.acquire_inference_lock(session_id, ttl=INFERENCE_LOCK_TTL):
                self.logger.debug(
                    f"[推理互斥] 用户 {session_id} 正在推理中，并发消息被拦截"
                )
                # 丢弃并发消息，依靠意图继承机制处理
                return True

            # =====================================================
            # Step 3: 正常 AI 处理流程（try...finally 确保锁释放）
            # =====================================================
            try:
                # 预处理消息
                processed_content = self.preprocessor.process(context.content, context.type)

                # 调用AI生成回复
                reply = await self._get_ai_reply(processed_content, context)
                if not reply:
                    self.logger.warning("AI回复生成失败，使用备用回复")
                    return await self._handle_fallback(context, metadata)

                # =====================================================
                # Step 4: 后置护栏检查（防止危险内容泄露）
                # =====================================================
                reply = self._post_process_guardrail(reply, session_id, metadata)

                # 发送回复
                success = await self._send_reply(context, reply, metadata)
                if success:
                    await self.log_message(context, "AI回复发送成功", f"回复: {reply}...")
                else:
                    self.logger.warning("AI回复发送失败")
                    return await self._handle_fallback(context, metadata)

                return True

            finally:
                # 确保推理锁被安全释放，防止死锁
                redis_manager.release_inference_lock(session_id)

        except Exception as e:
            self.logger.error(f"AI回复处理失败: {e}")
            return await self._handle_fallback(context, metadata)

    def _match_static_reply(self, context: Context, metadata: Dict[str, Any]) -> Optional[str]:
        """匹配关键词管理中的静态规则。

        支持一条规则写多个触发词，例如：
        12岁/十二岁/小孩/儿童/宝宝
        """
        if context.type != ContextType.TEXT:
            return None

        content = str(context.content or "")
        if not content:
            return None

        shop_id = str(metadata.get("shop_id") or "default")
        rules = redis_manager.get_static_rules(shop_id)
        if not rules:
            return None

        normalized_content = content.replace("内容：", "").replace("内容:", "").lower().strip()
        for keyword_expr, reply in rules.items():
            terms = self._split_static_rule_terms(str(keyword_expr))
            matched_terms = [term for term in terms if term and term.lower() in normalized_content]
            if matched_terms:
                self.logger.info(
                    f"[静态规则命中] shop_id={shop_id}, rule={keyword_expr}, "
                    f"matched={matched_terms}, content={normalized_content}"
                )
                return str(reply).strip()
        return None

    def _split_static_rule_terms(self, keyword_expr: str) -> List[str]:
        """把运营可读的一组触发词拆成可匹配列表。"""
        import re

        return [
            term.strip()
            for term in re.split(r"[\n,，;；|/、]+", keyword_expr or "")
            if term.strip()
        ]

    async def _get_ai_reply(self, query: str, context: Context) -> Optional[str]:
        """获取AI回复"""
        if not self.bot:
            return None

        try:
            # 优先使用异步接口，其次回退到同步接口
            if hasattr(self.bot, 'async_reply'):
                res = await self.bot.async_reply(query, context)
                return getattr(res, 'content', str(res))
            elif hasattr(self.bot, 'reply'):
                res = self.bot.reply(query, context)
                return getattr(res, 'content', str(res))
            else:
                self.logger.warning("Bot不支持reply或async_reply方法")
                return None

        except Exception as e:
            self.logger.error(f"AI Bot调用失败: {e}")
            return None

    def _post_process_guardrail(self, response_text: str, session_id: str, metadata: Dict[str, Any]) -> str:
        """
        后置护栏：检测 LLM 回复中的危险词汇

        对 LLM 返回的文本进行关键词匹配。如果命中黑名单：
        1. 强行丢弃 LLM 的回复
        2. 替换为标准兜底话术
        3. 触发 alert_level="high" 全网广播

        Args:
            response_text: LLM 原始回复
            session_id: 会话ID
            metadata: 元数据

        Returns:
            处理后的安全回复
        """
        # 检测危险词汇
        detected_dangers = [kw for kw in self.DANGEROUS_KEYWORDS if kw in response_text]

        if detected_dangers:
            self.logger.warning(
                f"[后置护栏] 检测到危险词汇: {detected_dangers}, "
                f"session_id={session_id}, 原回复将被替换"
            )

            # 触发高危警报
            try:
                from core.di_container import container
                from core.notification import NotificationService
                notification_service = container.get(NotificationService)
                if notification_service:
                    notification_service.alert_human_fallback(
                        shop_id=str(metadata.get('shop_id') or 'unknown'),
                        user_id=str(metadata.get('from_uid') or 'unknown'),
                        reason=f"LLM回复包含危险词汇: {detected_dangers}",
                        alert_level="high",
                    )
            except Exception as e:
                self.logger.warning(f"[后置护栏] 触发警报失败: {e}")

            # 返回安全兜底话术
            return self.SAFETY_FALLBACK

        # 无危险词汇，返回原回复
        return response_text

    async def _send_reply(self, context: Context, reply: str, metadata: Dict[str, Any]) -> bool:
        """发送回复"""
        try:
            # 从metadata中提取必要信息
            shop_id = metadata.get('shop_id')
            user_id = metadata.get('user_id')
            from_uid = metadata.get('from_uid')

            if not all([shop_id, user_id, from_uid]):
                self.logger.warning(f"缺少发送信息: shop_id={shop_id}, user_id={user_id}, from_uid={from_uid}")
                return False

            # 尝试发送消息
            from Channel.pinduoduo.utils.API.send_message import SendMessage
            sender = SendMessage(shop_id, user_id)
            result = sender.send_text(from_uid, reply)
            if isinstance(result, dict) and result.get("success"):
                self.logger.info(
                    f"[发送回执] 文本消息接口成功: shop_id={shop_id}, user_id={user_id}, "
                    f"from_uid={from_uid}, result={result.get('result')}"
                )
                return True
            self.logger.warning(
                f"[发送回执] 文本消息接口未确认成功: shop_id={shop_id}, user_id={user_id}, "
                f"from_uid={from_uid}, result={result}"
            )
            return False

        except Exception as e:
            self.logger.error(f"发送回复失败: {e}")
            return False

    async def _handle_fallback(self, context: Context, metadata: Dict[str, Any]) -> bool:
        """备用回复处理"""
        try:
            # 使用集中式常量的备用回复
            reply_text = FALLBACK_REPLY

            # 记录备用回复
            self.logger.info("使用备用回复")

            # 尝试发送备用回复
            success = await self._send_reply(context, reply_text, metadata)
            if not success:
                # 如果发送失败，记录日志并返回False让下游有机会处理
                await self.log_message(context, "备用回复发送失败", f"内容: {reply_text}")
                return False

            await self.log_message(context, "备用回复发送成功", f"内容: {reply_text}")
            return True

        except Exception as e:
            self.logger.error(f"备用回复处理失败: {e}")
            return True  # 即使失败也返回True，避免重复处理
