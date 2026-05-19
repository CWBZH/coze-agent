import time
from typing import Dict, Optional

from core.config import AUTO_REPLY_RECONNECT_SUSPEND_TTL
from utils.logger_loguru import get_logger
from .threads import AutoReplyThread


class AutoReplyManager:
    """Manage auto-reply worker threads per account."""

    def __init__(self, notification_service=None):
        self.running_accounts: Dict[str, AutoReplyThread] = {}
        self._last_start_at: Dict[str, float] = {}
        self._last_stop_at: Dict[str, float] = {}
        self._suspended_until: Dict[str, float] = {}
        self._suspended_reason: Dict[str, str] = {}
        self._start_cooldown_seconds = 8.0
        self._notification_service = notification_service
        self.logger = get_logger("AutoReplyManager")

    def _account_key(self, account_data: dict) -> str:
        return f"{account_data['channel_name']}_{account_data['shop_id']}_{account_data['username']}"

    def start_auto_reply(self, account_data: dict) -> bool:
        """Start auto-reply for one account with duplicate-start debounce."""
        try:
            account_key = self._account_key(account_data)
            now = time.monotonic()

            suspended_until = self._suspended_until.get(account_key, 0)
            if now < suspended_until:
                remaining = int(suspended_until - now)
                reason = self._suspended_reason.get(account_key, "connection failed repeatedly")
                self.logger.warning(
                    f"Account {account_key} is suspended for {remaining}s, reason: {reason}"
                )
                return False
            self._suspended_until.pop(account_key, None)
            self._suspended_reason.pop(account_key, None)

            if now - self._last_start_at.get(account_key, 0) < self._start_cooldown_seconds:
                self.logger.warning(f"Account {account_key} start ignored by debounce")
                return True

            if now - self._last_stop_at.get(account_key, 0) < self._start_cooldown_seconds:
                self.logger.warning(f"Account {account_key} was just stopped, wait before restart")
                return False

            thread = self.running_accounts.get(account_key)
            if thread:
                if thread.isRunning():
                    self.logger.warning(f"Account {account_key} is already running or reconnecting")
                    return True
                self._cleanup_stale_thread(account_key)

            thread = AutoReplyThread(account_data)
            self.running_accounts[account_key] = thread

            thread.connection_success.connect(lambda: self._on_connection_success(account_key))
            thread.connection_failed.connect(lambda error: self._on_connection_failed(account_key, error))
            thread.finished.connect(lambda: self._on_thread_finished(account_key))

            self.logger.info(
                f"Starting auto-reply account {account_data['username']} (shop: {account_data['shop_id']})"
            )
            self._last_start_at[account_key] = now
            thread.start()
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to start auto-reply account {account_data.get('username')} "
                f"(shop: {account_data.get('shop_id')}): {e}"
            )
            return False

    def stop_auto_reply(self, account_data: dict) -> bool:
        """Stop auto-reply for one account."""
        try:
            account_key = self._account_key(account_data)
            thread = self.running_accounts.get(account_key)
            if not thread:
                self.logger.warning(
                    f"Auto-reply account {account_data['username']} "
                    f"(shop: {account_data['shop_id']}) is not running"
                )
                return False

            thread.stop()
            if thread.isRunning():
                thread.wait(5000)

            self.running_accounts.pop(account_key, None)
            self._last_stop_at[account_key] = time.monotonic()

            self.logger.info(
                f"Stopped auto-reply account {account_data['username']} "
                f"(shop: {account_data['shop_id']})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to stop auto-reply account {account_data.get('username')} "
                f"(shop: {account_data.get('shop_id')}): {e}"
            )
            return False

    def is_running(self, account_data: dict) -> bool:
        """Check whether one account still has an active worker thread."""
        try:
            account_key = self._account_key(account_data)
            thread = self.running_accounts.get(account_key)
            if not thread or not hasattr(thread, "isRunning"):
                self._cleanup_stale_thread(account_key)
                return False

            if not thread.isRunning():
                self._cleanup_stale_thread(account_key)
                return False

            return True

        except Exception as e:
            self.logger.error(f"Failed to check account running state: {e}")
            return False

    def _cleanup_stale_thread(self, account_key: str):
        """Remove stopped worker references."""
        try:
            thread = self.running_accounts.get(account_key)
            if thread and hasattr(thread, "isRunning") and not thread.isRunning():
                self.running_accounts.pop(account_key, None)
                self._last_stop_at[account_key] = time.monotonic()
                self.logger.debug(f"Cleaned stale thread reference: {account_key}")
        except Exception as e:
            self.logger.error(f"Failed to clean stale thread reference: {account_key}, {e}")

    def _on_connection_success(self, account_key: str):
        self.logger.debug(f"Auto-reply account connected: {account_key}")

    def _on_connection_failed(self, account_key: str, error: str):
        """A single websocket attempt may fail while the thread is still reconnecting."""
        self.logger.error(f"Auto-reply account connection failed: {account_key}, {error}")
        thread = self.running_accounts.get(account_key)
        final_failure = self._is_final_connection_failure(str(error))
        if thread and thread.isRunning() and not final_failure:
            self.logger.warning(f"Account {account_key} is still reconnecting")
            return

        if final_failure:
            self._suspend_account(account_key, str(error))
            self._alert_connection_failed(account_key, str(error))
            if thread and thread.isRunning():
                thread.stop()

        self.running_accounts.pop(account_key, None)
        self._last_stop_at[account_key] = time.monotonic()

    def _is_final_connection_failure(self, error: str) -> bool:
        lower_error = error.lower()
        return (
            ("已达到最大重试次数" in error)
            or ("宸茶揪鍒版渶澶ч噸璇曟" in error)
            or ("max retry" in lower_error)
            or ("max retries" in lower_error)
        )

    def _get_notification_service(self):
        if self._notification_service is not None:
            return self._notification_service
        try:
            from core.di_container import container
            from core.notification import NotificationService

            return container.get(NotificationService)
        except Exception as e:
            self.logger.warning(f"Failed to get human-transfer notification service: {e}")
            return None

    def _alert_connection_failed(self, account_key: str, error: str):
        shop_id, username = self._parse_account_key(account_key)
        if not shop_id or not username:
            self.logger.warning(f"Invalid account key, cannot send connection failure alert: {account_key}")
            return

        service = self._get_notification_service()
        if not service:
            return

        service.alert_human_fallback(
            shop_id=shop_id,
            user_id=username,
            reason=f"自动回复连接失败: {error}",
            alert_level="high",
        )

    def _parse_account_key(self, account_key: str) -> tuple[Optional[str], Optional[str]]:
        parts = account_key.split("_", 2)
        if len(parts) != 3:
            return None, None
        _, shop_id, username = parts
        return shop_id, username

    def _suspend_account(self, account_key: str, reason: str):
        suspended_until = time.monotonic() + AUTO_REPLY_RECONNECT_SUSPEND_TTL
        self._suspended_until[account_key] = suspended_until
        self._suspended_reason[account_key] = reason
        self.logger.error(
            f"Auto-reply account suspended for {AUTO_REPLY_RECONNECT_SUSPEND_TTL}s: "
            f"{account_key}, reason: {reason}"
        )

    def _on_thread_finished(self, account_key: str):
        self.logger.debug(f"Auto-reply account thread finished: {account_key}")
        self.running_accounts.pop(account_key, None)
        self._last_stop_at[account_key] = time.monotonic()

    def get_running_count(self) -> int:
        return len(self.running_accounts)

    def stop_all(self):
        try:
            for thread in list(self.running_accounts.values()):
                if thread.is_running():
                    thread.stop()

            for thread in list(self.running_accounts.values()):
                thread.wait(5000)

            now = time.monotonic()
            for account_key in list(self.running_accounts.keys()):
                self._last_stop_at[account_key] = now
            self.running_accounts.clear()
            self.logger.info("All auto-reply tasks stopped")

        except Exception as e:
            self.logger.error(f"Failed to stop all auto-reply tasks: {e}")


auto_reply_manager = AutoReplyManager()


__all__ = ["AutoReplyManager", "auto_reply_manager"]
