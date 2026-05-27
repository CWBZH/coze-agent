"""Read-only schema probe for conversation context SQLite history.

This script inspects table/column compatibility for
SQLiteConversationContextRepository. It never writes to the DB and never prints
raw message rows or message content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CONVERSATION_TABLES = ("conversations", "conversation")
MESSAGE_TABLES = ("messages", "conversation_messages")
SHOP_FIELDS = ("shop_id",)
USER_FIELDS = ("user_id",)
BUYER_FIELDS = ("buyer_id", "customer_uid", "from_uid")
SESSION_FIELDS = ("session_id",)
CONTENT_FIELDS = ("content", "message", "text", "body")
CREATED_AT_FIELDS = ("created_at", "created_time", "timestamp", "time")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe conversation SQLite schema in read-only mode.")
    parser.add_argument("--db-path", type=Path, default=Path("temp/channel_shop.db"))
    parser.add_argument("--shop-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--buyer-id", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def probe_schema(
    db_path: str | Path,
    *,
    shop_id: str = "",
    user_id: str = "",
    buyer_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    path = Path(db_path).expanduser()
    result = _base_result(path)
    if not path.exists():
        result["status"] = "missing"
        return result

    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        result["status"] = "open_error"
        return result

    try:
        existing_tables = _tables(conn)
        conversation_tables = [table for table in CONVERSATION_TABLES if table in existing_tables]
        message_tables = [table for table in MESSAGE_TABLES if table in existing_tables]
        result["candidate_conversation_tables"] = conversation_tables
        result["candidate_message_tables"] = message_tables
        result["detected_conversation_columns"] = {
            table: _columns(conn, table) for table in conversation_tables
        }
        result["detected_message_columns"] = {
            table: _columns(conn, table) for table in message_tables
        }
        result["sample_counts"] = {
            table: _safe_count(conn, table) for table in (*conversation_tables, *message_tables)
        }
        result["supported_mapping"] = _supported_mapping(result)
        result["missing_required_fields"] = _missing_required_fields(result["supported_mapping"])
        if not conversation_tables or not message_tables:
            result["status"] = "missing_tables"
        elif result["missing_required_fields"]:
            result["status"] = "unsupported_schema"
        else:
            result["status"] = "ok"
        result["isolation_probe_status"] = _isolation_probe(
            conn,
            result,
            shop_id=str(shop_id or ""),
            user_id=str(user_id or ""),
            buyer_id=str(buyer_id or ""),
            session_id=str(session_id or ""),
        )
        return result
    finally:
        conn.close()


def write_result(result: dict[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
    else:
        print(f"conversation_context_schema_probe: status={result['status']}")
        print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = probe_schema(
        args.db_path,
        shop_id=args.shop_id,
        user_id=args.user_id,
        buyer_id=args.buyer_id,
        session_id=args.session_id,
    )
    write_result(result, json_only=args.json_only)
    return 0


def _base_result(path: Path) -> dict[str, Any]:
    return {
        "db_path": str(path),
        "status": "unknown",
        "candidate_conversation_tables": [],
        "candidate_message_tables": [],
        "detected_conversation_columns": {},
        "detected_message_columns": {},
        "supported_mapping": {},
        "missing_required_fields": [],
        "sample_counts": {},
        "isolation_probe_status": {"status": "not_requested"},
    }


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:
        return 0


def _supported_mapping(result: dict[str, Any]) -> dict[str, bool]:
    conversation_columns = _merged_columns(result.get("detected_conversation_columns", {}))
    message_columns = _merged_columns(result.get("detected_message_columns", {}))
    identity_columns = conversation_columns | message_columns
    return {
        "conversation_table": bool(result.get("candidate_conversation_tables")),
        "message_table": bool(result.get("candidate_message_tables")),
        "shop_id": _has_any(identity_columns, SHOP_FIELDS),
        "user_id": _has_any(identity_columns, USER_FIELDS),
        "buyer_id": _has_any(identity_columns, BUYER_FIELDS),
        "session_id": _has_any(identity_columns, SESSION_FIELDS),
        "content": _has_any(message_columns, CONTENT_FIELDS),
        "created_at": _has_any(message_columns, CREATED_AT_FIELDS),
    }


def _missing_required_fields(mapping: dict[str, bool]) -> list[str]:
    required = ("conversation_table", "message_table", "shop_id", "buyer_id", "session_id", "content", "created_at")
    return [field for field in required if not mapping.get(field)]


def _isolation_probe(
    conn: sqlite3.Connection,
    result: dict[str, Any],
    *,
    shop_id: str,
    user_id: str,
    buyer_id: str,
    session_id: str,
) -> dict[str, Any]:
    if not (shop_id and buyer_id and session_id):
        return {"status": "not_requested"}
    message_tables = list(result.get("candidate_message_tables") or [])
    if not message_tables:
        return {"status": "missing_message_table"}
    table = message_tables[0]
    columns = set(result.get("detected_message_columns", {}).get(table, []))
    filters = _filters(columns, shop_id=shop_id, user_id=user_id, buyer_id=buyer_id, session_id=session_id)
    if filters is None:
        return {"status": "missing_identity_fields"}
    where = " AND ".join(f'"{field}" = ?' for field, _ in filters)
    values = [value for _, value in filters]
    try:
        count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}', values).fetchone()[0])
    except sqlite3.Error:
        return {"status": "query_error"}
    return {
        "status": "ok",
        "matched_count": count,
        "shop_id_hash": _hash_or_empty(shop_id),
        "buyer_id_hash": _hash_or_empty(buyer_id),
        "session_id_hash": _hash_or_empty(session_id),
    }


def _filters(
    columns: set[str],
    *,
    shop_id: str,
    user_id: str,
    buyer_id: str,
    session_id: str,
) -> list[tuple[str, str]] | None:
    shop_field = _first(columns, SHOP_FIELDS)
    buyer_field = _first(columns, BUYER_FIELDS)
    session_field = _first(columns, SESSION_FIELDS)
    if not (shop_field and buyer_field and session_field):
        return None
    filters = [(shop_field, shop_id), (buyer_field, buyer_id), (session_field, session_id)]
    user_field = _first(columns, USER_FIELDS)
    if user_id and user_field:
        filters.append((user_field, user_id))
    return filters


def _merged_columns(tables: object) -> set[str]:
    merged: set[str] = set()
    if isinstance(tables, dict):
        for columns in tables.values():
            if isinstance(columns, list):
                merged.update(str(column) for column in columns)
    return merged


def _has_any(columns: set[str], candidates: Iterable[str]) -> bool:
    return any(candidate in columns for candidate in candidates)


def _first(columns: set[str], candidates: Iterable[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return ""


def _hash_or_empty(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else ""


if __name__ == "__main__":
    raise SystemExit(main())
