"""Operational alerts for headless worker failures."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from utils.logger_loguru import get_logger

logger = get_logger("WorkerAlerts")

_LAST_PDD_WORKER_ALERT_AT: dict[tuple[str, str, str], datetime] = {}
_DEFAULT_THROTTLE_SECONDS = 600


def _error_type(error_msg: str) -> str:
    text = str(error_msg or "")
    if "no close frame" in text:
        return "websocket_no_close_frame"
    if "timed out" in text or "timeout" in text:
        return "websocket_timeout"
    if "Account not found" in text:
        return "account_not_found"
    return "connection_failed"


def _get_notification_service() -> Any | None:
    try:
        from core.di_container import container
        from core.notification import NotificationService

        return container.get(NotificationService)
    except Exception as exc:
        logger.warning(
            "event=pdd.worker.connection_alert.service_unavailable "
            f"error_type={type(exc).__name__}"
        )
        return None


def alert_pdd_worker_connection_failure(
    shop_id: str,
    user_id: str,
    error_msg: str,
    *,
    notification_service: Any | None = None,
    now: datetime | None = None,
    throttle_seconds: int = _DEFAULT_THROTTLE_SECONDS,
) -> dict[str, Any]:
    """Send a throttled PushPlus alert when a PDD worker stops after reconnect failure."""
    now = now or datetime.now()
    shop_id = str(shop_id or "")
    user_id = str(user_id or "")
    error_msg = str(error_msg or "")
    err_type = _error_type(error_msg)
    throttle_key = (shop_id, user_id, err_type)
    last_alert_at = _LAST_PDD_WORKER_ALERT_AT.get(throttle_key)

    if last_alert_at and now - last_alert_at < timedelta(seconds=throttle_seconds):
        logger.info(
            "event=pdd.worker.connection_alert.throttled "
            f"shop_id={shop_id} user_id={user_id} error_type={err_type}"
        )
        return {"alerted": False, "reason": "throttled", "error_type": err_type}

    service = notification_service or _get_notification_service()
    if service is None:
        return {"alerted": False, "reason": "notification_service_unavailable", "error_type": err_type}

    metadata = {
        "event": "pdd_worker_connection_failed",
        "shop_id": shop_id,
        "user_id": user_id,
        "worker": "internal_pdd_worker_runtime",
        "error_type": err_type,
        "error_message_short": error_msg[:300],
        "outbox_retry_loop": "stopped",
        "sends_pdd": False,
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
    }
    reason = f"PDD worker websocket disconnected: {err_type}"

    try:
        service.alert_human_fallback(
            shop_id=shop_id,
            user_id=user_id,
            reason=reason,
            alert_level="high",
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(
            "event=pdd.worker.connection_alert.failed "
            f"shop_id={shop_id} user_id={user_id} error_type={type(exc).__name__}"
        )
        return {"alerted": False, "reason": "notification_failed", "error_type": type(exc).__name__}

    _LAST_PDD_WORKER_ALERT_AT[throttle_key] = now
    logger.info(
        "event=pdd.worker.connection_alert.sent "
        f"shop_id={shop_id} user_id={user_id} error_type={err_type}"
    )
    return {"alerted": True, "reason": "sent", "error_type": err_type}


def send_pdd_worker_startup_test_alert(
    shop_id: str,
    user_id: str,
    *,
    pushplus_notifier: Any | None = None,
) -> dict[str, Any]:
    """Send a lightweight ClawBot startup test notification for the worker."""
    try:
        if pushplus_notifier is None:
            from core.pushplus_notifier import PushPlusNotifier

            pushplus_notifier = PushPlusNotifier()

        shop_id = str(shop_id or "")
        user_id = str(user_id or "")
        title = "Worker startup test"
        content = (
            "Customer agent worker startup test. "
            f"shop_id={shop_id} user_id={user_id}. "
            "ClawBot notification channel check only. "
            "No PDD message is sent."
        )
        result = pushplus_notifier.send(title, content)
        if getattr(result, "skipped", False):
            reason = getattr(result, "reason", "")
            logger.warning(
                "event=pdd.worker.startup_test_alert.skipped "
                f"shop_id={shop_id} user_id={user_id} reason={reason}"
            )
            return {"alerted": False, "reason": reason or "skipped"}
        if not getattr(result, "sent", False):
            reason = getattr(result, "reason", "")
            logger.warning(
                "event=pdd.worker.startup_test_alert.failed "
                f"shop_id={shop_id} user_id={user_id} reason={reason}"
            )
            return {"alerted": False, "reason": reason or "failed"}

        logger.info(
            "event=pdd.worker.startup_test_alert.sent "
            f"shop_id={shop_id} user_id={user_id}"
        )
        return {"alerted": True, "reason": "sent"}
    except Exception as exc:
        logger.warning(
            "event=pdd.worker.startup_test_alert.exception "
            f"shop_id={shop_id} user_id={user_id} error_type={type(exc).__name__}"
        )
        return {"alerted": False, "reason": "notification_failed", "error_type": type(exc).__name__}
