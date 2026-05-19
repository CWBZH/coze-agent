"""
队列相关的数据模型
简化的消息包装器和统计信息
"""

import time
import uuid
import hashlib
from dataclasses import dataclass
from typing import Optional, Dict, Any
from bridge.context import Context


@dataclass
class MessageWrapper:
    """消息包装器 - 简化版"""
    message_id: str
    context: Context
    timestamp: float
    retry_count: int = 0
    trace_id: Optional[str] = None
    source_message_id: Optional[str] = None
    queue_name: Optional[str] = None
    shop_id: Optional[str] = None
    user_id: Optional[str] = None
    from_uid: Optional[str] = None
    to_uid: Optional[str] = None
    message_type: Optional[str] = None
    content_length: Optional[int] = None
    content_hash: Optional[str] = None

    def __post_init__(self):
        if not self.message_id:
            self.message_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = time.time()
        kwargs = getattr(self.context, "kwargs", None)
        self.trace_id = self.trace_id or self._get_kwarg(kwargs, "trace_id")
        self.source_message_id = self.source_message_id or self._get_kwarg(kwargs, "source_message_id") or self._get_kwarg(kwargs, "msg_id")
        self.queue_name = self.queue_name or self._get_kwarg(kwargs, "queue_name")
        self.shop_id = self.shop_id or self._get_kwarg(kwargs, "shop_id")
        self.user_id = self.user_id or self._get_kwarg(kwargs, "user_id")
        self.from_uid = self.from_uid or self._get_kwarg(kwargs, "from_uid")
        self.to_uid = self.to_uid or self._get_kwarg(kwargs, "to_uid")
        self.message_type = self.message_type or self._message_type(kwargs)
        if self.content_length is None:
            self.content_length = self._get_kwarg(kwargs, "content_length")
        if self.content_hash is None:
            self.content_hash = self._get_kwarg(kwargs, "content_hash")
        if self.content_length is None or self.content_hash is None:
            content_length, content_hash = self._content_fingerprint(self.context.content)
            if self.content_length is None:
                self.content_length = content_length
            if self.content_hash is None:
                self.content_hash = content_hash
        if not self.trace_id:
            source_id = self.source_message_id or self.message_id
            self.trace_id = f"pdd:{self.shop_id or 'unknown'}:{source_id}"

    def to_metadata(self) -> Dict[str, Any]:
        """转换为元数据字典"""
        return {
            'message_id': self.message_id,
            'queue_message_id': self.message_id,
            'trace_id': self.trace_id,
            'source_message_id': self.source_message_id,
            'shop_id': self.shop_id,
            'user_id': self.user_id,
            'from_uid': self.from_uid,
            'to_uid': self.to_uid,
            'queue_name': self.queue_name,
            'message_type': self.message_type,
            'content_length': self.content_length,
            'content_hash': self.content_hash,
            'timestamp': self.timestamp,
            'retry_count': self.retry_count
        }

    @staticmethod
    def _get_kwarg(kwargs: Any, name: str) -> Any:
        if kwargs is None:
            return None
        if isinstance(kwargs, dict):
            return kwargs.get(name)
        return getattr(kwargs, name, None)

    def _message_type(self, kwargs: Any) -> Optional[str]:
        value = self._get_kwarg(kwargs, "message_type") or self._get_kwarg(kwargs, "user_msg_type")
        if value is None and getattr(self.context, "type", None) is not None:
            value = self.context.type
        if hasattr(value, "value"):
            return str(value.value)
        return str(value) if value is not None else None

    @staticmethod
    def _content_fingerprint(content: Any) -> tuple[int, str]:
        content_text = "" if content is None else str(content)
        content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()[:12]
        return len(content_text), content_hash


@dataclass
class QueueStats:
    """队列统计信息 - 简化版"""
    total_enqueued: int = 0
    total_dequeued: int = 0
    current_size: int = 0
    last_activity: Optional[float] = None

    def enqueue(self):
        """记录入队操作"""
        self.total_enqueued += 1
        self.current_size += 1
        self.last_activity = time.time()

    def dequeue(self):
        """记录出队操作"""
        self.total_dequeued += 1
        if self.current_size > 0:
            self.current_size -= 1
        self.last_activity = time.time()


@dataclass
class QueueConfig:
    """队列配置 - 简化版"""
    max_size: int = 1000
    enable_deduplication: bool = True
    deduplication_window: int = 300  # 5分钟

    def __post_init__(self):
        if self.max_size <= 0:
            raise ValueError("max_size must be positive")
