"""
简化的消息消费者实现
移除复杂的用户隔离机制，保持核心功能
"""

import asyncio
from typing import List, Dict, Any
from utils.logger_loguru import get_logger
from bridge.context import Context
from .queue import queue_manager
from .handlers import MessageHandler
from ..models.queue_models import MessageWrapper


logger = get_logger(__name__)


class MessageConsumer:
    """消息消费者 - 简化版"""

    def __init__(self, queue_name: str, max_concurrent: int = 10):
        self.queue_name = queue_name
        self.max_concurrent = max_concurrent
        self.handlers: List[MessageHandler] = []
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.running = False
        self.consumer_task = None
        self._tasks: set = set()
        self._worker_tasks: set = set()
        self._loop = None
        self.logger = get_logger(f"Consumer.{queue_name}")

    def add_handler(self, handler: MessageHandler):
        """添加处理器"""
        if handler is None:
            return
        handler_key = self._handler_key(handler)
        for existing in self.handlers:
            if self._handler_key(existing) == handler_key:
                self.logger.debug(
                    f"Handler already registered: queue_name={self.queue_name}, "
                    f"handler={handler_key}, handler_count={len(self.handlers)}"
                )
                return
        self.handlers.append(handler)
        self.logger.debug(
            f"Added handler: queue_name={self.queue_name}, handler={handler_key}, "
            f"handler_count={len(self.handlers)}"
        )

    def is_running(self) -> bool:
        """检查消费者是否正在运行"""
        if not self.running:
            return False
        self._worker_tasks = {task for task in self._worker_tasks if not task.done()}
        if not self._worker_tasks:
            self.running = False
            return False
        return True

    def is_bound_to_current_loop(self) -> bool:
        """Return True when this consumer belongs to the active asyncio loop."""
        if self._loop is None:
            return True
        try:
            return self._loop is asyncio.get_running_loop()
        except RuntimeError:
            return True

    def loop_id(self) -> str:
        return str(id(self._loop)) if self._loop is not None else "none"

    def handler_count(self) -> int:
        return len(self.handlers)

    def worker_count(self) -> int:
        return len([task for task in self._worker_tasks if not task.done()])

    def worker_task_ids(self) -> List[int]:
        return [id(task) for task in self._worker_tasks if not task.done()]

    def queue_size(self) -> Any:
        queue = queue_manager.get_queue(self.queue_name)
        if queue and hasattr(queue, "size"):
            return queue.size()
        return "unknown"

    def diagnostic_state(self) -> Dict[str, Any]:
        return {
            "queue_name": self.queue_name,
            "loop_id": self.loop_id(),
            "consumer_id": id(self),
            "handler_count": len(self.handlers),
            "running": self.is_running(),
            "worker_count": self.worker_count(),
            "worker_task_ids": self.worker_task_ids(),
            "queue_size": self.queue_size(),
        }

    def _handler_key(self, handler: MessageHandler) -> str:
        cls = handler.__class__
        return f"{cls.__module__}.{cls.__name__}"

    async def start(self):
        """启动消费者"""
        if self.is_running():
            self.logger.warning(
                f"Consumer already running: queue_name={self.queue_name}, "
                f"loop_id={self.loop_id()}, consumer_id={id(self)}, "
                f"handler_count={len(self.handlers)}, running=True, "
                f"worker_count={self.worker_count()}, max_concurrent={self.max_concurrent}, "
                f"queue_size={self.queue_size()}"
            )
            return

        self._loop = asyncio.get_running_loop()
        self.running = True
        self.consumer_task = None
        self._worker_tasks = {
            asyncio.create_task(self._worker_loop(worker_id))
            for worker_id in range(self.max_concurrent)
        }
        self.logger.info(
            f"Consumer started: queue_name={self.queue_name}, loop_id={self.loop_id()}, "
            f"consumer_id={id(self)}, handler_count={len(self.handlers)}, running=True, "
            f"worker_count={self.worker_count()}, max_concurrent={self.max_concurrent}, "
            f"worker_task_ids={self.worker_task_ids()}, queue_size={self.queue_size()}"
        )

    async def _consume_loop(self):
        """消费循环"""
        queue = queue_manager.get_or_create_queue(self.queue_name)

        try:
            while self.running:
                try:
                    wrapper = await queue.get(timeout=1.0)
                    if wrapper:
                        # 使用信号量控制并发数，跟踪任务以便优雅停止
                        await self._process_message(wrapper)
                except RuntimeError as e:
                    if "bound to a different event loop" in str(e):
                        self.logger.error(f"Consumer {self.queue_name} stopped: queue is bound to another event loop")
                        self.running = False
                        break
                    self.logger.error(f"Consumer error: {e}")
                    await asyncio.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"Consumer error: {e}")
                    await asyncio.sleep(0.1)
        finally:
            self.running = False
            self.logger.info(
                f"Consumer stopped: queue_name={self.queue_name}, loop_id={self.loop_id()}, "
                f"consumer_id={id(self)}, handler_count={len(self.handlers)}, running=False"
            )

    async def _worker_loop(self, worker_id: int):
        """Fixed worker loop for the worker pool."""
        queue = queue_manager.get_or_create_queue(self.queue_name)

        try:
            while self.running:
                try:
                    wrapper = await queue.get(timeout=1.0)
                    if wrapper:
                        metadata = wrapper.to_metadata()
                        self.logger.debug(
                            f"event=pdd.consumer.dequeued trace_id={metadata.get('trace_id') or ''} "
                            f"source_message_id={metadata.get('source_message_id') or ''} "
                            f"queue_message_id={metadata.get('queue_message_id') or metadata.get('message_id') or ''} "
                            f"shop_id={metadata.get('shop_id') or ''} user_id={metadata.get('user_id') or ''} "
                            f"customer_uid={metadata.get('from_uid') or ''} queue_name={metadata.get('queue_name') or self.queue_name} "
                            f"message_type={metadata.get('message_type') or ''} "
                            f"content_length={metadata.get('content_length')} content_hash={metadata.get('content_hash') or ''} "
                            f"consumer_id={id(self)} worker_id={worker_id} queue_size={self.queue_size()}"
                        )
                        await self._process_message(wrapper)
                except asyncio.CancelledError:
                    self.logger.debug(
                        f"Consumer worker cancelled: queue_name={self.queue_name}, "
                        f"loop_id={self.loop_id()}, consumer_id={id(self)}, worker_id={worker_id}"
                    )
                    raise
                except RuntimeError as e:
                    if "bound to a different event loop" in str(e):
                        self.logger.error(
                            f"Consumer worker stopped: queue_name={self.queue_name}, "
                            f"loop_id={self.loop_id()}, consumer_id={id(self)}, "
                            f"worker_id={worker_id}, reason=queue_bound_to_another_event_loop"
                        )
                        self.running = False
                        break
                    self.logger.error(
                        f"Consumer worker error: queue_name={self.queue_name}, "
                        f"loop_id={self.loop_id()}, consumer_id={id(self)}, "
                        f"worker_id={worker_id}, error={e}"
                    )
                    await asyncio.sleep(0.1)
                except Exception as e:
                    self.logger.error(
                        f"Consumer worker error: queue_name={self.queue_name}, "
                        f"loop_id={self.loop_id()}, consumer_id={id(self)}, "
                        f"worker_id={worker_id}, error={e}"
                    )
                    await asyncio.sleep(0.1)
        finally:
            self.logger.debug(
                f"Consumer worker exited: queue_name={self.queue_name}, loop_id={self.loop_id()}, "
                f"consumer_id={id(self)}, worker_id={worker_id}, running={self.running}, "
                f"queue_size={self.queue_size()}"
            )

    async def stop(self):
        """停止消费者（安全处理跨事件循环）"""
        self.logger.info(
            f"Consumer stop requested: queue_name={self.queue_name}, loop_id={self.loop_id()}, "
            f"consumer_id={id(self)}, handler_count={len(self.handlers)}, running={self.running}, "
            f"worker_count={self.worker_count()}, queue_size={self.queue_size()}"
        )
        self.running = False

        # 取消消费任务（处理跨 loop 场景）
        worker_tasks = [task for task in self._worker_tasks if not task.done()]
        self.logger.info(
            f"Consumer worker cancel requested: queue_name={self.queue_name}, loop_id={self.loop_id()}, "
            f"consumer_id={id(self)}, worker_count={len(worker_tasks)}, "
            f"worker_task_ids={[id(task) for task in worker_tasks]}, timeout=5.0"
        )
        for task in worker_tasks:
            task.cancel()

        if worker_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*worker_tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Consumer worker stop timeout: queue_name={self.queue_name}, "
                    f"loop_id={self.loop_id()}, consumer_id={id(self)}, "
                    f"worker_count={len(worker_tasks)}"
                )
            except RuntimeError:
                pass
        self._worker_tasks.clear()

        if hasattr(self, 'consumer_task') and self.consumer_task:
            try:
                self.consumer_task.cancel()
                await asyncio.wait_for(self.consumer_task, timeout=5.0)
            except (asyncio.CancelledError, RuntimeError):
                pass
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Consumer task stop timeout: queue_name={self.queue_name}, "
                    f"loop_id={self.loop_id()}, consumer_id={id(self)}"
                )
            finally:
                self.consumer_task = None

        # 等待所有正在处理的任务完成
        if self._tasks:
            try:
                pending = [t for t in self._tasks if not t.done()]
                if pending:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=5.0,
                    )
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Consumer processing task stop timeout: queue_name={self.queue_name}, "
                    f"loop_id={self.loop_id()}, consumer_id={id(self)}, "
                    f"task_count={len(self._tasks)}"
                )
            except RuntimeError:
                pass
            self._tasks.clear()

        self.logger.info(
            f"Consumer stopped: queue_name={self.queue_name}, loop_id={self.loop_id()}, "
            f"consumer_id={id(self)}, handler_count={len(self.handlers)}, running=False, "
            f"worker_count={self.worker_count()}, queue_size={self.queue_size()}"
        )

    async def stop_from_any_loop(self, timeout: float = 5.0) -> bool:
        """Stop this consumer, scheduling cleanup on its owner loop when needed."""
        if self.is_bound_to_current_loop():
            await asyncio.wait_for(self.stop(), timeout=timeout)
            return not self.is_running()

        if self._loop is None or self._loop.is_closed():
            self.running = False
            return not self.is_running()

        future = asyncio.run_coroutine_threadsafe(self.stop(), self._loop)
        await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
        return not self.is_running()

    async def _process_message(self, wrapper: MessageWrapper):
        """处理单个消息"""
        async with self.semaphore:
            try:
                processed = False
                metadata = wrapper.to_metadata()
                # 追加渠道上下文到metadata，供发送使用
                try:
                    kwargs = getattr(wrapper.context, 'kwargs', None)
                    if kwargs:
                        metadata['shop_id'] = getattr(kwargs, 'shop_id', None)
                        metadata['user_id'] = getattr(kwargs, 'user_id', None)
                        metadata['from_uid'] = getattr(kwargs, 'from_uid', None)
                        metadata['goods_id'] = getattr(kwargs, 'goods_id', None)
                except Exception:
                    pass
                # 保留用于日志的用户键
                metadata['user_key'] = self._extract_user_id(wrapper.context)

                for handler in self.handlers:
                    try:
                        if handler.can_handle(wrapper.context):
                            self.logger.debug(
                                f"event=pdd.handler.selected trace_id={metadata.get('trace_id') or ''} "
                                f"source_message_id={metadata.get('source_message_id') or ''} "
                                f"queue_message_id={metadata.get('queue_message_id') or metadata.get('message_id') or ''} "
                                f"shop_id={metadata.get('shop_id') or ''} user_id={metadata.get('user_id') or ''} "
                                f"customer_uid={metadata.get('from_uid') or ''} queue_name={metadata.get('queue_name') or self.queue_name} "
                                f"message_type={metadata.get('message_type') or ''} "
                                f"content_length={metadata.get('content_length')} content_hash={metadata.get('content_hash') or ''} "
                                f"consumer_id={id(self)} handler={handler.__class__.__name__}"
                            )
                            success = await handler.handle(wrapper.context, metadata)
                            if success:
                                processed = True
                                self.logger.debug(
                                    f"event=pdd.handler.completed trace_id={metadata.get('trace_id') or ''} "
                                    f"source_message_id={metadata.get('source_message_id') or ''} "
                                    f"queue_message_id={metadata.get('queue_message_id') or metadata.get('message_id') or ''} "
                                    f"shop_id={metadata.get('shop_id') or ''} user_id={metadata.get('user_id') or ''} "
                                    f"customer_uid={metadata.get('from_uid') or ''} queue_name={metadata.get('queue_name') or self.queue_name} "
                                    f"message_type={metadata.get('message_type') or ''} "
                                    f"content_length={metadata.get('content_length')} content_hash={metadata.get('content_hash') or ''} "
                                    f"consumer_id={id(self)} handler={handler.__class__.__name__} success=True"
                                )
                                self.logger.debug(f"Message {wrapper.message_id} handled by {handler.__class__.__name__}")
                                break
                    except Exception as e:
                        self.logger.warning(
                            f"event=pdd.handler.failed trace_id={metadata.get('trace_id') or ''} "
                            f"source_message_id={metadata.get('source_message_id') or ''} "
                            f"queue_message_id={metadata.get('queue_message_id') or metadata.get('message_id') or ''} "
                            f"shop_id={metadata.get('shop_id') or ''} user_id={metadata.get('user_id') or ''} "
                            f"customer_uid={metadata.get('from_uid') or ''} queue_name={metadata.get('queue_name') or self.queue_name} "
                            f"message_type={metadata.get('message_type') or ''} "
                            f"content_length={metadata.get('content_length')} content_hash={metadata.get('content_hash') or ''} "
                            f"consumer_id={id(self)} handler={handler.__class__.__name__} error={e}"
                        )
                        self.logger.error(f"Handler {handler.__class__.__name__} error: {e}")
                        # 尝试下一个处理器
                        continue

                if not processed:
                    self.logger.info(
                        f"event=pdd.message.skipped trace_id={metadata.get('trace_id') or ''} "
                        f"source_message_id={metadata.get('source_message_id') or ''} "
                        f"queue_message_id={metadata.get('queue_message_id') or metadata.get('message_id') or ''} "
                        f"shop_id={metadata.get('shop_id') or ''} user_id={metadata.get('user_id') or ''} "
                        f"customer_uid={metadata.get('from_uid') or ''} queue_name={metadata.get('queue_name') or self.queue_name} "
                        f"message_type={metadata.get('message_type') or ''} "
                        f"content_length={metadata.get('content_length')} content_hash={metadata.get('content_hash') or ''} "
                        f"consumer_id={id(self)} reason=no_handler_processed"
                    )
                    self.logger.warning(f"Message {wrapper.message_id} not processed by any handler")

            except Exception as e:
                try:
                    metadata = wrapper.to_metadata()
                except Exception:
                    metadata = {}
                self.logger.warning(
                    f"event=pdd.handler.failed trace_id={metadata.get('trace_id') or ''} "
                    f"source_message_id={metadata.get('source_message_id') or ''} "
                    f"queue_message_id={metadata.get('queue_message_id') or getattr(wrapper, 'message_id', '')} "
                    f"shop_id={metadata.get('shop_id') or ''} user_id={metadata.get('user_id') or ''} "
                    f"customer_uid={metadata.get('from_uid') or ''} queue_name={metadata.get('queue_name') or self.queue_name} "
                    f"message_type={metadata.get('message_type') or ''} "
                    f"content_length={metadata.get('content_length')} content_hash={metadata.get('content_hash') or ''} "
                    f"consumer_id={id(self)} error={e}"
                )
                self.logger.error(f"Failed to process message {wrapper.message_id}: {e}")

    def _extract_user_id(self, context: Context) -> str:
        """提取用户ID"""
        try:
            from_uid = context.kwargs.from_uid if hasattr(context, 'kwargs') else None
            channel = context.channel_type

            # 处理可能的None值
            if from_uid is None:
                from_uid = "unknown"
            if channel is None:
                channel = "unknown"

            # 处理channel可能是字符串或枚举对象的情况
            if hasattr(channel, 'value'):
                channel_str = str(channel.value)
            else:
                channel_str = str(channel)

            return f"{channel_str}_{from_uid}"
        except Exception as e:
            self.logger.error(f"Failed to extract user ID: {e}")
            return "unknown_unknown"


class MessageConsumerManager:
    """消息消费者管理器"""

    def __init__(self):
        self._consumers: Dict[str, MessageConsumer] = {}
        self.logger = get_logger("ConsumerManager")

    def create_consumer(self, queue_name: str, max_concurrent: int = 10) -> MessageConsumer:
        """创建消费者"""
        existing = self._consumers.get(queue_name)
        if existing:
            state = existing.diagnostic_state()
            self.logger.warning(
                f"Consumer already exists: queue_name={state['queue_name']}, "
                f"loop_id={state['loop_id']}, consumer_id={state['consumer_id']}, "
                f"handler_count={state['handler_count']}, running={state['running']}, "
                f"worker_count={state['worker_count']}, queue_size={state['queue_size']}"
            )
            if existing.is_running():
                return existing
            self._consumers.pop(queue_name, None)

        consumer = MessageConsumer(queue_name, max_concurrent)
        self._consumers[queue_name] = consumer
        state = consumer.diagnostic_state()
        self.logger.info(
            f"Created consumer: queue_name={state['queue_name']}, loop_id={state['loop_id']}, "
            f"consumer_id={state['consumer_id']}, handler_count={state['handler_count']}, "
            f"running={state['running']}, worker_count={state['worker_count']}, "
            f"queue_size={state['queue_size']}"
        )
        return consumer

    def get_consumer(self, queue_name: str) -> MessageConsumer:
        """获取消费者"""
        return self._consumers.get(queue_name)

    async def start_consumer(self, queue_name: str):
        """启动消费者"""
        consumer = self.get_consumer(queue_name)
        if consumer:
            await consumer.start()
        else:
            self.logger.error(f"Consumer {queue_name} not found")

    async def stop_consumer(self, queue_name: str, timeout: float = 5.0, missing_ok: bool = False) -> bool:
        """停止消费者（安全处理跨事件循环）"""
        consumer = self.get_consumer(queue_name)
        if consumer:
            state = consumer.diagnostic_state()
            self.logger.info(
                f"Stopping consumer: queue_name={state['queue_name']}, loop_id={state['loop_id']}, "
                f"consumer_id={state['consumer_id']}, handler_count={state['handler_count']}, "
                f"running={state['running']}, consumer_running={state['running']}, "
                f"worker_count={state['worker_count']}, queue_size={state['queue_size']}, "
                f"timeout={timeout}"
            )
            try:
                stopped = await consumer.stop_from_any_loop(timeout=timeout)
                if not stopped and consumer.is_running():
                    self.logger.warning(
                        f"Consumer still running after stop timeout: queue_name={queue_name}, "
                        f"loop_id={consumer.loop_id()}, consumer_id={id(consumer)}, "
                        f"handler_count={consumer.handler_count()}, running=True"
                    )
                    return False
                self._consumers.pop(queue_name, None)
                self.logger.info(
                    f"Consumer stopped and removed: queue_name={queue_name}, "
                    f"loop_id={consumer.loop_id()}, consumer_id={id(consumer)}, "
                    f"handler_count={consumer.handler_count()}, running={consumer.is_running()}, "
                    f"consumer_running={consumer.is_running()}, worker_count={consumer.worker_count()}, "
                    f"queue_size={consumer.queue_size()}"
                )
                return True
            except RuntimeError as e:
                self.logger.warning(f"Consumer {queue_name} 停止失败（可能已跨事件循环）: {e}")
                if consumer.is_running():
                    self.logger.warning(
                        f"Consumer stop failed and consumer is still running: queue_name={queue_name}, "
                        f"loop_id={consumer.loop_id()}, consumer_id={id(consumer)}, "
                        f"handler_count={consumer.handler_count()}, error={e}"
                    )
                    return False
                self._consumers.pop(queue_name, None)
                return True
            except Exception as e:
                self.logger.warning(f"Consumer {queue_name} 停止异常: {e}")
                if consumer.is_running():
                    self.logger.warning(
                        f"Consumer stop failed and consumer is still running: queue_name={queue_name}, "
                        f"loop_id={consumer.loop_id()}, consumer_id={id(consumer)}, "
                        f"handler_count={consumer.handler_count()}, error={e}"
                    )
                    return False
                self._consumers.pop(queue_name, None)
                return True
        else:
            if missing_ok:
                self.logger.info(f"Consumer already absent: queue_name={queue_name}, missing_ok=True")
                return True
            self.logger.error(f"Consumer {queue_name} not found")
            return True

    def force_remove(self, queue_name: str) -> bool:
        """强制移除消费者（不清除资源，用于 event loop 已死的场景）"""
        consumer = self._consumers.get(queue_name)
        if not consumer:
            return True
        state = consumer.diagnostic_state()
        if consumer.is_running():
            self.logger.warning(
                f"Refuse to force remove running consumer: queue_name={state['queue_name']}, "
                f"loop_id={state['loop_id']}, consumer_id={state['consumer_id']}, "
                f"handler_count={state['handler_count']}, running=True"
            )
            return False
        del self._consumers[queue_name]
        self.logger.info(
            f"Force removed stopped consumer: queue_name={state['queue_name']}, "
            f"loop_id={state['loop_id']}, consumer_id={state['consumer_id']}, "
            f"handler_count={state['handler_count']}, running={state['running']}"
        )
        return True

    def list_consumers(self) -> List[str]:
        """列出所有消费者"""
        return list(self._consumers.keys())

    async def stop_all(self):
        """停止所有消费者"""
        for consumer in self._consumers.values():
            await consumer.stop()
        self.logger.info("All consumers stopped")


# 全局消费者管理器实例
message_consumer_manager = MessageConsumerManager()
