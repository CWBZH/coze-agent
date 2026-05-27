"""Read-only conversation context primitives for internal workflow history."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol


DEFAULT_HISTORY_LIMIT = 40


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    message_type: str
    content: str = field(repr=False)
    content_summary: str
    content_hash: str
    created_at: str
    source: str = ""


@dataclass(frozen=True)
class ConversationContext:
    shop_id: str
    user_id: str
    buyer_id: str
    session_id: str
    conversation_id: str
    human_state: str = ""
    pending_human: bool = False
    recent_messages: tuple[ConversationMessage, ...] = field(default_factory=tuple)
    history_window: tuple[ConversationMessage, ...] = field(default_factory=tuple)
    history_message_count: int = 0
    last_intent: str = ""
    last_action: str = ""
    history_source: str = ""


class ConversationContextRepository(Protocol):
    def load_context(
        self,
        *,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> ConversationContext:
        ...


@dataclass(frozen=True)
class ConversationRecord:
    shop_id: str
    user_id: str
    buyer_id: str
    session_id: str
    role: str
    message_type: str
    content: str = ""
    created_at: str = ""
    source: str = ""
    human_state: str = ""
    pending_human: bool = False
    intent: str = ""
    action: str = ""


class InMemoryConversationContextRepository:
    """Read-only in-memory repository for deterministic isolation tests."""

    def __init__(self, records: Iterable[ConversationRecord | dict] | None = None):
        self._records = tuple(_coerce_record(record) for record in (records or ()))

    def load_context(
        self,
        *,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> ConversationContext:
        normalized_limit = max(0, int(limit or 0))
        matched = [
            record
            for record in self._records
            if record.shop_id == str(shop_id or "")
            and record.user_id == str(user_id or "")
            and record.buyer_id == str(buyer_id or "")
            and record.session_id == str(session_id or "")
        ]
        ordered = sorted(matched, key=lambda record: _sort_key(record.created_at))
        window_records = ordered[-normalized_limit:] if normalized_limit else []
        window = tuple(_message_from_record(record) for record in window_records)
        last_record = ordered[-1] if ordered else None
        pending_human = any(record.pending_human for record in ordered)
        human_state = _last_text(record.human_state for record in ordered)
        return ConversationContext(
            shop_id=str(shop_id or ""),
            user_id=str(user_id or ""),
            buyer_id=str(buyer_id or ""),
            session_id=str(session_id or ""),
            conversation_id=conversation_id(shop_id, user_id, buyer_id, session_id),
            human_state=human_state,
            pending_human=pending_human,
            recent_messages=window,
            history_window=window,
            history_message_count=len(ordered),
            last_intent=last_record.intent if last_record else "",
            last_action=last_record.action if last_record else "",
            history_source="memory",
        )


class SQLiteConversationContextRepository:
    """Read-only SQLite adapter for conversation history.

    The adapter is deliberately defensive: if the DB, required tables, or
    required isolation fields are missing, it returns an empty context instead
    of weakening shop/buyer/session isolation.
    """

    _CONVERSATION_TABLES = ("conversations", "conversation")
    _MESSAGE_TABLES = ("messages", "conversation_messages")
    _CONVERSATION_ID_FIELDS = ("conversation_id", "id")
    _SHOP_FIELDS = ("shop_id",)
    _USER_FIELDS = ("user_id",)
    _BUYER_FIELDS = ("buyer_id", "customer_uid", "from_uid")
    _SESSION_FIELDS = ("session_id",)
    _ROLE_FIELDS = ("role", "direction")
    _MESSAGE_TYPE_FIELDS = ("message_type", "type")
    _CONTENT_FIELDS = ("content", "message", "text", "body")
    _CREATED_AT_FIELDS = ("created_at", "created_time", "timestamp", "time")
    _SOURCE_FIELDS = ("source", "origin")
    _HUMAN_STATE_FIELDS = ("human_state", "status")
    _PENDING_HUMAN_FIELDS = ("pending_human", "is_pending_human")
    _INTENT_FIELDS = ("intent", "last_intent")
    _ACTION_FIELDS = ("action", "last_action")
    _PENDING_HUMAN_STATES = {"pending_human", "human", "manual", "transferred"}

    def __init__(self, db_path: str | Path, timeout: float | None = None):
        self.db_path = Path(db_path).expanduser()
        self.timeout = 5.0 if timeout is None else float(timeout)

    def load_context(
        self,
        *,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> ConversationContext:
        shop_id = str(shop_id or "")
        user_id = str(user_id or "")
        buyer_id = str(buyer_id or "")
        session_id = str(session_id or "")
        if not shop_id or not buyer_id or not session_id:
            return _empty_context(shop_id, user_id, buyer_id, session_id, history_source="sqlite")
        if not self.db_path.exists():
            return _empty_context(shop_id, user_id, buyer_id, session_id, history_source="sqlite_missing")
        try:
            conn = sqlite3.connect(
                f"file:{self.db_path.resolve().as_posix()}?mode=ro",
                timeout=self.timeout,
                uri=True,
            )
        except sqlite3.Error:
            return _empty_context(shop_id, user_id, buyer_id, session_id, history_source="sqlite_error")

        try:
            conn.row_factory = sqlite3.Row
            conversation_table = self._first_existing_table(conn, self._CONVERSATION_TABLES)
            message_table = self._first_existing_table(conn, self._MESSAGE_TABLES)
            if not message_table:
                return _empty_context(shop_id, user_id, buyer_id, session_id, history_source="sqlite_missing_table")

            conversation_rows: list[sqlite3.Row] = []
            conversation_ids: list[str] = []
            pending_human = False
            human_state = ""
            last_intent = ""
            last_action = ""

            if conversation_table:
                conversation_columns = self._table_columns(conn, conversation_table)
                conversation_rows = self._load_conversation_rows(
                    conn,
                    conversation_table,
                    conversation_columns,
                    shop_id=shop_id,
                    user_id=user_id,
                    buyer_id=buyer_id,
                    session_id=session_id,
                )
                conversation_ids = [
                    str(self._row_value(row, self._CONVERSATION_ID_FIELDS) or "")
                    for row in conversation_rows
                    if self._row_value(row, self._CONVERSATION_ID_FIELDS)
                ]
                pending_human = any(self._row_pending_human(row) for row in conversation_rows)
                human_state = _last_text(
                    str(self._row_value(row, self._HUMAN_STATE_FIELDS) or "")
                    for row in conversation_rows
                )
                last_intent = _last_text(
                    str(self._row_value(row, self._INTENT_FIELDS) or "")
                    for row in conversation_rows
                )
                last_action = _last_text(
                    str(self._row_value(row, self._ACTION_FIELDS) or "")
                    for row in conversation_rows
                )

            message_columns = self._table_columns(conn, message_table)
            records = self._load_message_records(
                conn,
                message_table,
                message_columns,
                conversation_ids=conversation_ids,
                shop_id=shop_id,
                user_id=user_id,
                buyer_id=buyer_id,
                session_id=session_id,
                inherited_human_state=human_state,
                inherited_pending_human=pending_human,
            )
            if not records and conversation_table and not conversation_rows:
                return _empty_context(shop_id, user_id, buyer_id, session_id, history_source="sqlite")

            ordered = sorted(records, key=lambda record: _sort_key(record.created_at))
            normalized_limit = max(0, int(limit or 0))
            window_records = ordered[-normalized_limit:] if normalized_limit else []
            window = tuple(_message_from_record(record) for record in window_records)
            pending_human = pending_human or any(record.pending_human for record in ordered)
            human_state = human_state or _last_text(record.human_state for record in ordered)
            last_record = ordered[-1] if ordered else None
            return ConversationContext(
                shop_id=shop_id,
                user_id=user_id,
                buyer_id=buyer_id,
                session_id=session_id,
                conversation_id=conversation_id(shop_id, user_id, buyer_id, session_id),
                human_state=human_state,
                pending_human=pending_human,
                recent_messages=window,
                history_window=window,
                history_message_count=len(ordered),
                last_intent=last_intent or (last_record.intent if last_record else ""),
                last_action=last_action or (last_record.action if last_record else ""),
                history_source="sqlite",
            )
        except sqlite3.Error:
            return _empty_context(shop_id, user_id, buyer_id, session_id, history_source="sqlite_error")
        finally:
            conn.close()

    def _load_conversation_rows(
        self,
        conn: sqlite3.Connection,
        table: str,
        columns: set[str],
        *,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
    ) -> list[sqlite3.Row]:
        filters = self._identity_filters(
            columns,
            shop_id=shop_id,
            user_id=user_id,
            buyer_id=buyer_id,
            session_id=session_id,
        )
        if filters is None:
            return []
        sql, values = self._where_sql(table, filters)
        return list(conn.execute(sql, values).fetchall())

    def _load_message_records(
        self,
        conn: sqlite3.Connection,
        table: str,
        columns: set[str],
        *,
        conversation_ids: list[str],
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
        inherited_human_state: str,
        inherited_pending_human: bool,
    ) -> list[ConversationRecord]:
        rows: list[sqlite3.Row]
        conversation_id_field = self._first_column(columns, self._CONVERSATION_ID_FIELDS)
        if conversation_ids and conversation_id_field:
            placeholders = ",".join("?" for _ in conversation_ids)
            rows = list(
                conn.execute(
                    f'SELECT * FROM "{table}" WHERE "{conversation_id_field}" IN ({placeholders})',
                    conversation_ids,
                ).fetchall()
            )
            rows = [
                row
                for row in rows
                if self._row_matches_available_identity(
                    row,
                    shop_id=shop_id,
                    user_id=user_id,
                    buyer_id=buyer_id,
                    session_id=session_id,
                )
            ]
        else:
            filters = self._identity_filters(
                columns,
                shop_id=shop_id,
                user_id=user_id,
                buyer_id=buyer_id,
                session_id=session_id,
            )
            if filters is None:
                return []
            sql, values = self._where_sql(table, filters)
            rows = list(conn.execute(sql, values).fetchall())

        return [
            ConversationRecord(
                shop_id=shop_id,
                user_id=user_id,
                buyer_id=buyer_id,
                session_id=session_id,
                role=str(self._row_value(row, self._ROLE_FIELDS) or ""),
                message_type=str(self._row_value(row, self._MESSAGE_TYPE_FIELDS) or "text"),
                content=str(self._row_value(row, self._CONTENT_FIELDS) or ""),
                created_at=str(self._row_value(row, self._CREATED_AT_FIELDS) or ""),
                source=str(self._row_value(row, self._SOURCE_FIELDS) or "sqlite"),
                human_state=str(self._row_value(row, self._HUMAN_STATE_FIELDS) or inherited_human_state),
                pending_human=inherited_pending_human or self._row_pending_human(row),
                intent=str(self._row_value(row, self._INTENT_FIELDS) or ""),
                action=str(self._row_value(row, self._ACTION_FIELDS) or ""),
            )
            for row in rows
        ]

    def _identity_filters(
        self,
        columns: set[str],
        *,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
    ) -> list[tuple[str, str]] | None:
        shop_field = self._first_column(columns, self._SHOP_FIELDS)
        buyer_field = self._first_column(columns, self._BUYER_FIELDS)
        session_field = self._first_column(columns, self._SESSION_FIELDS)
        if not shop_field or not buyer_field or not session_field:
            return None
        filters = [(shop_field, shop_id), (buyer_field, buyer_id), (session_field, session_id)]
        user_field = self._first_column(columns, self._USER_FIELDS)
        if user_id:
            if not user_field:
                return None
            filters.append((user_field, user_id))
        return filters

    def _row_matches_available_identity(
        self,
        row: sqlite3.Row,
        *,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
    ) -> bool:
        row_keys = set(row.keys())
        required = (
            (self._SHOP_FIELDS, shop_id),
            (self._BUYER_FIELDS, buyer_id),
            (self._SESSION_FIELDS, session_id),
        )
        for candidates, expected in required:
            field = self._first_column(row_keys, candidates)
            if field and str(row[field]) != expected:
                return False
        user_field = self._first_column(row_keys, self._USER_FIELDS)
        if user_id and user_field and str(row[user_field]) != user_id:
            return False
        return True

    @staticmethod
    def _where_sql(table: str, filters: list[tuple[str, str]]) -> tuple[str, list[str]]:
        where = " AND ".join(f'"{field}" = ?' for field, _ in filters)
        values = [value for _, value in filters]
        return f'SELECT * FROM "{table}" WHERE {where}', values

    @staticmethod
    def _first_existing_table(conn: sqlite3.Connection, candidates: Iterable[str]) -> str:
        existing = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for candidate in candidates:
            if candidate in existing:
                return candidate
        return ""

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}

    @staticmethod
    def _first_column(columns: set[str], candidates: Iterable[str]) -> str:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return ""

    @staticmethod
    def _row_value(row: sqlite3.Row, candidates: Iterable[str]) -> object:
        keys = set(row.keys())
        for candidate in candidates:
            if candidate in keys:
                return row[candidate]
        return None

    def _row_pending_human(self, row: sqlite3.Row) -> bool:
        value = self._row_value(row, self._PENDING_HUMAN_FIELDS)
        if _truthy(value):
            return True
        states = [
            str(self._row_value(row, self._HUMAN_STATE_FIELDS) or "").strip().lower(),
            str(self._row_value(row, ("status",)) or "").strip().lower(),
        ]
        return any(state in self._PENDING_HUMAN_STATES for state in states)


def _empty_context(
    shop_id: str,
    user_id: str,
    buyer_id: str,
    session_id: str,
    *,
    history_source: str = "",
) -> ConversationContext:
        return ConversationContext(
            shop_id=str(shop_id or ""),
            user_id=str(user_id or ""),
            buyer_id=str(buyer_id or ""),
            session_id=str(session_id or ""),
            conversation_id=conversation_id(shop_id, user_id, buyer_id, session_id),
            history_source=history_source,
        )


def conversation_id(shop_id: object, user_id: object, buyer_id: object, session_id: object) -> str:
    return stable_hash("|".join(str(value or "") for value in (shop_id, user_id, buyer_id, session_id)))


def summarize_content(content: object) -> str:
    text = str(content or "")
    return f"len={len(text)} hash={stable_hash(text)}"


def stable_hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pending_human", "human"}


def _message_from_record(record: ConversationRecord) -> ConversationMessage:
    return ConversationMessage(
        role=record.role,
        message_type=record.message_type,
        content=record.content,
        content_summary=summarize_content(record.content),
        content_hash=stable_hash(record.content),
        created_at=record.created_at,
        source=record.source,
    )


def _coerce_record(record: ConversationRecord | dict) -> ConversationRecord:
    if isinstance(record, ConversationRecord):
        return record
    return ConversationRecord(
        shop_id=str(record.get("shop_id") or ""),
        user_id=str(record.get("user_id") or ""),
        buyer_id=str(record.get("buyer_id") or ""),
        session_id=str(record.get("session_id") or ""),
        role=str(record.get("role") or ""),
        message_type=str(record.get("message_type") or "text"),
        content=str(record.get("content") or ""),
        created_at=str(record.get("created_at") or ""),
        source=str(record.get("source") or ""),
        human_state=str(record.get("human_state") or ""),
        pending_human=bool(record.get("pending_human")),
        intent=str(record.get("intent") or ""),
        action=str(record.get("action") or ""),
    )


def _sort_key(created_at: str) -> tuple[int, str]:
    text = str(created_at or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (0, parsed.astimezone(timezone.utc).isoformat())
    except ValueError:
        return (1, text)


def _last_text(values: Iterable[str]) -> str:
    last = ""
    for value in values:
        if str(value or ""):
            last = str(value)
    return last
