from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from web_api.errors import ApiError
from web_api.services.schema_migration_service import SchemaMigrationService
from web_api.services.shop_auth_service import ShopAuthService, utc_now_iso
from web_api.services.shop_identity import assert_real_shop_id_bound
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


class WorkerControlService:
    """Persist worker lifecycle intent for an external Worker Manager."""

    VALID_COMMANDS = {"start", "stop", "restart"}

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, auth_service: ShopAuthService | None = None) -> None:
        self.db_path = Path(db_path)
        self.auth_service = auth_service or ShopAuthService(self.db_path)

    def init_schema(self) -> None:
        SchemaMigrationService(self.db_path).migrate()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def request_start(self, shop_id: str, *, operator: str = "local_admin", reason: str = "") -> dict[str, Any]:
        return self._request_command(shop_id, "start", operator=operator, reason=reason)

    def request_stop(self, shop_id: str, *, operator: str = "local_admin", reason: str = "") -> dict[str, Any]:
        return self._request_command(shop_id, "stop", operator=operator, reason=reason)

    def request_restart(self, shop_id: str, *, operator: str = "local_admin", reason: str = "") -> dict[str, Any]:
        return self._request_command(shop_id, "restart", operator=operator, reason=reason)

    def list_commands(self, shop_id: str, *, limit: int = 20) -> dict[str, Any]:
        self.init_schema()
        safe_limit = max(1, min(int(limit or 20), 100))
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, shop_id, command, status, requested_by, requested_at, trace_id
                FROM worker_control_commands
                WHERE shop_id=?
                ORDER BY requested_at DESC
                LIMIT ?
                """,
                (shop_id, safe_limit),
            ).fetchall()
            items = [self._row_to_command(row, self._desired_state_for_command(row["command"])) for row in rows]
            return {"items": items, "total": len(items)}
        finally:
            conn.close()

    def list_events(self, *, shop_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        self.init_schema()
        safe_limit = max(1, min(int(limit or 50), 200))
        conn = self._connect()
        try:
            if shop_id:
                rows = conn.execute(
                    """
                    SELECT id, shop_id, event_type, status, summary, metadata_json, created_at, trace_id
                    FROM worker_events
                    WHERE shop_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (shop_id, safe_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, shop_id, event_type, status, summary, metadata_json, created_at, trace_id
                    FROM worker_events
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()
            items = [dict(row) for row in rows]
            return {"items": items, "total": len(items)}
        finally:
            conn.close()

    def _request_command(self, shop_id: str, command: str, *, operator: str, reason: str) -> dict[str, Any]:
        self.init_schema()
        if command not in self.VALID_COMMANDS:
            raise ApiError(
                error_type="INVALID_WORKER_COMMAND",
                error_summary=f"Unsupported worker command: {command}",
                status_code=400,
                retryable=False,
                next_action="Use start, stop, or restart.",
            )
        self._validate_shop_for_command(shop_id, command)

        now = utc_now_iso()
        command_id = f"worker-cmd-{uuid.uuid4().hex[:16]}"
        trace_id = f"workerctl-{uuid.uuid4().hex[:16]}"
        desired_state = self._desired_state_for_command(command)
        summary = self._summary_for_command(command)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO worker_control_commands
                    (id, shop_id, command, status, requested_by, requested_at, trace_id)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (command_id, shop_id, command, operator, now, trace_id),
            )
            conn.execute(
                """
                INSERT INTO shop_worker_desired_state (shop_id, desired_state, updated_by, updated_at, reason)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(shop_id) DO UPDATE SET
                    desired_state=excluded.desired_state,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at,
                    reason=excluded.reason
                """,
                (shop_id, desired_state, operator, now, reason or summary),
            )
            self._record_event(
                conn,
                shop_id=shop_id,
                event_type=f"worker_{command}_requested",
                status="pending",
                summary=summary,
                metadata={"operator": operator, "command_id": command_id, "desired_state": desired_state},
                trace_id=trace_id,
            )
            conn.commit()
            return {
                "id": command_id,
                "shop_id": shop_id,
                "command": command,
                "status": "pending",
                "requested_by": operator,
                "requested_at": now,
                "trace_id": trace_id,
                "desired_state": desired_state,
                "summary": summary,
            }
        finally:
            conn.close()

    def _validate_shop_for_command(self, shop_id: str, command: str) -> None:
        assert_real_shop_id_bound(shop_id)
        if command == "stop":
            return
        try:
            auth = self.auth_service.get_auth_status(shop_id)
        except KeyError as exc:
            raise ApiError(
                error_type="AUTH_REQUIRED",
                error_summary="Worker cannot start before valid shop authorization is available.",
                status_code=409,
                retryable=True,
                next_action="Complete remote browser authorization for this shop first.",
            ) from exc
        if str(auth.get("auth_status") or "") not in {"valid", "auth_valid"}:
            raise ApiError(
                error_type="AUTH_REQUIRED",
                error_summary="Worker cannot start because shop authorization is not valid.",
                status_code=409,
                retryable=True,
                next_action="Re-authorize the shop with the remote browser flow.",
            )

    def _record_event(
        self,
        conn: sqlite3.Connection,
        *,
        shop_id: str,
        event_type: str,
        status: str,
        summary: str,
        metadata: dict[str, Any],
        trace_id: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO worker_events
                (id, shop_id, event_type, status, summary, metadata_json, created_at, trace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"worker-event-{uuid.uuid4().hex[:16]}",
                shop_id,
                event_type,
                status,
                summary,
                json.dumps(metadata, ensure_ascii=False),
                utc_now_iso(),
                trace_id,
            ),
        )

    @staticmethod
    def _desired_state_for_command(command: str) -> str:
        if command == "stop":
            return "stopped"
        return "running"

    @staticmethod
    def _summary_for_command(command: str) -> str:
        if command == "start":
            return "Worker start requested. Web API recorded desired state only; Worker Manager must execute it."
        if command == "stop":
            return "Worker stop requested. Web API recorded desired state only; Worker Manager must execute it."
        return "Worker restart requested. Web API recorded desired state only; Worker Manager must execute it."

    @classmethod
    def _row_to_command(cls, row: sqlite3.Row, desired_state: str) -> dict[str, Any]:
        return {
            "id": row["id"],
            "shop_id": row["shop_id"],
            "command": row["command"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "requested_at": row["requested_at"],
            "trace_id": row["trace_id"],
            "desired_state": desired_state,
            "summary": cls._summary_for_command(str(row["command"])),
        }
