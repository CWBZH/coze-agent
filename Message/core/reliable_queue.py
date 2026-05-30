"""SQLite-backed recovery queues for PDD inbound messages and reply outbox."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bridge.context import ChannelType, Context, ContextType
from core import settings


@dataclass(frozen=True)
class InboundRecord:
    record_id: str
    created: bool
    queue_name: str
    source_message_id: str
    context: Context
    status: str = "pending"


@dataclass(frozen=True)
class OutboxRecord:
    outbox_id: str
    created: bool
    status: str


class ReliableQueueStore:
    """Small local SQLite store for queue recovery.

    This is intentionally independent from SQLAlchemy models so it can be used
    by the websocket/consumer path without changing worker lifecycles.
    """

    def __init__(self, db_path: str | Path | None = None):
        selected = settings.resolve_path(db_path) if db_path else settings.db_path()
        self.db_path = Path(selected)
        settings.ensure_dir(self.db_path.parent)
        self._ensure_schema()

    def enqueue_inbound(self, *, queue_name: str, context: Context) -> InboundRecord:
        payload = self._context_to_payload(context)
        source_message_id = str(payload.get("source_message_id") or payload.get("msg_id") or "")
        if not source_message_id:
            source_message_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        dedupe_key = self._inbound_dedupe_key(queue_name, payload, source_message_id)
        now = self._now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, status, payload_json FROM pdd_inbound_message_queue WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if existing:
                return InboundRecord(
                    record_id=str(existing["id"]),
                    created=False,
                    queue_name=queue_name,
                    source_message_id=source_message_id,
                    context=self._payload_to_context(json.loads(existing["payload_json"])),
                    status=str(existing["status"]),
                )
            record_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO pdd_inbound_message_queue
                    (id, dedupe_key, queue_name, source_message_id, trace_id, shop_id, user_id,
                     buyer_id, session_id, message_type, payload_json, status, retry_count,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (
                    record_id,
                    dedupe_key,
                    queue_name,
                    source_message_id,
                    str(payload.get("trace_id") or ""),
                    str(payload.get("shop_id") or ""),
                    str(payload.get("user_id") or ""),
                    str(payload.get("from_uid") or ""),
                    str(payload.get("session_id") or ""),
                    str(payload.get("message_type") or ""),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            return InboundRecord(record_id, True, queue_name, source_message_id, context, "pending")

    def recover_inbound(
        self,
        *,
        queue_name: str,
        limit: int = 100,
        processing_timeout_seconds: int = 300,
    ) -> list[InboundRecord]:
        cutoff = self._now() - max(0, int(processing_timeout_seconds))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM pdd_inbound_message_queue
                WHERE queue_name = ?
                  AND (
                    status = 'pending'
                    OR (status = 'processing' AND updated_at <= ?)
                  )
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (queue_name, cutoff, max(1, int(limit))),
            ).fetchall()
        return [
            InboundRecord(
                record_id=str(row["id"]),
                created=False,
                queue_name=str(row["queue_name"]),
                source_message_id=str(row["source_message_id"] or ""),
                context=self._payload_to_context(json.loads(row["payload_json"])),
                status=str(row["status"]),
            )
            for row in rows
        ]

    def mark_inbound_processing(self, record_id: str) -> None:
        self._update_inbound_status(record_id, "processing", increment_retry=True)

    def mark_inbound_done(self, record_id: str) -> None:
        self._update_inbound_status(record_id, "done")

    def mark_inbound_failed(self, record_id: str, error_type: str = "") -> None:
        self._update_inbound_status(record_id, "failed", error_type=error_type)

    def create_outbox(
        self,
        *,
        trace_id: str,
        inbound_record_id: str,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
        reply_action: str,
        reply_text: str,
        reply_source: str,
        max_retries: int = 3,
    ) -> OutboxRecord:
        reply_hash = hashlib.sha256(str(reply_text or "").encode("utf-8")).hexdigest()[:16]
        dedupe_key = "|".join(str(part or "") for part in (inbound_record_id, reply_action, reply_hash))
        now = self._now()
        idempotency_key = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:24]
        with self._connect() as conn:
            existing = conn.execute("SELECT id, status FROM pdd_reply_outbox WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            if existing:
                return OutboxRecord(str(existing["id"]), False, str(existing["status"]))
            outbox_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO pdd_reply_outbox
                    (id, dedupe_key, trace_id, inbound_record_id, shop_id, user_id, buyer_id,
                     session_id, reply_action, reply_source, reply_hash, reply_length, status,
                     retry_count, reply_text, max_retries, next_retry_at, idempotency_key,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_send', 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outbox_id,
                    dedupe_key,
                    str(trace_id or ""),
                    str(inbound_record_id or ""),
                    str(shop_id or ""),
                    str(user_id or ""),
                    str(buyer_id or ""),
                    str(session_id or ""),
                    str(reply_action or "reply"),
                    str(reply_source or ""),
                    reply_hash,
                    len(str(reply_text or "")),
                    str(reply_text or ""),
                    max(0, int(max_retries)),
                    now,
                    idempotency_key,
                    now,
                    now,
                ),
            )
            return OutboxRecord(outbox_id, True, "pending_send")

    def mark_outbox_sending(self, outbox_id: str) -> None:
        self._update_outbox_status(outbox_id, "sending")

    def mark_outbox_sent(self, outbox_id: str) -> None:
        self._update_outbox_status(outbox_id, "sent")

    def mark_outbox_failed(self, outbox_id: str, *, pdd_error_code: str = "", error_summary_hash: str = "") -> None:
        row = self.get_outbox(outbox_id)
        action = str(row.get("reply_action") or "reply")
        status = "transfer_send_failed" if action == "transfer_human" else "reply_send_failed"
        self._update_outbox_status(outbox_id, status, pdd_error_code=pdd_error_code, error_summary_hash=error_summary_hash)

    def mark_outbox_unknown(self, outbox_id: str, *, pdd_error_code: str = "", error_summary_hash: str = "") -> None:
        row = self.get_outbox(outbox_id)
        action = str(row.get("reply_action") or "reply")
        status = "transfer_delivery_unknown" if action == "transfer_human" else "reply_delivery_unknown"
        self._update_outbox_status(outbox_id, status, pdd_error_code=pdd_error_code, error_summary_hash=error_summary_hash)

    def mark_outbox_suppressed(self, outbox_id: str, status: str, *, error_summary_hash: str = "") -> None:
        allowed = {
            "suppressed_duplicate",
            "suppressed_repeated_40013",
            "blocked_by_platform_policy",
            "pdd_sending_disabled",
            "dead_letter",
        }
        safe_status = status if status in allowed else "dead_letter"
        self._update_outbox_status(outbox_id, safe_status, error_summary_hash=error_summary_hash)

    def recover_stale_sending_outbox(
        self,
        *,
        now: float | None = None,
        timeout_seconds: float = 60.0,
    ) -> int:
        selected_now = self._now() if now is None else float(now)
        cutoff = selected_now - max(1.0, float(timeout_seconds or 60.0))
        with self._connect() as conn:
            reply_count = conn.execute(
                """
                UPDATE pdd_reply_outbox
                SET status = 'reply_delivery_unknown',
                    next_retry_at = ?,
                    updated_at = ?
                WHERE status = 'sending'
                  AND reply_action != 'transfer_human'
                  AND last_attempt_at > 0
                  AND last_attempt_at <= ?
                """,
                (selected_now, selected_now, cutoff),
            ).rowcount
            transfer_count = conn.execute(
                """
                UPDATE pdd_reply_outbox
                SET status = 'transfer_delivery_unknown',
                    next_retry_at = ?,
                    updated_at = ?
                WHERE status = 'sending'
                  AND reply_action = 'transfer_human'
                  AND last_attempt_at > 0
                  AND last_attempt_at <= ?
                """,
                (selected_now, selected_now, cutoff),
            ).rowcount
        return int(reply_count or 0) + int(transfer_count or 0)

    def recent_reply_stats(
        self,
        *,
        session_id: str,
        reply_hash: str,
        exclude_outbox_id: str = "",
        now: float | None = None,
        window_seconds: float = 600.0,
    ) -> dict[str, int]:
        selected_now = self._now() if now is None else float(now)
        cutoff = selected_now - max(1.0, float(window_seconds or 600.0))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, pdd_error_code, COUNT(*) AS count
                FROM pdd_reply_outbox
                WHERE session_id = ?
                  AND reply_hash = ?
                  AND id != ?
                  AND updated_at >= ?
                GROUP BY status, pdd_error_code
                """,
                (str(session_id or ""), str(reply_hash or ""), str(exclude_outbox_id or ""), cutoff),
            ).fetchall()
        stats = {
            "sent_count": 0,
            "failed_40013_count": 0,
            "send_failed_count": 0,
            "unknown_count": 0,
        }
        for row in rows:
            status = str(row["status"] or "")
            error_code = str(row["pdd_error_code"] or "")
            count = int(row["count"] or 0)
            if status == "sent":
                stats["sent_count"] += count
            if status in {"reply_send_failed", "transfer_send_failed"}:
                stats["send_failed_count"] += count
                if error_code == "40013":
                    stats["failed_40013_count"] += count
            if status in {"reply_delivery_unknown", "transfer_delivery_unknown"}:
                stats["unknown_count"] += count
        return stats

    def recover_retryable_outbox(self, *, now: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
        selected_now = self._now() if now is None else float(now)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM pdd_reply_outbox
                WHERE status IN ('reply_send_failed', 'reply_delivery_unknown')
                  AND retry_count < max_retries
                  AND next_retry_at <= ?
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (selected_now, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_retryable_outbox(self, *, now: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Atomically claim due outbox rows for retry.

        This avoids duplicate sends when reconnect recovery and the background
        retry loop run at the same time, or when multiple channel instances are
        alive in the same process.
        """

        selected_now = self._now() if now is None else float(now)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT * FROM pdd_reply_outbox
                WHERE status IN ('reply_send_failed', 'reply_delivery_unknown')
                  AND retry_count < max_retries
                  AND next_retry_at <= ?
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (selected_now, max(1, int(limit))),
            ).fetchall()
            row_ids = [str(row["id"]) for row in rows]
            if row_ids:
                placeholders = ",".join("?" for _ in row_ids)
                conn.execute(
                    f"""
                    UPDATE pdd_reply_outbox
                    SET status = 'sending',
                        last_attempt_at = ?,
                        updated_at = ?
                    WHERE id IN ({placeholders})
                      AND status IN ('reply_send_failed', 'reply_delivery_unknown')
                    """,
                    (selected_now, selected_now, *row_ids),
                )
            conn.commit()
        return [dict(row) for row in rows]

    def get_outbox(self, outbox_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pdd_reply_outbox WHERE id = ?", (outbox_id,)).fetchone()
        if not row:
            return {}
        return dict(row)

    def _update_inbound_status(
        self,
        record_id: str,
        status: str,
        *,
        increment_retry: bool = False,
        error_type: str = "",
    ) -> None:
        retry_expr = "retry_count + 1" if increment_retry else "retry_count"
        with self._connect() as conn:
            conn.execute(
                f"UPDATE pdd_inbound_message_queue SET status = ?, retry_count = {retry_expr}, error_type = ?, updated_at = ? WHERE id = ?",
                (status, str(error_type or ""), self._now(), record_id),
            )

    def _update_outbox_status(
        self,
        outbox_id: str,
        status: str,
        *,
        pdd_error_code: str = "",
        error_summary_hash: str = "",
    ) -> None:
        now = self._now()
        next_retry_at = now
        if status in {"reply_send_failed", "transfer_send_failed"}:
            row = self.get_outbox(outbox_id)
            retry_count = int(row.get("retry_count") or 0) + 1
            delays = (30, 120, 300)
            next_retry_at = now + delays[min(retry_count - 1, len(delays) - 1)]
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pdd_reply_outbox
                SET status = ?,
                    retry_count = CASE WHEN ? IN ('reply_send_failed', 'transfer_send_failed') THEN retry_count + 1 ELSE retry_count END,
                    pdd_error_code = ?,
                    error_summary_hash = ?,
                    next_retry_at = ?,
                    last_attempt_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    status,
                    str(pdd_error_code or ""),
                    str(error_summary_hash or ""),
                    next_retry_at,
                    now if status in {"sending", "sent", "reply_send_failed", "transfer_send_failed"} else 0,
                    now,
                    outbox_id,
                ),
            )

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pdd_inbound_message_queue (
                    id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    queue_name TEXT NOT NULL,
                    source_message_id TEXT,
                    trace_id TEXT,
                    shop_id TEXT,
                    user_id TEXT,
                    buyer_id TEXT,
                    session_id TEXT,
                    message_type TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_pdd_inbound_recover
                ON pdd_inbound_message_queue(queue_name, status, updated_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pdd_reply_outbox (
                    id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    trace_id TEXT,
                    inbound_record_id TEXT,
                    shop_id TEXT,
                    user_id TEXT,
                    buyer_id TEXT,
                    session_id TEXT,
                    reply_action TEXT,
                    reply_source TEXT,
                    reply_hash TEXT,
                    reply_length INTEGER,
                    reply_text TEXT,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    next_retry_at REAL NOT NULL DEFAULT 0,
                    last_attempt_at REAL NOT NULL DEFAULT 0,
                    idempotency_key TEXT,
                    pdd_error_code TEXT,
                    error_summary_hash TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_pdd_outbox_status
                ON pdd_reply_outbox(status, next_retry_at, updated_at)
                """
            )
            self._ensure_outbox_columns(conn)

    @staticmethod
    def _ensure_outbox_columns(conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(pdd_reply_outbox)").fetchall()}
        additions = {
            "reply_text": "TEXT",
            "max_retries": "INTEGER NOT NULL DEFAULT 3",
            "next_retry_at": "REAL NOT NULL DEFAULT 0",
            "last_attempt_at": "REAL NOT NULL DEFAULT 0",
            "idempotency_key": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE pdd_reply_outbox ADD COLUMN {name} {ddl}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _inbound_dedupe_key(queue_name: str, payload: dict[str, Any], source_message_id: str) -> str:
        return "|".join(
            str(part or "")
            for part in (
                queue_name,
                payload.get("shop_id"),
                payload.get("user_id"),
                payload.get("from_uid"),
                source_message_id,
            )
        )

    @staticmethod
    def _context_to_payload(context: Context) -> dict[str, Any]:
        kwargs = getattr(context, "kwargs", None)
        if hasattr(kwargs, "model_dump"):
            data = kwargs.model_dump()
        elif isinstance(kwargs, dict):
            data = dict(kwargs)
        else:
            data = dict(getattr(kwargs, "__dict__", {}) or {})
        data.update(
            {
                "content": context.content,
                "context_type": context.type.value if hasattr(context.type, "value") else str(context.type),
                "channel_type": context.channel_type.value if hasattr(context.channel_type, "value") else str(context.channel_type or ""),
            }
        )
        return data

    @staticmethod
    def _payload_to_context(payload: dict[str, Any]) -> Context:
        context_type = ContextType(payload.get("context_type") or "text")
        channel_value = payload.get("channel_type") or ChannelType.PINDUODUO.value
        return Context.create_pinduoduo_context(
            content=payload.get("content"),
            msg_id=payload.get("msg_id") or payload.get("source_message_id"),
            from_uid=payload.get("from_uid"),
            to_uid=payload.get("to_uid"),
            nickname=payload.get("nickname"),
            timestamp=payload.get("timestamp"),
            user_msg_type=context_type,
            shop_id=payload.get("shop_id"),
            user_id=payload.get("user_id"),
            username=payload.get("username"),
            shop_name=payload.get("shop_name"),
            goods_id=payload.get("goods_id"),
            raw_data=payload.get("raw_data") if isinstance(payload.get("raw_data"), dict) else None,
            channel_type=ChannelType(channel_value),
            trace_id=payload.get("trace_id"),
            source_message_id=payload.get("source_message_id"),
            queue_name=payload.get("queue_name"),
            message_type=payload.get("message_type"),
            content_length=payload.get("content_length"),
            content_hash=payload.get("content_hash"),
        )


_default_store: ReliableQueueStore | None = None


def get_reliable_queue_store() -> ReliableQueueStore:
    global _default_store
    if _default_store is None:
        _default_store = ReliableQueueStore()
    return _default_store
