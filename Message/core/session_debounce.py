"""Session-aware inbound text debounce for PDD buyer bursts."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from bridge.context import Context, ContextType
from utils.logger_loguru import get_logger


EnqueueCallable = Callable[[str, Context], Awaitable[str]]


def get_context_value(context: Context, name: str, default: Any = None) -> Any:
    kwargs = getattr(context, "kwargs", None)
    if kwargs is None:
        return default
    if isinstance(kwargs, dict):
        return kwargs.get(name, default)
    return getattr(kwargs, name, default)


def set_context_value(context: Context, name: str, value: Any) -> None:
    kwargs = getattr(context, "kwargs", None)
    if kwargs is None:
        return
    if isinstance(kwargs, dict):
        kwargs[name] = value
        return
    if hasattr(kwargs, name):
        setattr(kwargs, name, value)
        return
    # Pydantic models used by PDD kwargs reject unknown fields via setattr.
    try:
        kwargs.__dict__[name] = value
    except Exception:
        pass


def content_fingerprint(content: Any) -> tuple[int, str]:
    text = "" if content is None else str(content)
    return len(text), hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def session_key_from_context(context: Context, *, queue_name: str = "") -> str:
    shop_id = str(get_context_value(context, "shop_id", "") or "")
    user_id = str(get_context_value(context, "user_id", "") or "")
    buyer_id = str(get_context_value(context, "from_uid", "") or "")
    session_id = str(get_context_value(context, "session_id", "") or "")
    if not session_id:
        session_id = f"{shop_id}_{buyer_id}"
    return "|".join([queue_name or str(get_context_value(context, "queue_name", "") or ""), shop_id, user_id, buyer_id, session_id])


def session_key_from_metadata(metadata: Dict[str, Any], context: Optional[Context] = None, *, queue_name: str = "") -> str:
    if context is not None:
        return session_key_from_context(context, queue_name=queue_name or str(metadata.get("queue_name") or ""))
    shop_id = str(metadata.get("shop_id") or "")
    user_id = str(metadata.get("user_id") or "")
    buyer_id = str(metadata.get("from_uid") or metadata.get("customer_uid") or "")
    session_id = str(metadata.get("session_id") or f"{shop_id}_{buyer_id}")
    return "|".join([queue_name or str(metadata.get("queue_name") or ""), shop_id, user_id, buyer_id, session_id])


@dataclass
class _PendingBurst:
    queue_name: str
    key: str
    contexts: List[Context] = field(default_factory=list)
    first_seen: float = field(default_factory=time.monotonic)
    task: Optional[asyncio.Task] = None


class SessionMessageDebouncer:
    """Merge consecutive text messages from the same buyer session before queueing."""

    def __init__(self, *, window_seconds: float = 1.2, max_wait_seconds: float = 3.0, max_messages: int = 8):
        self.window_seconds = window_seconds
        self.max_wait_seconds = max_wait_seconds
        self.max_messages = max_messages
        self._pending: Dict[str, _PendingBurst] = {}
        self._lock = asyncio.Lock()
        self.logger = get_logger("SessionMessageDebouncer")

    async def submit(self, queue_name: str, context: Context, enqueue: EnqueueCallable) -> Optional[str]:
        if context.type != ContextType.TEXT:
            key = session_key_from_context(context, queue_name=queue_name)
            await self.flush_key(key, enqueue)
            return await enqueue(queue_name, context)

        key = session_key_from_context(context, queue_name=queue_name)
        async with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                pending = _PendingBurst(queue_name=queue_name, key=key)
                self._pending[key] = pending
            pending.contexts.append(context)
            if pending.task and not pending.task.done():
                pending.task.cancel()
            should_flush_now = (
                len(pending.contexts) >= self.max_messages
                or (time.monotonic() - pending.first_seen) >= self.max_wait_seconds
            )
            if should_flush_now:
                self._pending.pop(key, None)
            else:
                pending.task = asyncio.create_task(self._flush_later(key, enqueue))
                return None

        await self._flush_burst(pending, enqueue)
        return None

    async def flush_key(self, key: str, enqueue: EnqueueCallable) -> Optional[str]:
        async with self._lock:
            pending = self._pending.pop(key, None)
            if pending and pending.task and not pending.task.done():
                pending.task.cancel()
        if pending is None:
            return None
        return await self._flush_burst(pending, enqueue)

    async def flush_all(self, enqueue: EnqueueCallable) -> int:
        async with self._lock:
            pending_items = list(self._pending.values())
            self._pending.clear()
            for pending in pending_items:
                if pending.task and not pending.task.done():
                    pending.task.cancel()
        count = 0
        for pending in pending_items:
            await self._flush_burst(pending, enqueue)
            count += 1
        return count

    async def _flush_later(self, key: str, enqueue: EnqueueCallable) -> None:
        try:
            await asyncio.sleep(self.window_seconds)
            async with self._lock:
                pending = self._pending.pop(key, None)
            if pending is not None:
                await self._flush_burst(pending, enqueue)
        except asyncio.CancelledError:
            return

    async def _flush_burst(self, pending: _PendingBurst, enqueue: EnqueueCallable) -> str:
        if not pending.contexts:
            return ""
        context = pending.contexts[0]
        if len(pending.contexts) > 1:
            merged_parts = [str(item.content or "").strip() for item in pending.contexts if str(item.content or "").strip()]
            context.content = "\n".join(merged_parts)
            source_ids = [
                str(get_context_value(item, "source_message_id", "") or get_context_value(item, "msg_id", "") or "")
                for item in pending.contexts
            ]
            length, value_hash = content_fingerprint(context.content)
            set_context_value(context, "content_length", length)
            set_context_value(context, "content_hash", value_hash)
            set_context_value(context, "merged_from_burst", True)
            set_context_value(context, "burst_message_count", len(pending.contexts))
            set_context_value(context, "burst_source_message_ids", source_ids)
            set_context_value(context, "burst_window_ms", int(self.window_seconds * 1000))
            set_context_value(context, "burst_first_source_message_id", source_ids[0] if source_ids else "")
            set_context_value(context, "burst_last_source_message_id", source_ids[-1] if source_ids else "")
            self.logger.info(
                "event=pdd.message.burst_merged "
                f"queue_name={pending.queue_name} burst_message_count={len(pending.contexts)} "
                f"content_length={length} content_hash={value_hash}"
            )
        return await enqueue(pending.queue_name, context)


pdd_text_debouncer = SessionMessageDebouncer()
