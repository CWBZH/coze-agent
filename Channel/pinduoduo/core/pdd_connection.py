# 连接管理模块
import asyncio
import websockets
from websockets import exceptions as ws_exceptions
from typing import Optional, Any
from utils.logger_loguru import get_logger


class ConnectionMixin:
    """连接管理 Mixin"""

    base_url: str = "wss://m-ws.pinduoduo.com/"

    def _generation_is_current(self, connection_key: str, generation: int = None) -> bool:
        if generation is None or not hasattr(self, "_is_current_generation"):
            return True
        return self._is_current_generation(connection_key, generation)

    async def _connect_with_retry(
        self,
        shop_id: str,
        user_id: str,
        username: str,
        on_success: callable,
        on_failure: callable,
        generation: int = None,
    ):
        """带重连机制的 WebSocket 连接"""
        logger = get_logger("PDDChannel")
        connection_key = f"{shop_id}_{user_id}"
        stop_event = self._stop_events.get(connection_key, self._stop_event) if hasattr(self, "_stop_events") else self._stop_event

        for attempt in range(self.reconnect_config.max_attempts):
            if not self._generation_is_current(connection_key, generation):
                logger.info(
                    f"Stale reconnect task skipped: connection_key={connection_key}, "
                    f"shop_id={shop_id}, user_id={user_id}, generation={generation}, "
                    f"reconnect_attempt={attempt + 1}, loop_id={id(asyncio.get_running_loop())}"
                )
                return

            if stop_event and stop_event.is_set():
                logger.info(
                    f"收到停止信号，取消重连: shop_id={shop_id}, user_id={user_id}, "
                    f"username={username}, connection_key={connection_key}, generation={generation}, "
                    f"reconnect_attempt={attempt + 1}, loop_id={id(asyncio.get_running_loop())}"
                )
                if self._generation_is_current(connection_key, generation):
                    self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                return

            try:
                if attempt > 0:
                    if self._generation_is_current(connection_key, generation):
                        self.status_manager.update_status(shop_id, user_id, username, ConnectionState.RECONNECTING)
                    logger.info(
                        f"尝试重连 ({attempt + 1}/{self.reconnect_config.max_attempts}): "
                        f"shop_id={shop_id}, user_id={user_id}, username={username}, "
                        f"connection_key={connection_key}, generation={generation}, "
                        f"reconnect_attempt={attempt + 1}, loop_id={id(asyncio.get_running_loop())}"
                    )

                failure_callback = (
                    lambda error_msg: logger.warning(
                        f"连接尝试失败: shop_id={shop_id}, user_id={user_id}, username={username}, "
                        f"connection_key={connection_key}, generation={generation}, "
                        f"reconnect_attempt={attempt + 1}, 错误: {error_msg}"
                    )
                )

                await self._connect_single_attempt(
                    shop_id,
                    user_id,
                    username,
                    on_success,
                    failure_callback,
                    generation=generation,
                )
                return

            except Exception as e:
                if not self._generation_is_current(connection_key, generation):
                    logger.info(
                        f"Stale reconnect failure skipped: connection_key={connection_key}, "
                        f"shop_id={shop_id}, user_id={user_id}, generation={generation}, "
                        f"reconnect_attempt={attempt + 1}, error={e}"
                    )
                    return

                if stop_event and stop_event.is_set():
                    logger.info(
                        f"连接被停止信号中断: shop_id={shop_id}, user_id={user_id}, username={username}, "
                        f"connection_key={connection_key}, generation={generation}, "
                        f"reconnect_attempt={attempt + 1}"
                    )
                    if self._generation_is_current(connection_key, generation):
                        self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                    return

                if attempt == self.reconnect_config.max_attempts - 1:
                    if self._generation_is_current(connection_key, generation):
                        self.status_manager.update_status(shop_id, user_id, username, ConnectionState.SUSPENDED, str(e))
                    logger.error(
                        f"连接失败，已达到最大重试次数: shop_id={shop_id}, user_id={user_id}, "
                        f"username={username}, connection_key={connection_key}, generation={generation}, "
                        f"reconnect_attempt={attempt + 1}, max_attempts={self.reconnect_config.max_attempts}, "
                        f"错误: {str(e)}"
                    )
                    if self._generation_is_current(connection_key, generation):
                        on_failure(f"连接失败，已达到最大重试次数: {e}")
                    if stop_event and self._generation_is_current(connection_key, generation):
                        stop_event.set()
                    return

                delay = min(
                    self.reconnect_config.initial_delay * (self.reconnect_config.backoff_factor ** attempt),
                    self.reconnect_config.max_delay,
                )

                logger.warning(
                    f"连接失败，{delay:.1f}秒后重试: shop_id={shop_id}, user_id={user_id}, "
                    f"username={username}, connection_key={connection_key}, generation={generation}, "
                    f"reconnect_attempt={attempt + 1}, timeout={delay:.1f}, 错误: {str(e)}"
                )

                try:
                    for _ in range(int(delay * 10)):
                        if not self._generation_is_current(connection_key, generation):
                            logger.info(
                                f"Stale reconnect delay skipped: connection_key={connection_key}, "
                                f"shop_id={shop_id}, user_id={user_id}, generation={generation}, "
                                f"reconnect_attempt={attempt + 1}"
                            )
                            return
                        if stop_event and stop_event.is_set():
                            logger.info(
                                f"重连延迟被停止信号中断: shop_id={shop_id}, user_id={user_id}, "
                                f"username={username}, connection_key={connection_key}, "
                                f"generation={generation}, reconnect_attempt={attempt + 1}"
                            )
                            if self._generation_is_current(connection_key, generation):
                                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                            return
                        try:
                            await asyncio.sleep(0.1)
                        except RuntimeError:
                            logger.info(
                                f"事件循环关闭，退出重连延迟: shop_id={shop_id}, user_id={user_id}, "
                                f"username={username}, connection_key={connection_key}, "
                                f"generation={generation}, reconnect_attempt={attempt + 1}"
                            )
                            return
                except (asyncio.CancelledError, RuntimeError):
                    logger.info(
                        f"重连延迟被中断或事件循环关闭: shop_id={shop_id}, user_id={user_id}, "
                        f"username={username}, connection_key={connection_key}, "
                        f"generation={generation}, reconnect_attempt={attempt + 1}"
                    )
                    if self._generation_is_current(connection_key, generation):
                        self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)
                    return

    async def _connect_single_attempt(
        self,
        shop_id: str,
        user_id: str,
        username: str,
        on_success: callable,
        on_failure: callable,
        generation: int = None,
    ):
        """单次 WebSocket 连接尝试"""
        logger = get_logger("PDDChannel")
        logger.info(
            f"WebSocket single attempt start: shop_id={shop_id}, user_id={user_id}, "
            f"username={username}, connection_key={shop_id}_{user_id}, generation={generation}, "
            f"loop_id={id(asyncio.get_running_loop())}"
        )
        await self.init(shop_id, user_id, username, on_success, on_failure, generation=generation)

    def _is_ws_closed(self, ws: Any) -> bool:
        """检查 WebSocket 是否已关闭"""
        try:
            closed = getattr(ws, "closed", None)
            if isinstance(closed, bool):
                return closed
            return False
        except Exception:
            return False

    async def _safe_close_websocket(self, ws: Any, timeout: float = 5.0):
        """安全关闭 WebSocket"""
        if not ws:
            return

        websocket_id = id(ws)
        try:
            close_fn = getattr(ws, "close", None)
            if close_fn:
                self.logger.info(
                    f"WebSocket close requested: websocket_id={websocket_id}, timeout={timeout}"
                )
                result = close_fn()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=timeout)
                self.logger.info(
                    f"WebSocket close completed: websocket_id={websocket_id}, timeout={timeout}"
                )
        except asyncio.TimeoutError:
            self.logger.warning(f"关闭 WebSocket 超时: close, websocket_id={websocket_id}, timeout={timeout}")
        except Exception as e:
            self.logger.debug(f"关闭 WebSocket 失败: websocket_id={websocket_id}, error={e}")

        try:
            wait_closed_fn = getattr(ws, "wait_closed", None)
            if wait_closed_fn:
                self.logger.info(
                    f"WebSocket wait_closed requested: websocket_id={websocket_id}, timeout={timeout}"
                )
                result = wait_closed_fn()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=timeout)
                self.logger.info(
                    f"WebSocket wait_closed completed: websocket_id={websocket_id}, timeout={timeout}"
                )
        except asyncio.TimeoutError:
            self.logger.warning(f"关闭 WebSocket 超时: wait_closed, websocket_id={websocket_id}, timeout={timeout}")
        except Exception as e:
            self.logger.debug(f"等待 WebSocket 关闭失败: websocket_id={websocket_id}, error={e}")


# 延迟导入避免循环依赖
from core.connection_status import ConnectionState
__all__ = ['ConnectionMixin']
