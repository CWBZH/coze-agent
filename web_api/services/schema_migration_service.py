from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SchemaMigrationService:
    """Idempotent SQLite migrations for Web Admin runtime tables."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> dict[str, list[str]]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            self._ensure_migration_table(conn)
            applied: list[str] = []
            migrations: list[tuple[str, Callable[[sqlite3.Connection], None]]] = [
                ("001_web_admin_runtime_schema", self._migration_runtime_schema),
                ("002_legacy_compat_columns", self._migration_legacy_compat_columns),
                ("003_shop_identity_pending_auth", self._migration_shop_identity_pending_auth),
                ("004_quarantine_temporary_shop_ids", self._migration_quarantine_temporary_shop_ids),
            ]
            for version, handler in migrations:
                if self._is_applied(conn, version):
                    continue
                handler(conn)
                self._record(conn, version)
                applied.append(version)
            self._ensure_compat_columns(conn)
            conn.commit()
            return {"applied": applied}
        finally:
            conn.close()

    def _migration_runtime_schema(self, conn: sqlite3.Connection) -> None:
        root = Path(__file__).resolve().parents[2]
        for rel_path in (
            "deploy/sql/shop_onboarding_schema.sql",
            "deploy/sql/product_sync_jobs_schema.sql",
            "deploy/sql/knowledge_center_schema.sql",
        ):
            path = root / rel_path
            if path.exists():
                conn.executescript(path.read_text(encoding="utf-8"))

    def _migration_legacy_compat_columns(self, conn: sqlite3.Connection) -> None:
        self._ensure_compat_columns(conn)

    def _migration_shop_identity_pending_auth(self, conn: sqlite3.Connection) -> None:
        self._ensure_compat_columns(conn)

    def _migration_quarantine_temporary_shop_ids(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quarantined_temporary_shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_shop_row_id INTEGER,
                channel_id INTEGER,
                shop_id TEXT,
                shop_name TEXT,
                reason TEXT NOT NULL,
                quarantined_at TEXT NOT NULL
            )
            """
        )
        if not self._table_exists(conn, "shops"):
            return

        rows = conn.execute(
            "SELECT id, channel_id, shop_id, shop_name FROM shops WHERE shop_id LIKE 'remote-%'"
        ).fetchall()
        if not rows:
            return

        now = _now()
        for row in rows:
            conn.execute(
                """
                INSERT INTO quarantined_temporary_shops
                    (original_shop_row_id, channel_id, shop_id, shop_name, reason, quarantined_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (row["id"], row["channel_id"], row["shop_id"], row["shop_name"], "temporary_remote_shop_id", now),
            )

        ids = [int(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        if self._table_exists(conn, "accounts"):
            conn.execute(f"DELETE FROM accounts WHERE shop_id IN ({placeholders})", ids)
        if self._table_exists(conn, "product_knowledge"):
            conn.execute(f"DELETE FROM product_knowledge WHERE shop_id IN ({placeholders})", ids)
        if self._table_exists(conn, "shop_auth"):
            conn.execute("DELETE FROM shop_auth WHERE shop_id LIKE 'remote-%'")
        conn.execute(f"DELETE FROM shops WHERE id IN ({placeholders})", ids)

    def _ensure_migration_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

    def _is_applied(self, conn: sqlite3.Connection, version: str) -> bool:
        row = conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone()
        return row is not None

    def _record(self, conn: sqlite3.Connection, version: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, _now()),
        )

    def _ensure_compat_columns(self, conn: sqlite3.Connection) -> None:
        if self._table_exists(conn, "accounts"):
            self._add_missing_columns(conn, "accounts", {"status": "INTEGER"})
        if self._table_exists(conn, "conversations"):
            self._add_missing_columns(
                conn,
                "conversations",
                {
                    "session_id": "TEXT",
                    "status": "TEXT",
                    "created_at": "TEXT",
                    "updated_at": "TEXT",
                },
            )
        if self._table_exists(conn, "product_knowledge"):
            self._add_missing_columns(
                conn,
                "product_knowledge",
                {
                    "price_min": "TEXT",
                    "price_max": "TEXT",
                    "sold_quantity": "INTEGER",
                    "thumb_url": "TEXT",
                    "usage": "TEXT",
                    "ingredients": "TEXT",
                    "shelf_life": "TEXT",
                    "warnings": "TEXT",
                    "manual_notes": "TEXT",
                    "knowledge_status": "TEXT DEFAULT 'synced'",
                    "created_at": "TEXT",
                    "updated_at": "TEXT",
                },
            )
        if self._table_exists(conn, "shop_login_sessions"):
            self._add_missing_columns(
                conn,
                "shop_login_sessions",
                {
                    "runner_mode": "TEXT NOT NULL DEFAULT 'fake'",
                    "remote_browser_status": "TEXT",
                    "remote_browser_token": "TEXT",
                    "vnc_url": "TEXT",
                    "shop_identity_status": "TEXT NOT NULL DEFAULT 'unknown'",
                    "auth_status": "TEXT",
                    "cookie_encrypted": "TEXT",
                    "token_encrypted": "TEXT",
                },
            )
        if self._table_exists(conn, "shop_auth"):
            self._add_missing_columns(
                conn,
                "shop_auth",
                {
                    "shop_binding_status": "TEXT NOT NULL DEFAULT 'bound'",
                },
            )

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        return row is not None

    def _add_missing_columns(self, conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        for column, column_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}")
