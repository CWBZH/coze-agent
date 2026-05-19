import asyncio
import time
import websockets
from websockets import exceptions as ws_exceptions
from typing import Optional
from Channel.pinduoduo.utils.API.get_token import GetToken
from config import config


class LifecycleMixin:
    """PDD connection lifecycle helper."""

    def _get_lifecycle_lock(self, connection_key: str) -> asyncio.Lock:
        if not hasattr(self, "_lifecycle_locks"):
            self._lifecycle_locks = {}
        lock = self._lifecycle_locks.get(connection_key)
        if lock is None:
            lock = asyncio.Lock()
            self._lifecycle_locks[connection_key] = lock
        return lock

    def _next_generation(self, connection_key: str) -> int:
        if not hasattr(self, "_connection_generations"):
            self._connection_generations = {}
        generation = self._connection_generations.get(connection_key, 0) + 1
        self._connection_generations[connection_key] = generation
        return generation

    def _current_generation(self, connection_key: str) -> int:
        if not hasattr(self, "_connection_generations"):
            self._connection_generations = {}
        return self._connection_generations.get(connection_key, 0)

    def _is_current_generation(self, connection_key: str, generation: int = None) -> bool:
        return generation is None or self._current_generation(connection_key) == generation

    async def _cancel_reconnect_task(self, connection_key: str):
        old_task = self._reconnect_tasks.get(connection_key)
        if old_task is None:
            return

        old_task_id = id(old_task)
        if not old_task.done():
            self.logger.info(
                f"Reconnect task cancel requested: connection_key={connection_key}, "
                f"old_task_id={old_task_id}"
            )
            old_task.cancel()
            try:
                await asyncio.wait_for(old_task, timeout=5.0)
                self.logger.info(
                    f"Reconnect task cancel completed: connection_key={connection_key}, "
                    f"old_task_id={old_task_id}"
                )
            except asyncio.CancelledError:
                self.logger.info(
                    f"Reconnect task cancelled: connection_key={connection_key}, "
                    f"old_task_id={old_task_id}"
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Reconnect task cancel timeout: connection_key={connection_key}, "
                    f"old_task_id={old_task_id}"
                )
            except Exception as e:
                self.logger.warning(
                    f"Reconnect task cancel failed: connection_key={connection_key}, "
                    f"old_task_id={old_task_id}, error={e}"
                )
        else:
            self.logger.debug(
                f"Reconnect task already done: connection_key={connection_key}, "
                f"old_task_id={old_task_id}"
            )

        current = self._reconnect_tasks.get(connection_key)
        if current is old_task:
            self._reconnect_tasks.pop(connection_key, None)

    def _log_stale_skip(self, connection_key: str, generation: int, action: str):
        self.logger.info(
            f"Stale task skipped {action}: connection_key={connection_key}, "
            f"generation={generation}, current_generation={self._current_generation(connection_key)}"
        )

    async def start_account(self, shop_id: str, user_id: str, on_success: callable, on_failure: callable):
        """Start or replace one account connection."""
        account_info = db_manager.get_account(self.channel_name, shop_id, user_id)
        if not account_info:
            error_msg = f"Account not found: {user_id}"
            self.logger.error(error_msg)
            on_failure(error_msg)
            return

        username = account_info.get("username", user_id)
        connection_key = f"{shop_id}_{user_id}"
        lock = self._get_lifecycle_lock(connection_key)

        self.logger.info(f"Lifecycle lock waiting: connection_key={connection_key}")
        async with lock:
            self.logger.info(f"Lifecycle lock acquired: connection_key={connection_key}")
            try:
                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.CONNECTING)

                await self._cancel_reconnect_task(connection_key)

                generation = self._next_generation(connection_key)
                self.logger.info(
                    f"Connection generation advanced: connection_key={connection_key}, "
                    f"generation={generation}"
                )

                if hasattr(self, "_stop_events"):
                    self._stop_events[connection_key] = asyncio.Event()
                    self._stop_event = self._stop_events[connection_key]

                if self.reconnect_config.enable_auto_reconnect:
                    connect_task = asyncio.create_task(
                        self._connect_with_retry(
                            shop_id,
                            user_id,
                            username,
                            on_success,
                            on_failure,
                            generation=generation,
                        )
                    )
                else:
                    connect_task = asyncio.create_task(
                        self._connect_single_attempt(
                            shop_id,
                            user_id,
                            username,
                            on_success,
                            on_failure,
                            generation=generation,
                        )
                    )

                self._reconnect_tasks[connection_key] = connect_task
                self.logger.info(
                    f"Reconnect task created: connection_key={connection_key}, "
                    f"generation={generation}, new_task_id={id(connect_task)}"
                )
            finally:
                self.logger.info(f"Lifecycle lock released: connection_key={connection_key}")

    async def stop_account(self, shop_id: str, user_id: str):
        """Stop one account connection."""
        try:
            account_info = db_manager.get_account(self.channel_name, shop_id, user_id)
            if not account_info:
                self.logger.warning(f"Account not found: {user_id}")
                return

            username = account_info.get("username", user_id)
            connection_key = f"{shop_id}_{user_id}"

            self.logger.info(f"Stopping account: {shop_id} {username}")

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
                        self.logger.debug(f"Reconnect task cancelled: {connection_key}")
                    except asyncio.TimeoutError:
                        self.logger.warning(f"Reconnect task cancel timeout: {connection_key}")
                    except Exception as task_error:
                        self.logger.error(f"Reconnect task cancel error: {task_error}")
                del self._reconnect_tasks[connection_key]
                self.logger.debug(f"Reconnect task removed: {connection_key}")

            if connection_key in self._heartbeat_tasks:
                task = self._heartbeat_tasks[connection_key]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except asyncio.CancelledError:
                        self.logger.debug(f"Heartbeat task cancelled: {connection_key}")
                    except asyncio.TimeoutError:
                        self.logger.warning(f"Heartbeat task cancel timeout: {connection_key}")
                    except Exception as task_error:
                        self.logger.error(f"Heartbeat task cancel error: {task_error}")
                del self._heartbeat_tasks[connection_key]
                self.logger.debug(f"Heartbeat task removed: {connection_key}")

            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)

            if self.ws:
                await self._safe_close_websocket(self.ws)
                self.logger.info(f"Closed WebSocket: {shop_id} {username}")
            else:
                self.logger.warning(f"No active WebSocket: {shop_id} {username}")

            await self.cleanup_processing_tasks()

            queue_name = f"pdd_{shop_id}"
            await self._cleanup_resources(queue_name)
            if hasattr(self, "_stop_events"):
                self._stop_events.pop(connection_key, None)

            self.logger.info(f"Stopped account: {shop_id} {username}")

        except Exception as e:
            self.logger.error(f"Stop account failed: {shop_id} {user_id}: {str(e)}")

    async def init(
        self,
        shop_id: str,
        user_id: str,
        username: str,
        on_success: callable,
        on_failure: callable,
        generation: int = None,
    ):
        """Initialize one WebSocket connection attempt."""
        connection_key = f"{shop_id}_{user_id}"
        try:
            if not self._is_current_generation(connection_key, generation):
                self._log_stale_skip(connection_key, generation, "init")
                return

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

            if not self._is_current_generation(connection_key, generation):
                self._log_stale_skip(connection_key, generation, "post-token")
                return

            queue_name = f"pdd_{shop_id}"
            await self._setup_message_consumer(queue_name)

            if not self._is_current_generation(connection_key, generation):
                self._log_stale_skip(connection_key, generation, "post-consumer-setup")
                return

            params = {
                "access_token": access_token,
                "role": "mall_cs",
                "client": "web",
                "version": self.API_VERSION,
            }
            query = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{self.base_url}?{query}"

            self.logger.debug(
                f"WebSocket connecting: {shop_id}-{username}, "
                f"connection_key={connection_key}, generation={generation}"
            )

            async with websockets.connect(
                full_url,
                ping_interval=60,
                ping_timeout=30,
                max_size=10**7,
                compression=None,
                close_timeout=10,
            ) as websocket:
                if not self._is_current_generation(connection_key, generation):
                    self._log_stale_skip(connection_key, generation, "websocket-open")
                    return

                self.ws = websocket
                self.resource_manager.register_websocket(
                    websocket,
                    f"PDD WebSocket ({shop_id}-{username})",
                )
                self.logger.debug(f"WebSocket connected: {shop_id}-{username}")

                if self.ws and not self._is_ws_closed(self.ws):
                    self.logger.debug(f"WebSocket active: {shop_id}-{username}")
                else:
                    self.logger.error(f"WebSocket inactive: {shop_id}-{username}")

                if self._is_current_generation(connection_key, generation):
                    self.status_manager.update_status(shop_id, user_id, username, ConnectionState.CONNECTED)
                    self.logger.debug(f"Status connected: {shop_id}-{username}")
                    on_success()

                heartbeat_task = None
                if self.heartbeat_config.enable_heartbeat:
                    heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop(
                            websocket,
                            shop_id,
                            user_id,
                            username,
                            stop_event,
                            on_failure,
                            generation=generation,
                        )
                    )
                    self._heartbeat_tasks[connection_key] = heartbeat_task
                    self.logger.debug(f"Heartbeat started: {shop_id}-{username}")

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
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    should_cleanup = False
                    reconnect_exc = None
                    if stop_task in done:
                        self.logger.debug(f"Stop event received: {shop_id}-{username}")
                        should_cleanup = True
                    else:
                        if message_task in done:
                            reconnect_exc = message_task.exception()
                        if reconnect_exc:
                            self.logger.warning(
                                f"Connection interrupted: {shop_id}-{username}, "
                                f"error={reconnect_exc}"
                            )
                        else:
                            self.logger.warning(f"Connection task finished: {shop_id}-{username}")
                        should_cleanup = True

                    for task in pending:
                        task.cancel()
                        try:
                            await asyncio.wait_for(task, timeout=3.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                            pass
                        except Exception as e:
                            self.logger.debug(f"Pending task cancel error: {e}")

                    if should_cleanup:
                        if self._is_current_generation(connection_key, generation):
                            await self._cleanup_resources(f"pdd_{shop_id}", connection_key, generation)
                        else:
                            self._log_stale_skip(connection_key, generation, "cleanup")

                    if reconnect_exc:
                        raise reconnect_exc

                except asyncio.CancelledError:
                    self.logger.debug(f"WebSocket task cancelled: {shop_id}-{username}")
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
                    if self._is_current_generation(connection_key, generation):
                        await self._cleanup_resources(f"pdd_{shop_id}", connection_key, generation)
                    else:
                        self._log_stale_skip(connection_key, generation, "cancelled-cleanup")
                    raise

        except ws_exceptions.ConnectionClosedError as e:
            if self._is_current_generation(connection_key, generation):
                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
                on_failure(f"WebSocket: {e}")
            self.logger.error(f"WebSocket closed with error: {shop_id}-{username}, error={str(e)}")
            raise
        except ws_exceptions.ConnectionClosed as e:
            if self._is_current_generation(connection_key, generation):
                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
                on_failure(f"WebSocket: {e}")
            self.logger.warning(f"WebSocket closed: {shop_id}-{username}, code={e.code}")
            raise
        except Exception as e:
            if self._is_current_generation(connection_key, generation):
                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
                on_failure(f"WebSocket: {e}")
                await self._cleanup_resources(f"pdd_{shop_id}", connection_key, generation)
            else:
                self._log_stale_skip(connection_key, generation, "exception-cleanup")
            self.logger.error(f"WebSocket connection failed: {shop_id}-{username}, error={str(e)}")

    def request_stop(self):
        """Request all active connections to stop."""
        if hasattr(self, "_stop_events"):
            for stop_event in self._stop_events.values():
                stop_event.set()
        if self._stop_event:
            self._stop_event.set()

    async def stop_all_connections(self):
        """Stop all active connections."""
        try:
            self.logger.info("Stopping all PDD connections")

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
                        self.logger.debug(f"Reconnect task stopped: {connection_key}")
                    except Exception as e:
                        self.logger.error(f"Reconnect task stop error: {connection_key}, {e}")
                del self._reconnect_tasks[connection_key]

            for connection_key, task in list(self._heartbeat_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        self.logger.debug(f"Heartbeat task stopped: {connection_key}")
                    except Exception as e:
                        self.logger.error(f"Heartbeat task stop error: {connection_key}, {e}")
                del self._heartbeat_tasks[connection_key]

            if self.ws:
                await self._safe_close_websocket(self.ws)
                self.ws = None
            if hasattr(self, "_stop_events"):
                self._stop_events.clear()

            self.logger.info("All PDD connections stopped")

        except Exception as e:
            self.logger.error(f"Stop all connections failed: {e}")

    async def _heartbeat_loop(
        self,
        websocket,
        shop_id: str,
        user_id: str,
        username: str,
        stop_event: Optional[asyncio.Event] = None,
        on_failure: callable = None,
        generation: int = None,
    ):
        """Heartbeat loop."""
        connection_key = f"{shop_id}_{user_id}"
        consecutive_failures = 0
        current_task = asyncio.current_task()

        try:
            active_stop_event = stop_event or self._stop_event
            while not (active_stop_event and active_stop_event.is_set()):
                if not self._is_current_generation(connection_key, generation):
                    self._log_stale_skip(connection_key, generation, "heartbeat")
                    break
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
                    self.logger.warning(f"Heartbeat timeout: {shop_id}-{username}, failures={consecutive_failures}")
                    await asyncio.sleep(self.heartbeat_config.heartbeat_timeout)

                except Exception as e:
                    consecutive_failures += 1
                    self.logger.warning(
                        f"Heartbeat failed: {shop_id}-{username}, error={str(e)}, "
                        f"failures={consecutive_failures}"
                    )

                    if consecutive_failures >= self.heartbeat_config.max_heartbeat_failures:
                        self.logger.error(f"Heartbeat max failures reached: {shop_id}-{username}")
                        if self._is_current_generation(connection_key, generation):
                            self.status_manager.update_status(
                                shop_id,
                                user_id,
                                username,
                                ConnectionState.ERROR,
                                f"heartbeat failed {consecutive_failures} times",
                            )
                            if on_failure:
                                on_failure(f"max retries reached: heartbeat failed {consecutive_failures} times")
                        break

                    await asyncio.sleep(self.heartbeat_config.heartbeat_timeout)

        except asyncio.CancelledError:
            self.logger.debug(f"Heartbeat cancelled: {shop_id}-{username}")
        except Exception as e:
            self.logger.error(f"Heartbeat loop error: {shop_id}-{username}, error={str(e)}")
        finally:
            if self._heartbeat_tasks.get(connection_key) is current_task:
                del self._heartbeat_tasks[connection_key]
            elif not self._is_current_generation(connection_key, generation):
                self._log_stale_skip(connection_key, generation, "heartbeat-task-delete")
            self.logger.debug(f"Heartbeat exited: {shop_id}-{username}")

    async def _message_loop(self, websocket, shop_id: str, user_id: str, username: str, queue_name: str, stop_event: Optional[asyncio.Event] = None):
        """Message receive loop."""
        try:
            self.logger.info(f"Message loop started: {shop_id}-{username}")

            async for message in websocket:
                active_stop_event = stop_event or self._stop_event
                if active_stop_event and active_stop_event.is_set():
                    self.logger.info(f"Message loop stopped: {shop_id}-{username}")
                    break
                task = asyncio.create_task(
                    self._process_websocket_message_concurrent(
                        message, shop_id, user_id, username, queue_name
                    )
                )

                self.processing_tasks.add(task)
                task.add_done_callback(self.processing_tasks.discard)

        except ws_exceptions.ConnectionClosedError as cce:
            self.logger.error(f"WebSocket closed with error: {shop_id}-{username}, error={cce}")
            raise
        except ws_exceptions.ConnectionClosed as cc:
            self.logger.warning(f"WebSocket closed: {shop_id}-{username}, code={cc.code}")
            raise
        except Exception as e:
            self.logger.error(f"Message loop error: {shop_id}-{username}, error={str(e)}")
            raise

    async def _process_websocket_message_concurrent(self, message: str, shop_id: str, user_id: str, username: str, queue_name: str):
        """Process one websocket message under semaphore."""
        async with self.message_semaphore:
            try:
                await self._process_websocket_message(message, shop_id, user_id, username, queue_name)
            except Exception as e:
                self.logger.error(f"Process websocket message failed: {e}")

    async def cleanup_processing_tasks(self):
        """Cancel and clear processing tasks."""
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
                    self.logger.error(f"Processing task cleanup error: {e}")

        self.processing_tasks.clear()

    async def _cleanup_reconnect_tasks(self):
        """Cleanup reconnect tasks."""
        try:
            for connection_key, task in list(self._reconnect_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, RuntimeError):
                        pass
                    except asyncio.InvalidStateError:
                        self.logger.debug(f"Reconnect invalid state: {connection_key}")
                    except Exception as e:
                        self.logger.error(f"Reconnect cleanup error: {connection_key}, {e}")
            self._reconnect_tasks.clear()
        except RuntimeError:
            self._reconnect_tasks.clear()
        except Exception as e:
            self.logger.error(f"Reconnect cleanup failed: {e}")

    async def _cleanup_heartbeat_tasks(self):
        """Cleanup heartbeat tasks."""
        try:
            for connection_key, task in list(self._heartbeat_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, RuntimeError):
                        pass
                    except asyncio.InvalidStateError:
                        self.logger.debug(f"Heartbeat invalid state: {connection_key}")
                    except Exception as e:
                        self.logger.error(f"Heartbeat cleanup error: {connection_key}, {e}")
            self._heartbeat_tasks.clear()
        except RuntimeError:
            self._heartbeat_tasks.clear()
        except Exception as e:
            self.logger.error(f"Heartbeat cleanup failed: {e}")

    async def _cleanup_resources(self, queue_name: str, connection_key: str = None, generation: int = None):
        """Cleanup resources unless the caller is stale."""
        from Message import message_consumer_manager

        if connection_key is not None and not self._is_current_generation(connection_key, generation):
            self._log_stale_skip(connection_key, generation, "resource-cleanup")
            return

        try:
            await self.cleanup_processing_tasks()
            await self._cleanup_heartbeat_tasks()
            await self.resource_manager.cleanup_all()

            try:
                await message_consumer_manager.stop_consumer(queue_name)
                self.logger.debug(f"Consumer cleaned: {queue_name}")
            except (asyncio.InvalidStateError, RuntimeError):
                self.logger.debug(f"Consumer cleanup skipped: {queue_name}")
            except Exception as e:
                self.logger.warning(f"Consumer cleanup failed: {queue_name}, {e}")

            if connection_key is None or self._is_current_generation(connection_key, generation):
                self.ws = None
            else:
                self._log_stale_skip(connection_key, generation, "ws-clear")

        except RuntimeError:
            self.logger.debug(f"Resource cleanup runtime skipped: {queue_name}")
        except Exception as e:
            self.logger.error(f"Resource cleanup failed: {e}")


from database import db_manager
from core.connection_status import ConnectionState

__all__ = ['LifecycleMixin']
