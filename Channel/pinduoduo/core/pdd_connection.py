# 连接管理模块
import asyncio
import websockets
from websockets import exceptions as ws_exceptions
from typing import Optional, Any
from utils.logger_loguru import get_logger


class ConnectionMixin:
    """连接管理 Mixin"""

    base_url: str = "wss://m-ws.pinduoduo.com/"

    async def _connect_with_retry(self, shop_id: str, user_id: str, username: str, on_success: callable, on_failure: callable):
        """带重连机制的WebSocket连接"""
        logger = get_logger("PDDChannel")
        connection_key = f"{shop_id}_{user_id}"
        stop_event = self._stop_events.get(connection_key, self._stop_event) if hasattr(self, "_stop_events") else self._stop_event

        for attempt in range(self.reconnect_config.max_attempts):
            if stop_event and stop_event.is_set():
                logger.info(f"收到停止信号，取消重连: {shop_id}-{username}")
                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                return

            try:
                if attempt > 0:
                    self.status_manager.update_status(shop_id, user_id, username, ConnectionState.RECONNECTING)
                    logger.info(f"尝试重连 ({attempt + 1}/{self.reconnect_config.max_attempts}): {shop_id}-{username}")

                failure_callback = (
                    lambda error_msg: logger.warning(
                        f"连接尝试失败: {shop_id}-{username}, 错误: {error_msg}"
                    )
                )

                await self._connect_single_attempt(shop_id, user_id, username, on_success, failure_callback)
                return

            except Exception as e:
                if stop_event and stop_event.is_set():
                    logger.info(f"连接被停止信号中断: {shop_id}-{username}")
                    self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                    return

                if attempt == self.reconnect_config.max_attempts - 1:
                    self.status_manager.update_status(shop_id, user_id, username, ConnectionState.SUSPENDED, str(e))
                    logger.error(f"连接失败，已达到最大重试次数: {shop_id}-{username}, 错误: {str(e)}")
                    on_failure(f"连接失败，已达到最大重试次数: {e}")
                    if stop_event:
                        stop_event.set()
                    return

                delay = min(
                    self.reconnect_config.initial_delay * (self.reconnect_config.backoff_factor ** attempt),
                    self.reconnect_config.max_delay
                )

                logger.warning(f"连接失败，{delay:.1f}秒后重试: {shop_id}-{username}, 错误: {str(e)}")

                try:
                    for _ in range(int(delay * 10)):
                        if stop_event and stop_event.is_set():
                            logger.info(f"重连延迟被停止信号中断: {shop_id}-{username}")
                            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                            return
                        try:
                            await asyncio.sleep(0.1)
                        except RuntimeError:
                            logger.info(f"事件循环关闭，退出重连延迟: {shop_id}-{username}")
                            return
                except (asyncio.CancelledError, RuntimeError):
                    logger.info(f"重连延迟被中断或事件循环关闭: {shop_id}-{username}")
                    self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                    return

    async def _connect_single_attempt(self, shop_id: str, user_id: str, username: str, on_success: callable, on_failure: callable):
        """单次WebSocket连接尝试"""
        await self.init(shop_id, user_id, username, on_success, on_failure)

    def _is_ws_closed(self, ws: Any) -> bool:
        """检查WebSocket是否已关闭"""
        try:
            closed = getattr(ws, "closed", None)
            if isinstance(closed, bool):
                return closed
            return False
        except Exception:
            return False

    async def _safe_close_websocket(self, ws: Any):
        """安全关闭WebSocket"""
        try:
            close_fn = getattr(ws, "close", None)
            if close_fn:
                result = close_fn()
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            self.logger.debug(f"关闭WebSocket失败: {e}")


# 延迟导入避免循环依赖
from core.connection_status import ConnectionState
__all__ = ['ConnectionMixin']
