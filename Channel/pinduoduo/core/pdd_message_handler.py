# 消息处理模块
"""
V2.0 新增：
- 人工静默锁心跳续期：监听商家/客服发话，自动续期锁
"""
import json
import asyncio
from websockets import exceptions as ws_exceptions
from bridge.context import Context, ContextType, ChannelType
from Channel.pinduoduo.pdd_message import PDDChatMessage
from database import db_manager
from utils.logger_loguru import get_logger

# 导入 Redis 管理器
from database.redis_manager import redis_manager


class MessageHandlerMixin:
    """消息处理 Mixin"""

    async def _setup_message_consumer(self, queue_name: str):
        """V3.0: 设置消息消费者 — 使用 MessagePipeline 替代 CustomerAgent"""
        from Message import message_consumer_manager, queue_manager, handler_chain

        try:
            existing_consumer = message_consumer_manager.get_consumer(queue_name)
            if existing_consumer:
                self.logger.info(f"消费者 {queue_name} 已存在，先停止并重新创建")
                try:
                    await message_consumer_manager.stop_consumer(queue_name)
                except Exception as e:
                    self.logger.warning(f"停止旧消费者失败: {queue_name}, {e}")
                try:
                    queue_manager.recreate_queue(queue_name)
                except Exception as e:
                    self.logger.warning(f"重新创建队列失败: {queue_name}, {e}")

            consumer = message_consumer_manager.create_consumer(queue_name, max_concurrent=10)

            # V3.0: 不再注入 CustomerAgent，handler 内部使用 MessagePipeline
            handlers = handler_chain(use_ai=True, businessHours=self.businessHours, bot=None)
            for handler in handlers:
                if handler is not None:
                    consumer.add_handler(handler)

            await message_consumer_manager.start_consumer(queue_name)
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
            msg_type = message_data.get("message", {}).get("type", "unknown")
            from_uid_log = message_data.get("message", {}).get("from_uid", "unknown")
            from_role = message_data.get("message", {}).get("from", {}).get("role", "unknown")
            self.logger.debug(f"收到消息: type={msg_type}, from_uid={from_uid_log}, from_role={from_role}")

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
                    return
            except Exception as ctx_error:
                self.logger.error(f"转换Context失败: {shop_id}-{username}, 错误: {ctx_error}")
                return

            if context:
                if self._should_process_immediately(context):
                    await self._handle_immediate_message(context, shop_id, user_id)
                    self.logger.debug(f"立即处理消息: {context.type}, ID: {pdd_message.msg_id}")
                elif self._should_queue_message(context):
                    msg_id = await put_message(queue_name, context)
                    self.logger.debug(f"消息已入队: {queue_name}, ID: {msg_id}, 类型: {context.type}")
                else:
                    self.logger.debug(f"忽略消息: {context.type}, ID: {pdd_message.msg_id}")
            else:
                self.logger.warning("消息转换失败，跳过处理")

        except json.JSONDecodeError:
            self.logger.error(f"JSON解析失败: {message}")
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
                self.logger.info(f"收到撤回消息: {context.content}")
                send_message.send_text(recipient_uid, "[玫瑰]")

            elif context.type == ContextType.SYSTEM_STATUS:
                self.logger.debug(f"系统状态消息: {context.content}")

            elif context.type == ContextType.SYSTEM_HINT:
                self.logger.info(f"系统提示: {context.content}")

            elif context.type == ContextType.MALL_CS:
                self.logger.debug(f"收到客服消息: {context.content}")

            elif context.type == ContextType.SYSTEM_BIZ:
                self.logger.info(f"系统业务消息: {context.content}")

            elif context.type == ContextType.MALL_SYSTEM_MSG:
                self.logger.info(f"商城系统消息: {context.content}")

            elif context.type == ContextType.TRANSFER:
                self.logger.info(f"转接消息: {context.content}")
                send_message.send_text(recipient_uid, "[玫瑰]")

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
            channel_type=ChannelType.PINDUODUO
        )
        return context


__all__ = ['MessageHandlerMixin']
