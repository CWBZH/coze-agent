from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


PREVIEW_LIMIT = 120


@dataclass(frozen=True)
class HumanLockListResult:
    items: list[dict[str, Any]]
    total: int
    warning: str | None = None


class HumanLockService:
    """Manage local pending_human conversation state for Web Admin.

    The authoritative human lock state is Conversation.status in SQLite.
    All write operations require a platform shop_id and resolve it against
    shops.id before updating conversations.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        configured = db_path or os.getenv("WEB_API_SQLITE_DB_PATH") or DEFAULT_DB_PATH
        self.db_path = Path(configured)

    def list_locks(
        self,
        *,
        shop_id: str | None,
        buyer_id: str | None = None,
        session_id: str | None = None,
        status: str = "pending_human",
        limit: int = 100,
        offset: int = 0,
    ) -> HumanLockListResult:
        shop_id = self._require_shop_id(shop_id)
        if not self.db_path.exists():
            return HumanLockListResult(items=[], total=0, warning="db_missing")
        with self._connect() as conn:
            if not self._table_exists(conn, "conversations"):
                return HumanLockListResult(items=[], total=0, warning="missing_table:conversations")
            if not self._table_exists(conn, "shops"):
                return HumanLockListResult(items=[], total=0, warning="missing_table:shops")
            clauses, params = self._base_where(shop_id, status=status)
            if buyer_id:
                clauses.append("c.buyer_id = ?")
                params.append(buyer_id)
            if session_id:
                clauses.append("c.session_id = ?")
                params.append(session_id)
            where_sql = " AND ".join(clauses)
            count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM conversations c
                LEFT JOIN shops s ON s.id = c.shop_id
                WHERE {where_sql}
                """,
                tuple(params),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT c.*, s.shop_id AS platform_shop_id, s.shop_name AS shop_name
                FROM conversations c
                LEFT JOIN shops s ON s.id = c.shop_id
                WHERE {where_sql}
                ORDER BY COALESCE(c.updated_at, c.created_at, '') DESC, c.id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params + [self._clamp_limit(limit), max(0, int(offset or 0))]),
            ).fetchall()
            items = [self._row_to_item(conn, row, requested_shop_id=shop_id) for row in rows]
            return HumanLockListResult(items=items, total=int(count_row["total"] or 0))

    def unlock_lock(self, lock_id: str, *, shop_id: str | None, operator: str, reason: str) -> dict[str, Any]:
        shop_id = self._require_shop_id(shop_id)
        with self._connect_existing() as conn:
            row = self._get_lock_row(conn, lock_id, shop_id)
            if row is None:
                raise KeyError("not_found")
            updated_at = self._now()
            if str(row["status"] or "") != "pending_human":
                return {
                    "id": str(row["id"]),
                    "shop_id": shop_id,
                    "unlocked": False,
                    "already_unlocked": True,
                    "operator": operator or "local_admin",
                    "reason": reason or "",
                    "updated_at": str(row["updated_at"] or updated_at),
                }
            self._update_status(conn, [row["id"]], operator=operator, reason=reason, updated_at=updated_at)
            conn.commit()
            return {
                "id": str(row["id"]),
                "shop_id": shop_id,
                "unlocked": True,
                "already_unlocked": False,
                "operator": operator or "local_admin",
                "reason": reason or "",
                "updated_at": updated_at,
            }

    def unlock_by_session(
        self,
        *,
        shop_id: str | None,
        buyer_id: str | None = None,
        session_id: str | None = None,
        operator: str,
        reason: str,
    ) -> dict[str, Any]:
        shop_id = self._require_shop_id(shop_id)
        if not buyer_id and not session_id:
            raise ValueError("buyer_id_or_session_id_required")
        with self._connect_existing() as conn:
            clauses, params = self._base_where(shop_id, status="pending_human")
            if buyer_id:
                clauses.append("c.buyer_id = ?")
                params.append(buyer_id)
            if session_id:
                clauses.append("c.session_id = ?")
                params.append(session_id)
            rows = conn.execute(
                f"""
                SELECT c.id
                FROM conversations c
                LEFT JOIN shops s ON s.id = c.shop_id
                WHERE {" AND ".join(clauses)}
                """,
                tuple(params),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                self._update_status(conn, ids, operator=operator, reason=reason, updated_at=self._now())
                conn.commit()
            return {
                "shop_id": shop_id,
                "matched_count": len(ids),
                "unlocked_count": len(ids),
                "operator": operator or "local_admin",
                "reason": reason or "",
            }

    def bulk_unlock(self, *, shop_id: str | None, operator: str, reason: str, limit: int = 100) -> dict[str, Any]:
        shop_id = self._require_shop_id(shop_id)
        limit = self._clamp_limit(limit)
        with self._connect_existing() as conn:
            clauses, params = self._base_where(shop_id, status="pending_human")
            rows = conn.execute(
                f"""
                SELECT c.id
                FROM conversations c
                LEFT JOIN shops s ON s.id = c.shop_id
                WHERE {" AND ".join(clauses)}
                ORDER BY COALESCE(c.updated_at, c.created_at, '') DESC, c.id DESC
                LIMIT ?
                """,
                tuple(params + [limit]),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                self._update_status(conn, ids, operator=operator, reason=reason, updated_at=self._now())
                conn.commit()
            return {
                "shop_id": shop_id,
                "matched_count": len(ids),
                "unlocked_count": len(ids),
                "operator": operator or "local_admin",
                "reason": reason or "",
            }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_existing(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError("db_missing")
        conn = self._connect()
        if not self._table_exists(conn, "conversations"):
            conn.close()
            raise LookupError("missing_table:conversations")
        if not self._table_exists(conn, "shops"):
            conn.close()
            raise LookupError("missing_table:shops")
        return conn

    @staticmethod
    def _require_shop_id(shop_id: str | None) -> str:
        value = str(shop_id or "").strip()
        if not value:
            raise ValueError("shop_id_required")
        return value

    @staticmethod
    def _clamp_limit(limit: int) -> int:
        try:
            parsed = int(limit)
        except (TypeError, ValueError):
            parsed = 100
        return max(1, min(parsed, 500))

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(sep=" ", timespec="seconds")

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    @staticmethod
    def _base_where(shop_id: str, *, status: str | None) -> tuple[list[str], list[Any]]:
        clauses = ["(s.shop_id = ? OR CAST(c.shop_id AS TEXT) = ?)"]
        params: list[Any] = [shop_id, shop_id]
        if status:
            clauses.append("c.status = ?")
            params.append(status)
        return clauses, params

    def _get_lock_row(self, conn: sqlite3.Connection, lock_id: str, shop_id: str) -> sqlite3.Row | None:
        clauses, params = self._base_where(shop_id, status=None)
        clauses.append("CAST(c.id AS TEXT) = ?")
        params.append(str(lock_id))
        return conn.execute(
            f"""
            SELECT c.*, s.shop_id AS platform_shop_id, s.shop_name AS shop_name
            FROM conversations c
            LEFT JOIN shops s ON s.id = c.shop_id
            WHERE {" AND ".join(clauses)}
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()

    def _update_status(
        self,
        conn: sqlite3.Connection,
        conversation_ids: list[Any],
        *,
        operator: str,
        reason: str,
        updated_at: str,
    ) -> None:
        if not conversation_ids:
            return
        columns = self._columns(conn, "conversations")
        set_parts = ["status = ?"]
        params: list[Any] = ["active"]
        optional_values = {
            "updated_at": updated_at,
            "unlocked_at": updated_at,
            "unlock_operator": operator or "local_admin",
            "unlock_reason": reason or "",
            "human_unlock_operator": operator or "local_admin",
            "human_unlock_reason": reason or "",
        }
        for column, value in optional_values.items():
            if column in columns:
                set_parts.append(f"{column} = ?")
                params.append(value)
        placeholders = ",".join("?" for _ in conversation_ids)
        params.extend(conversation_ids)
        conn.execute(
            f"UPDATE conversations SET {', '.join(set_parts)} WHERE id IN ({placeholders}) AND status = 'pending_human'",
            tuple(params),
        )

    def _row_to_item(self, conn: sqlite3.Connection, row: sqlite3.Row, *, requested_shop_id: str) -> dict[str, Any]:
        data = dict(row)
        session_id = str(data.get("session_id") or "")
        reason = self._pick(data, "reason", "transfer_reason", "human_reason")
        intent = self._pick(data, "intent", "last_intent")
        source = self._pick(data, "source", "human_source", "transfer_source") or "unknown"
        trace_id = self._pick(data, "trace_id", "last_trace_id")
        updated_at = str(data.get("updated_at") or "")
        locked_at = self._pick(data, "locked_at", "created_at", "updated_at")
        return {
            "id": str(data.get("id") or session_id),
            "shop_id": str(data.get("platform_shop_id") or requested_shop_id),
            "buyer_id": str(data.get("buyer_id") or ""),
            "session_id": session_id,
            "status": str(data.get("status") or ""),
            "reason": reason,
            "intent": intent,
            "source": source,
            "trace_id": trace_id,
            "last_message_preview": self._last_message_preview(conn, session_id),
            "locked_at": str(locked_at or ""),
            "updated_at": updated_at,
            "can_unlock": str(data.get("status") or "") == "pending_human",
        }

    def _last_message_preview(self, conn: sqlite3.Connection, session_id: str) -> str:
        if not session_id or not self._table_exists(conn, "agent_messages"):
            return ""
        row = conn.execute(
            """
            SELECT content
            FROM agent_messages
            WHERE session_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        text = str(dict(row).get("content") or "") if row else ""
        text = " ".join(text.split())
        if len(text) <= PREVIEW_LIMIT:
            return text
        return text[: PREVIEW_LIMIT - 3] + "..."

    @staticmethod
    def _pick(data: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = data.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
