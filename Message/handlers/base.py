"""
处理器基类和通用工具
"""
import hashlib
import json
from typing import Dict, Any, Optional
from utils.logger_loguru import get_logger
from bridge.context import Context
from ..core.handlers import MessageHandler



class BaseHandler(MessageHandler):
    """处理器基类，提供通用功能"""

    def __init__(self, name: Optional[str] = None):
        super().__init__()
        self.name = name or self.__class__.__name__

    async def log_message(self, context: Context, action: str, extra_info: str = ""):
        """统一的日志记录（不记录完整内容以保护隐私）"""
        user_info = self._get_user_info(context)
        content_length, content_hash = self._fingerprint(context.content)
        safe_extra = ""
        if extra_info:
            extra_length, extra_hash = self._fingerprint(extra_info)
            safe_extra = f" extra_length={extra_length} extra_hash={extra_hash}"
        self.logger.info(
            f"{self.name} {action} - {user_info} - "
            f"content_length={content_length} content_hash={content_hash}{safe_extra}"
        )

    @staticmethod
    def _fingerprint(value: Any) -> tuple[int, str]:
        if value is None:
            return 0, ""
        text = value if isinstance(value, str) else str(value)
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return len(text), digest

    def _get_user_info(self, context: Context) -> str:
        """提取用户信息"""
        try:
            if hasattr(context, 'kwargs') and context.kwargs:
                from_uid = getattr(context.kwargs, 'from_uid', None)
                username = getattr(context.kwargs, 'username', None)
                if username:
                    return f"用户:{username}({from_uid})"
                elif from_uid:
                    return f"用户:{from_uid}"
            return "用户:unknown"
        except Exception:
            return "用户:unknown"
