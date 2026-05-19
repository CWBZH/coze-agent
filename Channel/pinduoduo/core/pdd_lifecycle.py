# 
import asyncio
import time
import websockets
from websockets import exceptions as ws_exceptions
from typing import Optional, Any
from utils.logger_loguru import get_logger
from Channel.pinduoduo.utils.API.get_token import GetToken
from config import config


class LifecycleMixin:
    """Lifecycle helper."""

    async def start_account(self, shop_id: str, user_id: str, on_success: callable, on_failure: callable):
        """Lifecycle helper."""
        account_info = db_manager.get_account(self.channel_name, shop_id, user_id)
        if not account_info:
            error_msg = f" {user_id} "
            self.logger.error(error_msg)
            on_failure(error_msg)
            return

        username = account_info.get("username", user_id)
        connection_key = f"{shop_id}_{user_id}"

        self.status_manager.update_status(shop_id, user_id, username, ConnectionState.CONNECTING)

        if connection_key in self._reconnect_tasks:
            self._reconnect_tasks[connection_key].cancel()
            del self._reconnect_tasks[connection_key]

        if hasattr(self, "_stop_events"):
            self._stop_events[connection_key] = asyncio.Event()
            self._stop_event = self._stop_events[connection_key]

        if self.reconnect_config.enable_auto_reconnect:
            connect_task = asyncio.create_task(
                self._connect_with_retry(shop_id, user_id, username, on_success, on_failure)
            )
        else:
            connect_task = asyncio.create_task(
                self._connect_single_attempt(shop_id, user_id, username, on_success, on_failure)
            )

        self._reconnect_tasks[connection_key] = connect_task

    async def stop_account(self, shop_id: str, user_id: str):
        """Lifecycle helper."""
        try:
            account_info = db_manager.get_account(self.channel_name, shop_id, user_id)
            if not account_info:
                self.logger.warning(f" {user_id} ")
                return

            username = account_info.get("username", user_id)
            connection_key = f"{shop_id}_{user_id}"

            self.logger.info(f" {shop_id}  {username}")

            stop_event = self._stop_events.get(connection_key) if hasattr(self, "_stop_events") else None
            if stop_event:
                stop_event.set()
            elif self._stop_event:
                self._stop_event.set()

            if connection_key in self._reconnect_tasks:
                task = self._reconnect_tasks[connection_key]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except asyncio.CancelledError:
                        self.logger.debug(f": {connection_key}")
                    except asyncio.TimeoutError:
                        self.logger.warning(f": {connection_key}")
                    except Exception as task_error:
                        self.logger.error(f"? {task_error}")
                del self._reconnect_tasks[connection_key]
                self.logger.debug(f"? {connection_key}")

            if connection_key in self._heartbeat_tasks:
                task = self._heartbeat_tasks[connection_key]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except asyncio.CancelledError:
                        self.logger.debug(f": {connection_key}")
                    except asyncio.TimeoutError:
                        self.logger.warning(f": {connection_key}")
                    except Exception as task_error:
                        self.logger.error(f"? {task_error}")
                del self._heartbeat_tasks[connection_key]
                self.logger.debug(f"? {connection_key}")

            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)

            if self.ws:
                await self._safe_close_websocket(self.ws)
                self.logger.info(f"?{shop_id}  {username} ebSocket")
            else:
                self.logger.warning(f" {shop_id}  {username} ebSocket")

            await self.cleanup_processing_tasks()

            queue_name = f"pdd_{shop_id}"
            await self._cleanup_resources(queue_name)
            if hasattr(self, "_stop_events"):
                self._stop_events.pop(connection_key, None)

            self.logger.info(f" {shop_id}  {username}")

        except Exception as e:
            self.logger.error(f" {shop_id}  {user_id} ? {str(e)}")

    async def init(self, shop_id: str, user_id: str, username: str, on_success: callable, on_failure: callable):
        """Lifecycle helper."""
        try:
            connection_key = f"{shop_id}_{user_id}"
            if hasattr(self, "_stop_events"):
                stop_event = self._stop_events.get(connection_key)
                if stop_event is None:
                    stop_event = asyncio.Event()
                    self._stop_events[connection_key] = stop_event
            else:
                stop_event = asyncio.Event()
            self._stop_event = stop_event

            token = GetToken(shop_id, user_id)
            access_token = await asyncio.to_thread(token.get_token)

            queue_name = f"pdd_{shop_id}"
            await self._setup_message_consumer(queue_name)

            params = {
                "access_token": access_token,
                "role": "mall_cs",
                "client": "web",
                "version": self.API_VERSION
            }
            query = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{self.base_url}?{query}"

            self.logger.debug(f"WebSocket: {shop_id}-{username}")

            async with websockets.connect(
                full_url,
                ping_interval=60,
                ping_timeout=30,
                max_size=10**7,
                compression=None,
                close_timeout=10
            ) as websocket:
                self.ws = websocket
                self.resource_manager.register_websocket(
                    websocket,
                    f"PDD WebSocket ({shop_id}-{username})"
                )
                self.logger.debug(f"WebSocket? {shop_id}-{username}")

                if self.ws and not self._is_ws_closed(self.ws):
                    self.logger.debug(f"WebSocket: {shop_id}-{username}")
                else:
                    self.logger.error(f"WebSocket: {shop_id}-{username}")

                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.CONNECTED)
                self.logger.debug(f"? {shop_id}-{username}")

                on_success()

                heartbeat_task = None
                if self.heartbeat_config.enable_heartbeat:
                    connection_key = f"{shop_id}_{user_id}"
                    heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop(websocket, shop_id, user_id, username, stop_event, on_failure)
                    )
                    self._heartbeat_tasks[connection_key] = heartbeat_task
                    self.logger.debug(f": {shop_id}-{username}")

                message_task = asyncio.create_task(
                    self._message_loop(websocket, shop_id, user_id, username, queue_name, stop_event)
                )

                stop_task = asyncio.create_task(stop_event.wait())

                try:
                    tasks = [message_task, stop_task]
                    if heartbeat_task:
                        tasks.append(heartbeat_task)

                    done, pending = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    should_cleanup = False
                    reconnect_exc = None
                    if stop_task in done:
                        self.logger.debug(f": {shop_id}-{username}")
                        should_cleanup = True
                    else:
                        if message_task in done:
                            reconnect_exc = message_task.exception()
                        if reconnect_exc:
                            self.logger.warning(
                                f"? {shop_id}-{username}, "
                                f": {reconnect_exc}"
                            )
                        else:
                            self.logger.warning(f": {shop_id}-{username}")
                        should_cleanup = True

                    for task in pending:
                        task.cancel()
                        try:
                            await asyncio.wait_for(task, timeout=3.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                            pass
                        except Exception as e:
                            self.logger.debug(f"? {e}")

                    if should_cleanup:
                        await self._cleanup_resources(f"pdd_{shop_id}")

                    if reconnect_exc:
                        raise reconnect_exc

                except asyncio.CancelledError:
                    self.logger.debug(f"WebSocket? {shop_id}-{username}")
                    message_task.cancel()
                    if heartbeat_task:
                        heartbeat_task.cancel()
                    try:
                        await asyncio.wait_for(message_task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                        pass
                    if heartbeat_task:
                        try:
                            await asyncio.wait_for(heartbeat_task, timeout=3.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                            pass
                    await self._cleanup_resources(f"pdd_{shop_id}")

        except ws_exceptions.ConnectionClosedError as e:
            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
            self.logger.error(f"WebSocket: {shop_id}-{username}, : {str(e)}")
            on_failure(f"WebSocket: {e}")
            raise
        except ws_exceptions.ConnectionClosed as e:
            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
            self.logger.warning(f"WebSocket: {shop_id}-{username}, : {e.code}")
            on_failure(f"WebSocket: {e}")
            raise
        except Exception as e:
            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
            self.logger.error(f"WebSocket: {shop_id}-{username}, : {str(e)}")
            on_failure(f"WebSocket: {e}")
            await self._cleanup_resources(f"pdd_{shop_id}")

    def request_stop(self):
        """Lifecycle helper."""
        if hasattr(self, "_stop_events"):
            for stop_event in self._stop_events.values():
                stop_event.set()
        if self._stop_event:
            self._stop_event.set()

    async def stop_all_connections(self):
        """Lifecycle helper."""
        try:
            self.logger.info("?..")

            if self._stop_event:
                self._stop_event.set()
            if hasattr(self, "_stop_events"):
                for stop_event in self._stop_events.values():
                    stop_event.set()

            for connection_key, task in list(self._reconnect_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        self.logger.debug(f": {connection_key}")
                    except Exception as e:
                        self.logger.error(f"? {connection_key}, {e}")
                del self._reconnect_tasks[connection_key]

            for connection_key, task in list(self._heartbeat_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        self.logger.debug(f": {connection_key}")
                    except Exception as e:
                        self.logger.error(f"? {connection_key}, {e}")
                del self._heartbeat_tasks[connection_key]

            if self.ws:
                await self._safe_close_websocket(self.ws)
                self.ws = None
            if hasattr(self, "_stop_events"):
                self._stop_events.clear()

            self.logger.info("")

        except Exception as e:
            self.logger.error(f": {e}")

    async def _heartbeat_loop(self, websocket, shop_id: str, user_id: str, username: str, stop_event: Optional[asyncio.Event] = None, on_failure: callable = None):
        """Lifecycle helper."""
        connection_key = f"{shop_id}_{user_id}"
        consecutive_failures = 0

        try:
            active_stop_event = stop_event or self._stop_event
            while not (active_stop_event and active_stop_event.is_set()):
                try:
                    start_time = time.time()
                    await websocket.ping()
                    response_time = time.time() - start_time

                    consecutive_failures = 0

                    status = self.status_manager.get_status(shop_id, user_id)
                    if status and status.state == ConnectionState.CONNECTED:
                        pass

                    await asyncio.sleep(self.heartbeat_config.heartbeat_interval)

                except asyncio.TimeoutError:
                    consecutive_failures += 1
                    self.logger.warning(f": {shop_id}-{username}, : {consecutive_failures}")
                    await asyncio.sleep(self.heartbeat_config.heartbeat_timeout)

                except Exception as e:
                    consecutive_failures += 1
                    self.logger.warning(f": {shop_id}-{username}, : {str(e)}, : {consecutive_failures}")

                    if consecutive_failures >= self.heartbeat_config.max_heartbeat_failures:
                        self.logger.error(f"? {shop_id}-{username}")
                        self.status_manager.update_status(
                            shop_id, user_id, username,
                            ConnectionState.ERROR,
                            f"heartbeat failed {consecutive_failures} times"
                        )
                        if on_failure:
                            on_failure(f"max retries reached: heartbeat failed {consecutive_failures} times")
                        break

                    await asyncio.sleep(self.heartbeat_config.heartbeat_timeout)

        except asyncio.CancelledError:
            self.logger.debug(f"? {shop_id}-{username}")
        except Exception as e:
            self.logger.error(f": {shop_id}-{username}, : {str(e)}")
        finally:
            if connection_key in self._heartbeat_tasks:
                del self._heartbeat_tasks[connection_key]
            self.logger.debug(f"? {shop_id}-{username}")

    async def _message_loop(self, websocket, shop_id: str, user_id: str, username: str, queue_name: str, stop_event: Optional[asyncio.Event] = None):
        """Lifecycle helper."""
        try:
            self.logger.info(f"Message loop started: {shop_id}-{username}")

            async for message in websocket:
                active_stop_event = stop_event or self._stop_event
                if active_stop_event and active_stop_event.is_set():
                    self.logger.info(f"? {shop_id}-{username}")
                    break
                task = asyncio.create_task(
                    self._process_websocket_message_concurrent(
                        message, shop_id, user_id, username, queue_name
                    )
                )

                self.processing_tasks.add(task)
                task.add_done_callback(self.processing_tasks.discard)

        except ws_exceptions.ConnectionClosedError as cce:
            self.logger.error(f"WebSocket: {shop_id}-{username}, : {cce}")
            raise
        except ws_exceptions.ConnectionClosed as cc:
            self.logger.warning(f"WebSocket: {shop_id}-{username}, : {cc.code}")
            raise
        except Exception as e:
            self.logger.error(f": {shop_id}-{username}, : {str(e)}")
            raise

    async def _process_websocket_message_concurrent(self, message: str, shop_id: str, user_id: str, username: str, queue_name: str):
        """Lifecycle helper."""
        async with self.message_semaphore:
            try:
                await self._process_websocket_message(message, shop_id, user_id, username, queue_name)
            except Exception as e:
                self.logger.error(f": {e}")

    async def cleanup_processing_tasks(self):
        """Lifecycle helper."""
        if not self.processing_tasks:
            return

        self.logger.info(f"Cleaning {len(self.processing_tasks)} processing tasks")
        for task in self.processing_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self.logger.error(f": {e}")

        self.processing_tasks.clear()

    async def _cleanup_reconnect_tasks(self):
        """Lifecycle helper."""
        try:
            for connection_key, task in list(self._reconnect_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, RuntimeError):
                        pass
                    except asyncio.InvalidStateError:
                        self.logger.debug(f": {connection_key}")
                    except Exception as e:
                        self.logger.error(f": {connection_key}, {e}")
            self._reconnect_tasks.clear()
        except RuntimeError:
            self._reconnect_tasks.clear()
        except Exception as e:
            self.logger.error(f": {e}")

    async def _cleanup_heartbeat_tasks(self):
        """Lifecycle helper."""
        try:
            for connection_key, task in list(self._heartbeat_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, RuntimeError):
                        pass
                    except asyncio.InvalidStateError:
                        self.logger.debug(f": {connection_key}")
                    except Exception as e:
                        self.logger.error(f": {connection_key}, {e}")
            self._heartbeat_tasks.clear()
        except RuntimeError:
            self._heartbeat_tasks.clear()
        except Exception as e:
            self.logger.error(f": {e}")

    async def _cleanup_resources(self, queue_name: str):
        """Lifecycle helper."""
        from Message import message_consumer_manager

        try:
            await self.cleanup_processing_tasks()
            await self._cleanup_heartbeat_tasks()
            await self.resource_manager.cleanup_all()

            try:
                await message_consumer_manager.stop_consumer(queue_name)
                self.logger.debug(f"? {queue_name}")
            except (asyncio.InvalidStateError, RuntimeError):
                self.logger.debug(f": {queue_name}")
            except Exception as e:
                self.logger.warning(f"? {queue_name}, {e}")

            self.ws = None

        except RuntimeError:
            self.logger.debug(f": {queue_name}")
        except Exception as e:
            self.logger.error(f": {e}")


# 
from database import db_manager
from core.connection_status import ConnectionState

__all__ = ['LifecycleMixin']


