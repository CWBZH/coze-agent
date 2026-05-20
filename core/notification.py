"""Notification service abstractions for UI and headless runtimes."""
from __future__ import annotations

from typing import Any, Optional
import hashlib

from core.human_alert_context import HumanAlertContextBuilder, format_human_alert_message
from core.pushplus_notifier import PushPlusNotifier
from utils.logger_loguru import get_logger

logger = get_logger("NotificationService")


class NotificationService:
    """Abstract notification service used by backend business logic."""

    def alert_human_fallback(
        self,
        shop_id: str,
        user_id: str,
        reason: str,
        alert_level: str = "low",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trigger manual-transfer notification."""
        raise NotImplementedError


class DummyNotificationService(NotificationService):
    """No-op notification service for headless mode without PushPlus config."""

    def alert_human_fallback(
        self,
        shop_id: str,
        user_id: str,
        reason: str,
        alert_level: str = "low",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        trace_id = ""
        if metadata:
            trace_id = str(metadata.get("trace_id") or "")
        logger.warning(
            "event=manual_transfer.notification.dummy "
            f"shop_id={shop_id} user_id={user_id} alert_level={alert_level} trace_id={trace_id}"
        )


class HeadlessNotificationService(NotificationService):
    """Headless PushPlus notification service for Linux/systemd workers."""

    def __init__(
        self,
        pushplus_notifier: PushPlusNotifier | None = None,
        context_builder: HumanAlertContextBuilder | None = None,
    ):
        self._pushplus_notifier = pushplus_notifier or PushPlusNotifier()
        if context_builder is None:
            from database.db_manager import db_manager

            context_builder = HumanAlertContextBuilder(db_manager)
        self._context_builder = context_builder

    @staticmethod
    def _content_hash(value: object) -> str:
        text = "" if value is None else str(value)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def alert_human_fallback(
        self,
        shop_id: str,
        user_id: str,
        reason: str,
        alert_level: str = "low",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        metadata = dict(metadata or {})
        trace_id = str(metadata.get("trace_id") or "")
        try:
            alert_context = self._context_builder.build(shop_id, user_id)
            content = format_human_alert_message(
                alert_context,
                reason=reason,
                alert_level=alert_level,
                metadata=metadata,
            )
            title = "Customer agent transfer alert"
            if alert_level == "high":
                title = "High-risk customer agent transfer alert"

            result = self._pushplus_notifier.send(title, content)
            content_length = len(content)
            content_hash = self._content_hash(content)
            if getattr(result, "skipped", False):
                logger.warning(
                    "event=pushplus.notification.skipped "
                    f"trace_id={trace_id} reason={getattr(result, 'reason', '')} "
                    f"content_length={content_length} content_hash={content_hash}"
                )
            elif not getattr(result, "sent", False):
                logger.warning(
                    "event=pushplus.notification.failed "
                    f"trace_id={trace_id} reason={getattr(result, 'reason', '')} "
                    f"content_length={content_length} content_hash={content_hash}"
                )
            else:
                logger.info(
                    "event=pushplus.notification.sent "
                    f"trace_id={trace_id} content_length={content_length} content_hash={content_hash}"
                )
        except Exception as e:
            logger.warning(
                "event=pushplus.notification.failed "
                f"trace_id={trace_id} error_type={type(e).__name__}"
            )
