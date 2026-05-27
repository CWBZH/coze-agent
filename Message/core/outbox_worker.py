"""Controlled retry worker for PDD reply outbox records."""

from __future__ import annotations

import asyncio
import hashlib
import contextlib
from typing import Any, Callable

from utils.logger_loguru import get_logger

from .reliable_queue import ReliableQueueStore, get_reliable_queue_store


class OutboxWorker:
    """Retry due reply outbox records without changing websocket lifecycles."""

    def __init__(
        self,
        *,
        store: ReliableQueueStore | None = None,
        sender_factory: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.store = store if store is not None else get_reliable_queue_store()
        self.sender_factory = sender_factory
        self.logger = get_logger("OutboxWorker")

    async def run_due_retries(self, *, now: float | None = None, limit: int = 50) -> dict[str, int]:
        selected_now = self.store._now() if now is None else float(now)
        recovered_sending = 0
        recover_stale = getattr(self.store, "recover_stale_sending_outbox", None)
        if callable(recover_stale):
            recovered_sending = int(recover_stale(now=selected_now, timeout_seconds=60.0))
        claim = getattr(self.store, "claim_retryable_outbox", None)
        rows = claim(now=selected_now, limit=limit) if callable(claim) else self.store.recover_retryable_outbox(now=selected_now, limit=limit)
        summary = {
            "scanned": len(rows),
            "retried": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "suppressed": 0,
            "recovered_sending": recovered_sending,
        }
        if recovered_sending:
            self.logger.info(f"event=pdd.outbox.recovered_stale_sending count={recovered_sending}")
        for row in rows:
            outbox_id = str(row.get("id") or "")
            if not outbox_id:
                summary["skipped"] += 1
                continue
            reply_text = str(row.get("reply_text") or "")
            shop_id = str(row.get("shop_id") or "")
            user_id = str(row.get("user_id") or "")
            buyer_id = str(row.get("buyer_id") or "")
            if not (reply_text and shop_id and user_id and buyer_id):
                summary["skipped"] += 1
                continue
            suppress_status = self._suppression_status(row, selected_now)
            if suppress_status:
                summary["suppressed"] += 1
                self.store.mark_outbox_suppressed(
                    outbox_id,
                    suppress_status,
                    error_summary_hash=self._hash(suppress_status),
                )
                self.logger.warning(
                    "event=pdd.outbox.retry.suppressed "
                    f"outbox_id_hash={self._hash(outbox_id)} status={suppress_status} "
                    f"reply_hash={row.get('reply_hash') or ''}"
                )
                continue
            summary["retried"] += 1
            try:
                result = await asyncio.to_thread(self._send_text, shop_id, user_id, buyer_id, reply_text)
            except Exception as exc:
                summary["failed"] += 1
                self.store.mark_outbox_failed(outbox_id, error_summary_hash=type(exc).__name__)
                self.logger.warning(
                    "event=pdd.outbox.retry.failed "
                    f"outbox_id_hash={self._hash(outbox_id)} error_type={type(exc).__name__}"
                )
                continue

            if self._is_pdd_success(result):
                self.store.mark_outbox_sent(outbox_id)
                summary["sent"] += 1
                self.logger.info(
                    "event=pdd.outbox.retry.succeeded "
                    f"outbox_id_hash={self._hash(outbox_id)} reply_hash={row.get('reply_hash') or ''}"
                )
            else:
                summary["failed"] += 1
                error_code = self._pdd_error_code(result)
                if error_code == "40013" and int(row.get("retry_count") or 0) >= 1:
                    self.store.mark_outbox_suppressed(
                        outbox_id,
                        "blocked_by_platform_policy",
                        error_summary_hash=self._summary_hash(result),
                    )
                    self.logger.warning(
                        "event=pdd.outbox.retry.blocked_by_platform_policy "
                        f"outbox_id_hash={self._hash(outbox_id)} pdd_error_code=40013 "
                        f"retry_count={int(row.get('retry_count') or 0)}"
                    )
                else:
                    self.store.mark_outbox_failed(
                        outbox_id,
                        pdd_error_code=error_code,
                        error_summary_hash=self._summary_hash(result),
                    )
                self.logger.warning(
                    "event=pdd.outbox.retry.failed "
                    f"outbox_id_hash={self._hash(outbox_id)} pdd_error_code={error_code}"
                )
        return summary

    async def run_retry_loop(
        self,
        *,
        stop_event: asyncio.Event,
        interval_seconds: float = 10.0,
        limit: int = 20,
    ) -> None:
        """Continuously retry due outbox rows until ``stop_event`` is set."""

        interval = max(1.0, float(interval_seconds or 10.0))
        self.logger.info(
            "event=pdd.outbox.retry_loop.started "
            f"interval_seconds={interval:g} limit={max(1, int(limit))}"
        )
        try:
            while not stop_event.is_set():
                try:
                    summary = await self.run_due_retries(limit=limit)
                    if summary.get("retried"):
                        self.logger.info(
                            "event=pdd.outbox.retry_loop.tick "
                            f"retried={summary.get('retried', 0)} sent={summary.get('sent', 0)} "
                            f"failed={summary.get('failed', 0)} skipped={summary.get('skipped', 0)}"
                        )
                except Exception as exc:
                    self.logger.warning(f"event=pdd.outbox.retry_loop.error error_type={type(exc).__name__}")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
        finally:
            self.logger.info("event=pdd.outbox.retry_loop.stopped")

    def _send_text(self, shop_id: str, user_id: str, buyer_id: str, reply_text: str) -> Any:
        if self.sender_factory is None:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(shop_id, user_id)
        else:
            sender = self.sender_factory(shop_id, user_id)
        return sender.send_text(buyer_id, reply_text)

    def _suppression_status(self, row: dict[str, Any], now: float) -> str:
        stats_fn = getattr(self.store, "recent_reply_stats", None)
        if not callable(stats_fn):
            return ""
        stats = stats_fn(
            session_id=str(row.get("session_id") or ""),
            reply_hash=str(row.get("reply_hash") or ""),
            exclude_outbox_id=str(row.get("id") or ""),
            now=now,
            window_seconds=600.0,
        )
        if stats.get("sent_count", 0) > 0:
            return "suppressed_duplicate"
        if str(row.get("pdd_error_code") or "") == "40013" and stats.get("failed_40013_count", 0) >= 1:
            return "suppressed_repeated_40013"
        return ""

    @staticmethod
    def _is_pdd_success(result: Any) -> bool:
        if not isinstance(result, dict) or not result.get("success"):
            return False
        pdd_result = result.get("result")
        return isinstance(pdd_result, dict) and pdd_result.get("result") == "ok"

    @staticmethod
    def _pdd_error_code(result: Any) -> str:
        if not isinstance(result, dict):
            return ""
        pdd_result = result.get("result")
        if isinstance(pdd_result, dict) and pdd_result.get("error_code") is not None:
            return str(pdd_result.get("error_code"))
        if result.get("error_code") is not None:
            return str(result.get("error_code"))
        return ""

    @classmethod
    def _summary_hash(cls, result: Any) -> str:
        if isinstance(result, dict):
            pdd_result = result.get("result")
            if isinstance(pdd_result, dict):
                value = f"error_code:{pdd_result.get('error_code', '')}:error:{bool(pdd_result.get('error'))}"
            else:
                value = str(type(pdd_result).__name__)
        else:
            value = str(type(result).__name__)
        return cls._hash(value)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


async def trigger_reconnect_recovery(
    queue_name: str,
    *,
    queue_manager_obj: Any | None = None,
    outbox_worker: OutboxWorker | None = None,
) -> dict[str, int]:
    """Recover inbound queue and due outbox records after a websocket reconnect."""

    if queue_manager_obj is None:
        from .queue import queue_manager

        queue_manager_obj = queue_manager
    queue = queue_manager_obj.get_or_create_queue(queue_name)
    inbound_recovered = 0
    if hasattr(queue, "recover_persisted_now"):
        inbound_recovered = int(await queue.recover_persisted_now())
    worker = outbox_worker if outbox_worker is not None else OutboxWorker()
    outbox_summary = await worker.run_due_retries()
    return {
        "inbound_recovered": inbound_recovered,
        "outbox_retried": int(outbox_summary.get("retried", 0)),
    }
