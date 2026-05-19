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
import hashlib
import time
import uuid
from bridge.context import Context, ContextType
from .base import BaseHandler
from .preprocessor import MessagePreprocessor

# 导入 Redis 管理器 (V3.0 存根，所有方法返回安全默认值)
from database.redis_manager import redis_manager

# 导入集中式配置和常量
from core.config import FALLBACK_SECOND_REMINDER_BEFORE_EXPIRY, HUMAN_LOCK_TTL, INFERENCE_LOCK_TTL
from core.constants import IMAGE_INTERCEPT_REPLY, FALLBACK_REPLY_POOL
import random


class AIReplyHandler(BaseHandler):
    """V3.0 AI回复处理器 — 移除 Agent 依赖，通过 MessagePipeline 调用 FastGPT"""

    PIPELINE_SKIP = "__PIPELINE_SKIP__"
    _fallback_state: Dict[str, Dict[str, float]] = {}

    # 危险词汇黑名单（医疗/安全相关）
    DANGEROUS_KEYWORDS = [
        '偏方', '解毒', '催吐', '洗胃', '灌肠',
        '自行用药', '草药治疗', '民间疗法',
        '不用去医院', '自己治疗', '在家治疗'
    ]

    # 安全兜底话术
    SAFETY_FALLBACK = "非常抱歉，我们无法提供相关建议。为安全起见，请您立即停止使用并寻求专业人士/医生的帮助。"

    def __init__(self, bot: Any = None, auto_reply_types: set = None):
        super().__init__("AIReplyHandler")
        self.bot = bot  # V3.0: bot 可为 None，此时走 MessagePipeline
        self._pipeline = None
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

    @staticmethod
    def _get_context_value(context: Context, name: str) -> Any:
        kwargs = getattr(context, "kwargs", None)
        if kwargs is None:
            return None
        if isinstance(kwargs, dict):
            return kwargs.get(name)
        return getattr(kwargs, name, None)

    @staticmethod
    def _fingerprint(value: Any) -> tuple[int, str]:
        value_text = "" if value is None else str(value)
        value_hash = hashlib.sha256(value_text.encode("utf-8")).hexdigest()[:12]
        return len(value_text), value_hash

    def _build_trace_metadata(self, context: Context, metadata: Dict[str, Any]) -> Dict[str, Any]:
        shop_id = metadata.get("shop_id") or self._get_context_value(context, "shop_id") or "unknown"
        user_id = metadata.get("user_id") or self._get_context_value(context, "user_id") or ""
        from_uid = metadata.get("from_uid") or self._get_context_value(context, "from_uid") or ""
        trace_id = metadata.get("trace_id") or self._get_context_value(context, "trace_id") or ""
        source_message_id = (
            metadata.get("source_message_id")
            or self._get_context_value(context, "source_message_id")
            or self._get_context_value(context, "msg_id")
            or ""
        )
        queue_message_id = metadata.get("queue_message_id") or metadata.get("message_id") or ""
        session_id = metadata.get("session_id") or f"{shop_id}_{from_uid}"
        content_length = metadata.get("content_length") or self._get_context_value(context, "content_length")
        content_hash = metadata.get("content_hash") or self._get_context_value(context, "content_hash")
        if content_length is None or content_hash is None:
            computed_length, computed_hash = self._fingerprint(context.content)
            content_length = computed_length if content_length is None else content_length
            content_hash = computed_hash if content_hash is None else content_hash

        return {
            "trace_id": str(trace_id or ""),
            "source_message_id": str(source_message_id or ""),
            "queue_message_id": str(queue_message_id or ""),
            "session_id": str(session_id or ""),
            "shop_id": str(shop_id or "unknown"),
            "user_id": str(user_id or ""),
            "customer_uid": str(from_uid or ""),
            "content_length": content_length,
            "content_hash": str(content_hash or ""),
        }

    @staticmethod
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

    @staticmethod
    def _pdd_result_summary(result: Any) -> str:
        if not isinstance(result, dict):
            return "none" if result is None else type(result).__name__
        pdd_result = result.get("result")
        if isinstance(pdd_result, dict):
            if pdd_result.get("result") == "ok":
                return "ok"
            if pdd_result.get("error_code") is not None:
                return f"error_code:{pdd_result.get('error_code')}"
            if pdd_result.get("error"):
                return "error"
            return "dict_no_result"
        if pdd_result is None:
            return "missing_result"
        value_length, value_hash = AIReplyHandler._fingerprint(pdd_result)
        return f"{type(pdd_result).__name__}:length={value_length}:hash={value_hash}"

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        """处理AI回复"""
        trace = self._build_trace_metadata(context, metadata)
        handle_started_at = time.perf_counter()
        try:
            # =====================================================
            # Step 0: 图片消息前置硬拦截（防大模型懵逼）
            # =====================================================
            # 从 metadata 或 context 中提取用户标识
            from_uid = metadata.get('from_uid') or getattr(context.kwargs, 'from_uid', None)
            session_id = metadata.get('session_id') or f"{metadata.get('shop_id')}_{from_uid}"
            trace["session_id"] = str(session_id or trace.get("session_id") or "")

            # 检查是否是图片消息
            if context.type == ContextType.IMAGE or (
                context.content and ('[图片]' in str(context.content) or '[Image]' in str(context.content))
            ):
                duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                self.logger.warning(
                    "event=pdd.transfer_human.triggered "
                    + self._trace_fields(
                        trace,
                        action="image_intercept",
                        duration_ms=duration_ms,
                        content_length=trace.get("content_length", 0),
                        content_hash=trace.get("content_hash", ""),
                    )
                )
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
                duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                self.logger.info(
                    "event=pdd.human_lock.skipped "
                    + self._trace_fields(
                        trace,
                        action="human_locked",
                        duration_ms=duration_ms,
                    )
                )
                self.logger.info(
                    "event=pdd.message.skipped "
                    + self._trace_fields(
                        trace,
                        action="human_locked",
                        duration_ms=duration_ms,
                    )
                )
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
                reply_length, reply_hash = self._fingerprint(static_reply)
                duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                self.logger.info(
                    "event=pdd.static_rule.matched "
                    + self._trace_fields(
                        trace,
                        action="static_reply",
                        duration_ms=duration_ms,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                self.logger.info(
                    f"[静态规则拦截] session_id={session_id}, reply={static_reply[:40]}"
                )
                await self._send_reply(context, static_reply, metadata)
                duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                self.logger.info(
                    "event=pdd.reply.generated "
                    + self._trace_fields(
                        trace,
                        action="static_reply",
                        duration_ms=duration_ms,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                return True

            # =====================================================
            # Step 2: AI 推理互斥锁检查（防止并发压垮显存）
            # =====================================================
            if not redis_manager.acquire_inference_lock(session_id, ttl=INFERENCE_LOCK_TTL):
                duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                self.logger.info(
                    "event=pdd.message.skipped "
                    + self._trace_fields(
                        trace,
                        action="inference_locked",
                        duration_ms=duration_ms,
                    )
                )
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
                reply = await self._get_ai_reply(processed_content, context, metadata)
                if reply == self.PIPELINE_SKIP:
                    duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                    self.logger.info(
                        "event=pdd.message.skipped "
                        + self._trace_fields(
                            trace,
                            action="pipeline_skip",
                            duration_ms=duration_ms,
                        )
                    )
                    self.logger.info("Pipeline 已要求静默跳过，终止自动回复")
                    return True
                if not reply:
                    duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                    self.logger.warning(
                        "event=pdd.transfer_human.triggered "
                        + self._trace_fields(
                            trace,
                            action="ai_empty_reply",
                            duration_ms=duration_ms,
                        )
                    )
                    self.logger.warning("AI回复生成失败，使用备用回复")
                    self._alert_manual_transfer(metadata, session_id, "AI reply send failed", "high")
                    return await self._handle_fallback(context, metadata)

                # =====================================================
                # Step 4: 后置护栏检查（防止危险内容泄露）
                # =====================================================
                reply = self._post_process_guardrail(reply, session_id, metadata)

                # 发送回复
                reply_length, reply_hash = self._fingerprint(reply)
                success = await self._send_reply(context, reply, metadata)
                if success:
                    duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                    self.logger.info(
                        "event=pdd.handler.completed "
                        + self._trace_fields(
                            trace,
                            action="reply_sent",
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    await self.log_message(
                        context,
                        "AI回复发送成功",
                        f"reply_length={reply_length} reply_hash={reply_hash}",
                    )
                else:
                    duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
                    self.logger.warning(
                        "event=pdd.transfer_human.triggered "
                        + self._trace_fields(
                            trace,
                            action="send_failed",
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    self.logger.warning("AI回复发送失败")
                    await self.log_message(context, "AI回复发送失败", "已触发转人工告警，避免重复发送备用话术")
                    return True

                return True

            finally:
                # 确保推理锁被安全释放，防止死锁
                redis_manager.release_inference_lock(session_id)

        except Exception as e:
            duration_ms = int((time.perf_counter() - handle_started_at) * 1000)
            self.logger.error(
                "event=pdd.message.skipped "
                + self._trace_fields(
                    trace,
                    action="handler_exception",
                    duration_ms=duration_ms,
                    error_type=type(e).__name__,
                )
            )
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

    def _get_pipeline(self):
        """V3.0: 惰性初始化 MessagePipeline"""
        if self._pipeline is None:
            try:
                from database.db_manager import db_manager
                from Message.core.pipeline import MessagePipeline
                from Message.handlers.fastgpt_handler import FastGPTHandler
                from Message.handlers.keyword_handler import KeywordHandler
                from Session.session_manager import SessionManager
                from core.config_manager import config_manager

                # 从 AppConfig 读取 FastGPT API Key，没有则使用默认值
                api_key = ""
                fastgpt_config = db_manager.get_config("fastgpt:api_key")
                if fastgpt_config:
                    api_key = fastgpt_config["config_value"]

                fastgpt = FastGPTHandler(api_key=api_key)
                keyword = KeywordHandler(db_manager)
                session_mgr = SessionManager(db_manager)
                self._pipeline = MessagePipeline(
                    db_manager, session_mgr, keyword, fastgpt, config_manager
                )
            except Exception as e:
                self.logger.error(f"V3.0 Pipeline 初始化失败: {e}")
        return self._pipeline

    async def _get_ai_reply(self, query: str, context: Context, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """获取AI回复 — V3.0: 优先 MessagePipeline，其次 bot"""
        metadata = metadata or {}
        trace = self._build_trace_metadata(context, metadata)
        request_started_at = time.perf_counter()
        # 尝试 V3.0 MessagePipeline
        pipeline = self._get_pipeline()
        if pipeline:
            try:
                kwargs = context.kwargs
                message = {
                    "buyer_id": str(getattr(kwargs, 'from_uid', '')),
                    "shop_platform_id": str(getattr(kwargs, 'shop_id', '')),
                    "content": query,
                    "user_id": str(getattr(kwargs, 'user_id', '')),
                }
                self.logger.debug(
                    "event=pdd.pipeline.started "
                    + self._trace_fields(
                        trace,
                        action="pipeline_process",
                        duration_ms=0,
                        content_length=trace.get("content_length", 0),
                        content_hash=trace.get("content_hash", ""),
                    )
                )
                result = await pipeline.process(
                    message,
                    trace_id=trace.get("trace_id") or None,
                    source_message_id=trace.get("source_message_id") or None,
                    queue_message_id=trace.get("queue_message_id") or None,
                )
                action = result.get("action", "")
                duration_ms = int((time.perf_counter() - request_started_at) * 1000)
                trace["session_id"] = str(result.get("session_id") or trace.get("session_id") or "")
                if action in ("reply", "transfer_human"):
                    reply = result.get("text", "")
                    reply_length, reply_hash = self._fingerprint(reply)
                    self.logger.info(
                        "event=pdd.pipeline.completed "
                        + self._trace_fields(
                            trace,
                            action=action,
                            duration_ms=duration_ms,
                            reply_length=reply_length,
                            reply_hash=reply_hash,
                        )
                    )
                    if action == "transfer_human":
                        self.logger.warning(
                            "event=pdd.transfer_human.triggered "
                            + self._trace_fields(
                                trace,
                                action=str(result.get("reason") or "pipeline_transfer_human"),
                                duration_ms=duration_ms,
                            )
                        )
                    return reply
                if action == "skip":
                    self.logger.info(
                        "event=pdd.pipeline.completed "
                        + self._trace_fields(
                            trace,
                            action="skip",
                            duration_ms=duration_ms,
                        )
                    )
                    self.logger.info(
                        "Pipeline skip: "
                        + self._trace_fields(trace, action="skip", duration_ms=duration_ms)
                    )
                    return self.PIPELINE_SKIP
            except Exception as e:
                duration_ms = int((time.perf_counter() - request_started_at) * 1000)
                self.logger.warning(
                    "event=pdd.pipeline.failed "
                    + self._trace_fields(
                        trace,
                        action="pipeline_exception",
                        duration_ms=duration_ms,
                        error_type=type(e).__name__,
                    )
                )
                self.logger.error(f"Pipeline 调用失败: {e}")

        # 回退到旧 bot (V2.0 兼容)
        if self.bot:
            try:
                if hasattr(self.bot, 'async_reply'):
                    res = await self.bot.async_reply(query, context)
                    return getattr(res, 'content', str(res))
                elif hasattr(self.bot, 'reply'):
                    res = self.bot.reply(query, context)
                    return getattr(res, 'content', str(res))
            except Exception as e:
                self.logger.error(f"Bot 调用失败: {e}")

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
        trace = self._build_trace_metadata(context, metadata)
        send_request_id = uuid.uuid4().hex[:12]
        send_started_at = time.perf_counter()
        reply_length, reply_hash = self._fingerprint(reply)
        try:
            # 从metadata中提取必要信息
            shop_id = metadata.get('shop_id')
            user_id = metadata.get('user_id')
            from_uid = metadata.get('from_uid')
            trace["shop_id"] = str(shop_id or trace.get("shop_id") or "unknown")
            trace["user_id"] = str(user_id or trace.get("user_id") or "")
            trace["customer_uid"] = str(from_uid or trace.get("customer_uid") or "")

            if not all([shop_id, user_id, from_uid]):
                duration_ms = int((time.perf_counter() - send_started_at) * 1000)
                self.logger.warning(
                    "event=pdd.reply.send.failed "
                    + self._trace_fields(
                        trace,
                        send_request_id=send_request_id,
                        action="missing_send_fields",
                        duration_ms=duration_ms,
                        pdd_result="not_called",
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                        error_type="MissingSendFields",
                    )
                )
                self.logger.info(
                    "event=pdd.message.completed "
                    + self._trace_fields(
                        trace,
                        send_request_id=send_request_id,
                        final_status="reply_send_failed",
                        duration_ms=duration_ms,
                        pdd_result="not_called",
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                self.logger.warning(f"缺少发送信息: shop_id={shop_id}, user_id={user_id}, from_uid={from_uid}")
                return False

            # 尝试发送消息
            from Channel.pinduoduo.utils.API.send_message import SendMessage
            sender = SendMessage(shop_id, user_id)
            import asyncio
            self.logger.debug(
                "event=pdd.reply.send.started "
                + self._trace_fields(
                    trace,
                    send_request_id=send_request_id,
                    action="send_text",
                    duration_ms=0,
                    pdd_result="pending",
                    reply_length=reply_length,
                    reply_hash=reply_hash,
                )
            )
            result = await asyncio.to_thread(sender.send_text, from_uid, reply)
            pdd_result = result.get("result") if isinstance(result, dict) else None
            pdd_ok = isinstance(pdd_result, dict) and pdd_result.get("result") == "ok"
            pdd_result_summary = self._pdd_result_summary(result)
            duration_ms = int((time.perf_counter() - send_started_at) * 1000)
            if isinstance(result, dict) and result.get("success") and pdd_ok:
                self.logger.info(
                    "event=pdd.reply.send.succeeded "
                    + self._trace_fields(
                        trace,
                        send_request_id=send_request_id,
                        action="send_text",
                        duration_ms=duration_ms,
                        pdd_result=pdd_result_summary,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                self.logger.info(
                    "event=pdd.message.completed "
                    + self._trace_fields(
                        trace,
                        send_request_id=send_request_id,
                        final_status="reply_sent",
                        duration_ms=duration_ms,
                        pdd_result=pdd_result_summary,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                self.logger.info(
                    f"[发送回执] 文本消息接口成功: shop_id={shop_id}, user_id={user_id}, "
                    f"from_uid={from_uid}, pdd_result={pdd_result_summary}"
                )
                return True
            if isinstance(result, dict) and result.get("success") and not isinstance(pdd_result, dict):
                self.logger.warning(
                    "event=pdd.reply.send.call_succeeded "
                    + self._trace_fields(
                        trace,
                        send_request_id=send_request_id,
                        action="send_text",
                        status="unknown_delivery",
                        duration_ms=duration_ms,
                        pdd_result=pdd_result_summary,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                self.logger.info(
                    "event=pdd.message.completed "
                    + self._trace_fields(
                        trace,
                        send_request_id=send_request_id,
                        final_status="reply_delivery_unknown",
                        duration_ms=duration_ms,
                        pdd_result=pdd_result_summary,
                        reply_length=reply_length,
                        reply_hash=reply_hash,
                    )
                )
                self._alert_manual_transfer(
                    metadata,
                    f"{metadata.get('shop_id')}_{from_uid}",
                    f"PDD send failed: pdd_result={pdd_result_summary}",
                    "high",
                )
                return False
            self._alert_manual_transfer(
                metadata,
                f"{metadata.get('shop_id')}_{from_uid}",
                f"PDD send failed: pdd_result={pdd_result_summary}",
                "high",
            )
            self.logger.warning(
                "event=pdd.reply.send.failed "
                + self._trace_fields(
                    trace,
                    send_request_id=send_request_id,
                    action="send_text",
                    duration_ms=duration_ms,
                    pdd_result=pdd_result_summary,
                    reply_length=reply_length,
                    reply_hash=reply_hash,
                    error_type="PddSendFailed",
                )
            )
            self.logger.info(
                "event=pdd.message.completed "
                + self._trace_fields(
                    trace,
                    send_request_id=send_request_id,
                    final_status="reply_send_failed",
                    duration_ms=duration_ms,
                    pdd_result=pdd_result_summary,
                    reply_length=reply_length,
                    reply_hash=reply_hash,
                )
            )
            self.logger.warning(
                f"[发送回执] 文本消息接口未确认成功: shop_id={shop_id}, user_id={user_id}, "
                f"from_uid={from_uid}, pdd_result={pdd_result_summary}"
            )
            return False

        except Exception as e:
            duration_ms = int((time.perf_counter() - send_started_at) * 1000)
            self.logger.warning(
                "event=pdd.reply.send.failed "
                + self._trace_fields(
                    trace,
                    send_request_id=send_request_id,
                    action="send_text",
                    duration_ms=duration_ms,
                    pdd_result="exception",
                    reply_length=reply_length,
                    reply_hash=reply_hash,
                    error_type=type(e).__name__,
                )
            )
            self.logger.info(
                "event=pdd.message.completed "
                + self._trace_fields(
                    trace,
                    send_request_id=send_request_id,
                    final_status="reply_send_failed",
                    duration_ms=duration_ms,
                    pdd_result="exception",
                    reply_length=reply_length,
                    reply_hash=reply_hash,
                )
            )
            self.logger.error(f"发送回复失败: {e}")
            self._alert_manual_transfer(metadata, f"{metadata.get('shop_id')}_{metadata.get('from_uid')}", f"Send reply exception: {e}", "high")
            return False


    def _alert_manual_transfer(self, metadata: Dict[str, Any], session_id: str, reason: str,
                               alert_level: str = "high") -> None:
        """Notify UI that manual intervention is required."""
        try:
            from core.di_container import container
            from core.notification import NotificationService
            notification_service = container.get(NotificationService)
            if notification_service:
                notification_service.alert_human_fallback(
                    shop_id=str(metadata.get('shop_id') or 'unknown'),
                    user_id=str(metadata.get('from_uid') or 'unknown'),
                    reason=reason,
                    alert_level=alert_level,
                )
        except Exception as alert_error:
            self.logger.warning(f"Manual transfer alert failed: {alert_error}")
    async def _handle_fallback(self, context: Context, metadata: Dict[str, Any]) -> bool:
        """备用回复处理"""
        try:
            from_uid = metadata.get('from_uid') or getattr(context.kwargs, 'from_uid', None)
            session_id = metadata.get('session_id') or f"{metadata.get('shop_id')}_{from_uid}"
            fallback_stage = self._next_fallback_stage(session_id)
            if not fallback_stage:
                self.logger.info(f"fallback 已节流，等待人工处理: session_id={session_id}")
                return True

            # 使用备用回复池随机选取，避免拼多多重复消息拦截
            reply_text = random.choice(FALLBACK_REPLY_POOL)

            # 记录备用回复
            self.logger.info(f"使用第 {fallback_stage} 次备用回复")
            self._mark_fallback_sent(session_id, fallback_stage)
            redis_manager.set_human_lock(session_id, ttl=HUMAN_LOCK_TTL)

            # 尝试发送备用回复
            success = await self._send_reply(context, reply_text, metadata)
            if not success:
                # 如果发送失败，记录日志并返回False让下游有机会处理
                reply_length, reply_hash = self._fingerprint(reply_text)
                await self.log_message(
                    context,
                    "备用回复发送失败",
                    f"reply_length={reply_length} reply_hash={reply_hash}",
                )
                return False

            reply_length, reply_hash = self._fingerprint(reply_text)
            await self.log_message(
                context,
                "备用回复发送成功",
                f"reply_length={reply_length} reply_hash={reply_hash}",
            )
            return True

        except Exception as e:
            self.logger.error(f"备用回复处理失败: {e}")
            return True  # 即使失败也返回True，避免重复处理

    def _next_fallback_stage(self, session_id: str) -> str:
        state = self._fallback_state.get(session_id, {})
        first_sent_at = float(state.get("first_sent_at") or 0)
        second_sent_at = float(state.get("second_sent_at") or 0)
        now = time.time()
        if not first_sent_at:
            return "first"
        reminder_after = max(0, HUMAN_LOCK_TTL - FALLBACK_SECOND_REMINDER_BEFORE_EXPIRY)
        if not second_sent_at and now - first_sent_at >= reminder_after:
            return "second"
        return ""

    def _mark_fallback_sent(self, session_id: str, stage: str) -> None:
        state = self._fallback_state.setdefault(session_id, {})
        now = time.time()
        if stage == "first":
            state.setdefault("first_sent_at", now)
        elif stage == "second":
            state.setdefault("second_sent_at", now)
        state["updated_at"] = now
