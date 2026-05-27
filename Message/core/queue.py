"""Async FIFO message queues with local SQLite recovery support."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Dict, Optional, Set

from bridge.context import Context
from utils.logger_loguru import get_logger

from ..models.queue_models import MessageWrapper, QueueConfig, QueueStats
from .reliable_queue import ReliableQueueStore, get_reliable_queue_store


logger = get_logger(__name__)


class SimpleMessageQueue:
    """Simple FIFO queue backed by a durable inbound recovery table."""

    def __init__(self, name: str, config: QueueConfig, reliable_store: ReliableQueueStore | None = None):
        self.name = name
        self.config = config
        self.logger = get_logger(f"Queue.{name}")
        self.reliable_store = reliable_store if reliable_store is not None else get_reliable_queue_store()
        self._queue = asyncio.Queue(maxsize=config.max_size)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._stats = QueueStats()
        self._closed = False
        self._deduplication_cache: Set[str] | None = set() if config.enable_deduplication else None
        self._last_cleanup_time = time.time()
        self._recovered_persisted = False

    async def put(self, context: Context) -> str:
        if self._closed:
            raise RuntimeError("Queue is closed")
        if self._queue.full():
            self._stats.total_enqueued += 1
            raise RuntimeError("Queue is full")

        reliable_record = self.reliable_store.enqueue_inbound(queue_name=self.name, context=context)
        wrapper = MessageWrapper(
            message_id="",
            context=context,
            timestamp=time.time(),
            reliable_record_id=reliable_record.record_id,
        )
        if self._should_deduplicate(wrapper):
            self.logger.debug(f"Message deduplicated: {wrapper.message_id}")
            return wrapper.message_id

        try:
            await self._queue.put(wrapper)
        except asyncio.QueueFull:
            raise RuntimeError("Queue is full")
        self._stats.enqueue()
        self.logger.debug(f"Message enqueued: {wrapper.message_id}")
        return wrapper.message_id

    async def get(self, timeout: Optional[float] = None) -> Optional[MessageWrapper]:
        await self._recover_persisted_once()
        if self._closed and self._queue.empty():
            return None
        try:
            wrapper = await asyncio.wait_for(self._queue.get(), timeout) if timeout else await self._queue.get()
        except asyncio.TimeoutError:
            return None
        self._stats.dequeue()
        if wrapper.reliable_record_id:
            self.reliable_store.mark_inbound_processing(wrapper.reliable_record_id)
        self.logger.debug(f"Message dequeued: {wrapper.message_id}")
        return wrapper

    def size(self) -> int:
        return self._queue.qsize()

    def is_empty(self) -> bool:
        return self._queue.empty()

    def get_stats(self) -> QueueStats:
        return QueueStats(
            total_enqueued=self._stats.total_enqueued,
            total_dequeued=self._stats.total_dequeued,
            current_size=self.size(),
            last_activity=self._stats.last_activity,
        )

    def is_bound_to_current_loop(self) -> bool:
        if self._loop is None:
            return True
        try:
            return self._loop is asyncio.get_running_loop()
        except RuntimeError:
            return True

    def close(self) -> None:
        self._closed = True
        self.logger.info(f"Queue {self.name} closed")

    async def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.logger.info(f"Queue {self.name} cleared")

    async def recover_persisted_now(self, *, limit: int = 100, processing_timeout_seconds: int = 300) -> int:
        try:
            recovered = self.reliable_store.recover_inbound(
                queue_name=self.name,
                limit=limit,
                processing_timeout_seconds=processing_timeout_seconds,
            )
        except Exception as exc:
            self.logger.warning(f"Reliable queue recovery failed: queue={self.name}, error={exc}")
            return 0
        for record in recovered:
            wrapper = MessageWrapper(
                message_id=record.record_id,
                context=record.context,
                timestamp=time.time(),
                reliable_record_id=record.record_id,
            )
            await self._queue.put(wrapper)
            self._stats.enqueue()
        if recovered:
            self.logger.info(f"Reliable queue recovered: queue={self.name}, count={len(recovered)}")
        return len(recovered)

    async def _recover_persisted_once(self) -> None:
        if self._recovered_persisted:
            return
        self._recovered_persisted = True
        await self.recover_persisted_now()

    def _should_deduplicate(self, wrapper: MessageWrapper) -> bool:
        if not self._deduplication_cache:
            return False
        content_text = "" if wrapper.context.content is None else str(wrapper.context.content)
        content_hash = hashlib.md5(content_text.encode("utf-8")).hexdigest()
        if content_hash in self._deduplication_cache:
            return True
        self._deduplication_cache.add(content_hash)
        self._cleanup_deduplication_cache()
        return False

    def _cleanup_deduplication_cache(self) -> None:
        if self._deduplication_cache is None:
            return
        current_time = time.time()
        if current_time - self._last_cleanup_time > self.config.deduplication_window:
            self._deduplication_cache.clear()
            self._last_cleanup_time = current_time
            return
        if len(self._deduplication_cache) > 10000:
            self._deduplication_cache.clear()
            self._last_cleanup_time = current_time
            self.logger.warning("Deduplication cache exceeded 10000 entries, cleared")


class QueueManager:
    """Manage named in-memory queues."""

    def __init__(self):
        self._queues: Dict[str, SimpleMessageQueue] = {}
        self.logger = get_logger("QueueManager")

    def get_or_create_queue(self, name: str, config: Optional[QueueConfig] = None) -> SimpleMessageQueue:
        queue = self._queues.get(name)
        if queue is not None and not queue.is_bound_to_current_loop():
            self.logger.warning(f"Queue {name} is bound to another event loop, recreating")
            return self.recreate_queue(name, config or queue.config)
        if name not in self._queues:
            self._queues[name] = SimpleMessageQueue(name, config or QueueConfig())
            self.logger.debug(f"Created queue: {name}")
        return self._queues[name]

    def get_queue(self, name: str) -> Optional[SimpleMessageQueue]:
        return self._queues.get(name)

    def recreate_queue(self, name: str, config: Optional[QueueConfig] = None) -> SimpleMessageQueue:
        old = self._queues.pop(name, None)
        if old:
            old.close()
        queue = SimpleMessageQueue(name, config or QueueConfig())
        self._queues[name] = queue
        self.logger.info(f"Recreated queue: {name}")
        return queue

    def list_queues(self) -> Dict[str, QueueStats]:
        return {name: queue.get_stats() for name, queue in self._queues.items()}

    async def close_all(self) -> None:
        for queue in self._queues.values():
            queue.close()
        self.logger.info("All queues closed")


queue_manager = QueueManager()
