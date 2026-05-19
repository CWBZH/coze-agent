# 消息处理模块
"""
V2.0 新增：
- 人工静默锁心跳续期：监听商家/客服发话，自动续期锁
"""
import json
import asyncio
import hashlib
import uuid
from websockets import exceptions as ws_exceptions
from bridge.context import Context, ContextType, ChannelType
from Channel.pinduoduo.pdd_message import PDDChatMessage
from database import db_manager
from utils.logger_loguru import get_logger

# 导入 Redis 管理器
from database.redis_manager import redis_manager


class MessageHandlerMixin:
    """消息处理 Mixin"""

    def _build_trace_id(self, shop_id: str, source_message_id: str = None) -> str:
        shop_part = str(shop_id) if shop_id else "unknown"
        message_part = str(source_message_id) if source_message_id else uuid.uuid4().hex[:12]
        return f"pdd:{shop_part}:{message_part}"

    def _content_fingerprint(self, content) -> tuple[int, str]:
        content_text = "" if content is None else str(content)
        return len(content_text), hashlib.sha256(content_text.encode("utf-8")).hexdigest()[:12]

    async def _setup_message_consumer(self, queue_name: str):
        """V3.0: 设置消息消费者 — 使用 MessagePipeline 替代 CustomerAgent"""
        from Message import message_consumer_manager, queue_manager, handler_chain

        try:
            loop_id = id(asyncio.get_running_loop())
            existing_consumer = message_consumer_manager.get_consumer(queue_name)
            if existing_consumer:
                running = existing_consumer.is_running()
                same_loop = existing_consumer.is_bound_to_current_loop()
                queue = queue_manager.get_queue(queue_name)
                queue_size = queue.size() if queue and hasattr(queue, "size") else "unknown"
                self.logger.info(
                    f"Message consumer setup check: queue_name={queue_name}, loop_id={loop_id}, "
                    f"consumer_id={id(existing_consumer)}, handler_count={existing_consumer.handler_count()}, "
                    f"running={running}, same_loop={same_loop}, worker_count={existing_consumer.worker_count()}, "
                    f"queue_size={queue_size}"
                )
                if running and same_loop:
                    self.logger.info(
                        f"Reusing existing message consumer: queue_name={queue_name}, loop_id={loop_id}, "
                        f"consumer_id={id(existing_consumer)}, handler_count={existing_consumer.handler_count()}, "
                        f"running=True, consumer_running=True, worker_count={existing_consumer.worker_count()}, "
                        f"queue_size={queue_size}"
                    )
                    return
            existing_consumer = message_consumer_manager.get_consumer(queue_name)
            if existing_consumer:
                self.logger.info(
                    f"Message consumer replacement requested: queue_name={queue_name}, loop_id={loop_id}, "
                    f"consumer_id={id(existing_consumer)}, consumer_running={existing_consumer.is_running()}, "
                    f"handler_count={existing_consumer.handler_count()}, worker_count={existing_consumer.worker_count()}"
                )
                try:
                    stopped = await message_consumer_manager.stop_consumer(queue_name, timeout=5.0)
                    if not stopped:
                        self.logger.warning(
                            f"Message consumer replacement rejected: queue_name={queue_name}, loop_id={loop_id}, "
                            f"consumer_id={id(existing_consumer)}, consumer_running={existing_consumer.is_running()}, "
                            f"handler_count={existing_consumer.handler_count()}, timeout=5.0"
                        )
                        raise RuntimeError(f"consumer still running, refuse replacement: queue_name={queue_name}")
                except RuntimeError as e:
                    # Stop must finish before a replacement consumer can be created.
                    self.logger.warning(
                        f"停止旧消费者失败，拒绝替换: {queue_name}, {e}"
                    )
                    raise
                except Exception as e:
                    self.logger.warning(f"停止旧消费者失败: {queue_name}, {e}")
                remaining_consumer = message_consumer_manager.get_consumer(queue_name)
                if remaining_consumer and remaining_consumer.is_running():
                    raise RuntimeError(
                        f"consumer still running, refuse replacement: queue_name={queue_name}, "
                        f"consumer_id={id(remaining_consumer)}, handler_count={remaining_consumer.handler_count()}"
                    )
                try:
                    queue = queue_manager.get_or_create_queue(queue_name)
                    self.logger.info(
                        f"Message queue checked after consumer replacement: queue_name={queue_name}, "
                        f"loop_id={loop_id}, queue_size={queue.size() if hasattr(queue, 'size') else 'unknown'}"
                    )
                except Exception as e:
                    self.logger.warning(f"重新创建队列失败: {queue_name}, {e}")

            try:
                queue = queue_manager.get_or_create_queue(queue_name)
                self.logger.info(
                    f"Message queue ready: queue_name={queue_name}, loop_id={loop_id}, "
                    f"queue_size={queue.size() if hasattr(queue, 'size') else 'unknown'}"
                )
            except Exception as e:
                self.logger.warning(f"重新创建队列失败: {queue_name}, {e}")

            consumer = message_consumer_manager.create_consumer(queue_name, max_concurrent=10)
            self.logger.info(
                f"Message consumer create/get result: queue_name={queue_name}, loop_id={loop_id}, "
                f"consumer_id={id(consumer)}, consumer_running={consumer.is_running()}, "
                f"handler_count={consumer.handler_count()}, worker_count={consumer.worker_count()}"
            )

            # V3.0: 不再注入 CustomerAgent，handler 内部使用 MessagePipeline
            handlers = handler_chain(use_ai=True, businessHours=self.businessHours, bot=None)
            for handler in handlers:
                if handler is not None:
                    consumer.add_handler(handler)

            await message_consumer_manager.start_consumer(queue_name)
            queue = queue_manager.get_queue(queue_name)
            self.logger.info(
                f"Message consumer setup complete: queue_name={queue_name}, loop_id={loop_id}, "
                f"consumer_id={id(consumer)}, handler_count={consumer.handler_count()}, "
                f"running={consumer.is_running()}, consumer_running={consumer.is_running()}, "
                f"worker_count={consumer.worker_count()}, "
                f"queue_size={queue.size() if queue and hasattr(queue, 'size') else 'unknown'}"
            )
            self.logger.debug(f"消息消费者已启动: {queue_name}")

        except Exception as e:
            self.logger.error(f"设置消息消费者失败: {e}")
            raise

    async def _process_websocket_message(self, message: str, shop_id: str, user_id: str, username: str, queue_name: str):
        """处理单条WebSocket消息"""
        from Message import put_message

        try:
            if not message or not message.strip():
                self.logger.debug(f"收到空消息，跳过处理: {shop_id}-{username}")
                return

            message_data = json.loads(message)
            source_message_id = message_data.get("message", {}).get("msg_id")
            trace_id = self._build_trace_id(shop_id, str(source_message_id) if source_message_id else None)
            msg_type = message_data.get("message", {}).get("type", "unknown")
            from_uid_log = message_data.get("message", {}).get("from_uid", "unknown")
            from_role = message_data.get("message", {}).get("from", {}).get("role", "unknown")
            raw_content = message_data.get("message", {}).get("content")
            raw_content_length, raw_content_hash = self._content_fingerprint(raw_content)
            customer_uid = message_data.get("message", {}).get("from", {}).get("uid") or from_uid_log
            to_uid_log = message_data.get("message", {}).get("to", {}).get("uid")
            self.logger.debug(
                f"event=pdd.message.received trace_id={trace_id} source_message_id={source_message_id or ''} "
                f"queue_message_id= shop_id={shop_id} user_id={user_id} customer_uid={customer_uid or ''} "
                f"from_uid={customer_uid or ''} to_uid={to_uid_log or ''} queue_name={queue_name} "
                f"message_type={msg_type} content_length={raw_content_length} content_hash={raw_content_hash}"
            )
            self.logger.debug(
                f"收到消息: shop_id={shop_id}, user_id={user_id}, username={username}, "
                f"queue_name={queue_name}, type={msg_type}, from_uid={from_uid_log}, from_role={from_role}"
            )

            # =====================================================
            # V2.0 新增：人工客服发话检测与锁续期
            # =====================================================
            # 拼多多的客服角色标识是 "mall_cs"
            if from_role == "mall_cs":
                # 这是商家/客服自己发的消息
                # 获取对话中的用户 UID（to_uid）
                to_uid = message_data.get("message", {}).get("to", {}).get("uid")
                if to_uid:
                    # 构造 session_id 并续期人工锁
                    session_id = f"pinduoduo{to_uid}"
                    renewed = redis_manager.renew_human_lock(session_id, ttl=240)
                    if renewed:
                        ttl = redis_manager.get_lock_ttl(session_id)
                        self.logger.info(
                            f"[人工心跳] 检测到客服发话，锁已续期: "
                            f"session_id={session_id}, ttl={ttl}s"
                        )
                # 客服消息不入队，直接返回
                self.logger.debug(f"客服消息不入队: from_role={from_role}")
                return

            try:
                pdd_message = PDDChatMessage(message_data)
            except Exception as pdd_error:
                self.logger.error(f"创建PDD消息对象失败: {shop_id}-{username}, 错误: {pdd_error}")
                return

            try:
                context = self._convert_to_context(pdd_message, shop_id, user_id, username)
                if not context:
                    self.logger.debug(f"消息转换失败，跳过处理: {shop_id}-{username}")
                    self.logger.info(
                        f"event=pdd.message.skipped trace_id={trace_id} source_message_id={source_message_id or ''} "
                        f"queue_message_id= shop_id={shop_id} user_id={user_id} customer_uid={customer_uid or ''} "
                        f"queue_name={queue_name} message_type={msg_type} reason=context_empty"
                    )
                    return
                context.kwargs.trace_id = trace_id
                context.kwargs.source_message_id = str(pdd_message.msg_id) if pdd_message.msg_id is not None else str(source_message_id or "")
                context.kwargs.queue_name = queue_name
                context.kwargs.message_type = str(context.type.value if hasattr(context.type, "value") else context.type)
                context.kwargs.content_length, context.kwargs.content_hash = self._content_fingerprint(context.content)
                self.logger.debug(
                    f"event=pdd.context.created trace_id={context.kwargs.trace_id} "
                    f"source_message_id={context.kwargs.source_message_id or ''} queue_message_id= "
                    f"shop_id={shop_id} user_id={user_id} customer_uid={context.kwargs.from_uid or ''} "
                    f"from_uid={context.kwargs.from_uid or ''} to_uid={context.kwargs.to_uid or ''} "
                    f"queue_name={queue_name} message_type={context.kwargs.message_type} "
                    f"content_length={context.kwargs.content_length} content_hash={context.kwargs.content_hash}"
                )
            except Exception as ctx_error:
                self.logger.error(f"转换Context失败: {shop_id}-{username}, 错误: {ctx_error}")
                self.logger.info(
                    f"event=pdd.message.skipped trace_id={trace_id} source_message_id={source_message_id or ''} "
                    f"queue_message_id= shop_id={shop_id} user_id={user_id} customer_uid={customer_uid or ''} "
                    f"queue_name={queue_name} message_type={msg_type} reason=context_error"
                )
                return

            if context:
                if self._should_process_immediately(context):
                    await self._handle_immediate_message(context, shop_id, user_id)
                    self.logger.debug(f"立即处理消息: {context.type}, ID: {pdd_message.msg_id}")
                    self.logger.info(
                        f"event=pdd.message.skipped trace_id={context.kwargs.trace_id} "
                        f"source_message_id={context.kwargs.source_message_id or ''} queue_message_id= "
                        f"shop_id={shop_id} user_id={user_id} customer_uid={context.kwargs.from_uid or ''} "
                        f"queue_name={queue_name} message_type={context.kwargs.message_type} reason=immediate_message"
                    )
                elif self._should_queue_message(context):
                    msg_id = await put_message(queue_name, context)
                    from Message import queue_manager
                    queue = queue_manager.get_queue(queue_name)
                    queue_size = queue.size() if queue and hasattr(queue, 'size') else 'unknown'
                    self.logger.debug(
                        f"消息已入队: queue_name={queue_name}, ID={msg_id}, 类型={context.type}, "
                        f"shop_id={shop_id}, user_id={user_id}, "
                        f"queue_size={queue_size}"
                    )
                    self.logger.debug(
                        f"event=pdd.message.queued trace_id={context.kwargs.trace_id} "
                        f"source_message_id={context.kwargs.source_message_id or ''} queue_message_id={msg_id} "
                        f"shop_id={shop_id} user_id={user_id} customer_uid={context.kwargs.from_uid or ''} "
                        f"from_uid={context.kwargs.from_uid or ''} to_uid={context.kwargs.to_uid or ''} "
                        f"queue_name={queue_name} message_type={context.kwargs.message_type} "
                        f"content_length={context.kwargs.content_length} content_hash={context.kwargs.content_hash} "
                        f"queue_size={queue_size}"
                    )
                else:
                    self.logger.debug(f"忽略消息: {context.type}, ID: {pdd_message.msg_id}")
                    self.logger.info(
                        f"event=pdd.message.skipped trace_id={context.kwargs.trace_id} "
                        f"source_message_id={context.kwargs.source_message_id or ''} queue_message_id= "
                        f"shop_id={shop_id} user_id={user_id} customer_uid={context.kwargs.from_uid or ''} "
                        f"queue_name={queue_name} message_type={context.kwargs.message_type} reason=unsupported_type"
                    )
            else:
                self.logger.warning("消息转换失败，跳过处理")
                self.logger.info(
                    f"event=pdd.message.skipped trace_id={trace_id} source_message_id={source_message_id or ''} "
                    f"queue_message_id= shop_id={shop_id} user_id={user_id} customer_uid={customer_uid or ''} "
                    f"queue_name={queue_name} message_type={msg_type} reason=context_missing"
                )

        except json.JSONDecodeError:
            raw_length, raw_hash = self._content_fingerprint(message)
            self.logger.error(f"JSON解析失败: content_length={raw_length}, content_hash={raw_hash}")
        except Exception as e:
            self.logger.error(f"处理WebSocket消息失败: {e}")

    def _should_process_immediately(self, context: Context) -> bool:
        """判断消息是否需要立即处理"""
        immediate_types = {
            ContextType.SYSTEM_STATUS,
            ContextType.AUTH,
            ContextType.WITHDRAW,
            ContextType.SYSTEM_HINT,
            ContextType.MALL_CS,
            ContextType.TRANSFER
        }
        return context.type in immediate_types

    def _should_queue_message(self, context: Context) -> bool:
        """判断消息是否需要放入队列处理"""
        queue_types = {
            ContextType.TEXT,
            ContextType.IMAGE,
            ContextType.VIDEO,
            ContextType.EMOTION,
            ContextType.GOODS_INQUIRY,
            ContextType.ORDER_INFO,
            ContextType.GOODS_CARD,
            ContextType.GOODS_SPEC,
        }
        return context.type in queue_types

    async def _handle_immediate_message(self, context: Context, shop_id: str, user_id: str):
        """立即处理消息"""
        username = context.kwargs.username
        recipient_uid = context.kwargs.from_uid
        content_length, content_hash = self._content_fingerprint(context.content)
        message_type = context.type.value if hasattr(context.type, "value") else context.type
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage
            send_message = SendMessage(shop_id, user_id)
            if context.type == ContextType.AUTH:
                auth_info = context.content
                if isinstance(auth_info, dict):
                    result = auth_info.get('result')
                    if result == 'ok':
                        self.logger.info(f"{username}认证成功")
                    else:
                        self.logger.warning(f"{username}认证失败")

            elif context.type == ContextType.WITHDRAW:
                self.logger.info(
                    f"收到撤回消息: message_type={message_type}, content_length={content_length}, content_hash={content_hash}"
                )
                await asyncio.to_thread(send_message.send_text, recipient_uid, "[玫瑰]")

            elif context.type == ContextType.SYSTEM_STATUS:
                self.logger.debug(
                    f"系统状态消息: message_type={message_type}, content_length={content_length}, content_hash={content_hash}"
                )

            elif context.type == ContextType.SYSTEM_HINT:
                self.logger.info(
                    f"系统提示: message_type={message_type}, content_length={content_length}, content_hash={content_hash}"
                )

            elif context.type == ContextType.MALL_CS:
                self.logger.debug(
                    f"收到客服消息: message_type={message_type}, content_length={content_length}, content_hash={content_hash}"
                )

            elif context.type == ContextType.SYSTEM_BIZ:
                self.logger.info(
                    f"系统业务消息: message_type={message_type}, content_length={content_length}, content_hash={content_hash}"
                )

            elif context.type == ContextType.MALL_SYSTEM_MSG:
                self.logger.info(
                    f"商城系统消息: message_type={message_type}, content_length={content_length}, content_hash={content_hash}"
                )

            elif context.type == ContextType.TRANSFER:
                self.logger.info(
                    f"转接消息: message_type={message_type}, content_length={content_length}, content_hash={content_hash}"
                )
                await asyncio.to_thread(send_message.send_text, recipient_uid, "[玫瑰]")

        except Exception as e:
            self.logger.error(f"立即处理消息失败: {e}")

    def _convert_to_context(self, pdd_message: PDDChatMessage, shop_id: str, user_id: str, username: str) -> Context:
        """将拼多多消息转换为Context格式"""
        shop_info = db_manager.get_shop(self.channel_name, shop_id)
        shop_name = shop_info.get("shop_name", "")

        context_type = pdd_message.user_msg_type

        content = pdd_message.content
        # 从content中提取goods_id（商品咨询/规格咨询/订单信息消息）
        goods_id = None
        if isinstance(content, dict):
            goods_id = content.get("goods_id")
            content = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content = ""
        else:
            content = str(content)

        context = Context.create_pinduoduo_context(
            content=content,
            msg_id=str(pdd_message.msg_id) if pdd_message.msg_id is not None else "",
            from_user=str(pdd_message.from_user) if pdd_message.from_user is not None else "",
            from_uid=str(pdd_message.from_uid) if pdd_message.from_uid is not None else "",
            to_user=str(pdd_message.to_user) if pdd_message.to_user is not None else "",
            to_uid=str(pdd_message.to_uid) if pdd_message.to_uid is not None else "",
            nickname=str(pdd_message.nickname) if pdd_message.nickname is not None else "",
            timestamp=pdd_message.timestamp,
            user_msg_type=pdd_message.user_msg_type,
            shop_id=str(shop_id),
            user_id=str(user_id),
            username=str(username),
            shop_name=str(shop_name),
            goods_id=str(goods_id) if goods_id else None,
            raw_data=pdd_message.raw_data,
            channel_type=ChannelType.PINDUODUO,
            source_message_id=str(pdd_message.source_message_id) if getattr(pdd_message, "source_message_id", None) is not None else "",
        )
        return context


__all__ = ['MessageHandlerMixin']
