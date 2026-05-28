from __future__ import annotations

import sqlite3
import uuid
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from web_api.services.pdd_login_runner import FakePddLoginRunner, LoginRunnerState, LoginRunnerSuccess, PddLoginRunnerProtocol, RealPddLoginRunner
from web_api.services.remote_browser_service import RemoteBrowserCheckResult, RemoteBrowserService
from web_api.services.schema_migration_service import SchemaMigrationService
from web_api.services.shop_auth_service import AuthSavePayload, ShopAuthService, build_safe_account_display, utc_now_iso
from web_api.services.shop_identity import assert_real_shop_id_bound, is_temporary_shop_id, shop_id_not_bound_error
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


TERMINAL_STATUSES = {"succeeded", "failed", "expired", "cancelled", "blocked_complex_verification", "shop_identity_pending"}


class ChecklistNotReadyError(Exception):
    def __init__(self, blocking_items: list[str]) -> None:
        super().__init__("checklist_not_ready")
        self.blocking_items = blocking_items


class ShopOnboardingService:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        runner: PddLoginRunnerProtocol | None = None,
        real_runner: PddLoginRunnerProtocol | None = None,
        auth_service: ShopAuthService | None = None,
        remote_browser_service: RemoteBrowserService | None = None,
        worker_status_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.runner = runner or FakePddLoginRunner()
        self.real_runner = real_runner or RealPddLoginRunner()
        self.auth_service = auth_service or ShopAuthService(self.db_path)
        self.remote_browser_service = remote_browser_service or RemoteBrowserService()
        self.worker_status_path = Path(worker_status_path) if worker_status_path else self._default_worker_status_path()

    def _default_worker_status_path(self) -> Path:
        configured = os.getenv("WORKER_STATUS_PATH")
        if configured:
            return Path(configured)
        try:
            from core import settings

            return Path(settings.worker_status_path())
        except Exception:
            return Path("temp/worker_status.json")

    def init_schema(self) -> None:
        SchemaMigrationService(self.db_path).migrate()

    def _ensure_optional_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(shop_login_sessions)").fetchall()}
        if "runner_mode" not in columns:
            conn.execute("ALTER TABLE shop_login_sessions ADD COLUMN runner_mode TEXT NOT NULL DEFAULT 'fake'")
        if "remote_browser_status" not in columns:
            conn.execute("ALTER TABLE shop_login_sessions ADD COLUMN remote_browser_status TEXT")
        if "remote_browser_token" not in columns:
            conn.execute("ALTER TABLE shop_login_sessions ADD COLUMN remote_browser_token TEXT")
        if "vnc_url" not in columns:
            conn.execute("ALTER TABLE shop_login_sessions ADD COLUMN vnc_url TEXT")

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _session_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["session_id"] = result.pop("id")
        result["needs_sms_code"] = bool(result.get("needs_sms_code"))
        result["needs_captcha"] = bool(result.get("needs_captcha"))
        result["remote_browser_available"] = result.get("runner_mode") == "remote_browser"
        result["vnc_url_ready"] = bool(result.get("vnc_url")) and result.get("status") == "waiting_user_verification"
        if not result["vnc_url_ready"]:
            result["vnc_url"] = None
        shop_id = str(result.get("shop_id") or "")
        identity_status = str(result.get("shop_identity_status") or "")
        result["real_shop_id_pending"] = bool(identity_status == "pending_real_shop_id" or is_temporary_shop_id(shop_id))
        return result

    def _runner_for_mode(self, runner_mode: str | None) -> PddLoginRunnerProtocol:
        if (runner_mode or "fake").lower() == "real":
            return self.real_runner
        return self.runner

    def _apply_state(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        state: LoginRunnerState,
        *,
        shop_id: str | None = None,
        completed: bool = False,
        cancelled: bool = False,
    ) -> None:
        now = utc_now_iso()
        conn.execute(
            """
            UPDATE shop_login_sessions
            SET status=?, step=?, needs_sms_code=?, needs_captcha=?, captcha_image_ref=?,
                error_summary=?, shop_id=COALESCE(?, shop_id), updated_at=?,
                completed_at=CASE WHEN ? THEN ? ELSE completed_at END,
                cancelled_at=CASE WHEN ? THEN ? ELSE cancelled_at END
            WHERE id=?
            """,
            (
                state.status,
                state.step,
                int(state.needs_sms_code),
                int(state.needs_captcha),
                state.captcha_image_ref,
                state.error_summary,
                shop_id,
                now,
                1 if completed else 0,
                now,
                1 if cancelled else 0,
                now,
                session_id,
            ),
        )

    def _save_success_and_apply_state(
        self,
        conn: sqlite3.Connection,
        session: dict[str, Any],
        state: LoginRunnerState,
        success: LoginRunnerSuccess,
    ) -> None:
        self.auth_service.save_auth(
            AuthSavePayload(
                shop_id=success.shop_id,
                shop_name=success.shop_name,
                platform=session["platform"],
                account_name=success.account_name,
                user_id=success.user_id,
                cookie_value=success.cookie_value,
                token_value=success.token_value,
            )
        )
        conn.execute(
            "UPDATE shop_login_sessions SET shop_identity_status='bound', auth_status='valid' WHERE id=?",
            (session["session_id"],),
        )
        self._apply_state(conn, session["session_id"], state, shop_id=success.shop_id, completed=True)

    def _save_pending_identity_auth(
        self,
        conn: sqlite3.Connection,
        session: dict[str, Any],
        result: RemoteBrowserCheckResult,
    ) -> None:
        encrypted_cookie = self.auth_service.cipher.encrypt(str(result.cookie_value or ""))
        encrypted_token = self.auth_service.cipher.encrypt(str(result.token_value or "")) if result.token_value else None
        now = utc_now_iso()
        conn.execute(
            """
            UPDATE shop_login_sessions
            SET status='shop_identity_pending',
                step='shop_identity_pending',
                shop_id=NULL,
                auth_status='valid',
                shop_identity_status='pending_real_shop_id',
                cookie_encrypted=?,
                token_encrypted=?,
                error_summary='授权成功，店铺身份待绑定',
                completed_at=?,
                updated_at=?
            WHERE id=?
            """,
            (encrypted_cookie, encrypted_token, now, now, session["session_id"]),
        )

    def create_session(
        self,
        platform: str,
        account_name: str,
        shop_name: str,
        password: str | None,
        operator: str = "local_admin",
        runner_mode: str = "fake",
    ) -> dict[str, Any]:
        if platform.lower() != "pdd":
            raise ValueError("unsupported_platform")
        runner_mode = (runner_mode or "fake").lower()
        if runner_mode not in {"fake", "real", "remote_browser"}:
            raise ValueError("unsupported_runner_mode")
        self.init_schema()
        session_id = f"login-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        safe_display = build_safe_account_display(account_name)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO shop_login_sessions
                    (id, platform, shop_name, account_name, safe_display, runner_mode, status, step, created_by,
                     created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 'created', 'created', ?, ?, ?, ?)
                """,
                (session_id, "pdd", shop_name, account_name, safe_display, runner_mode, operator, now, now, expires_at),
            )
            if runner_mode == "remote_browser":
                remote = self.remote_browser_service.create_session(session_id, "https://mms.pinduoduo.com/login")
                if remote.status == "ready":
                    state = LoginRunnerState(status="waiting_user_verification", step="waiting_user_verification")
                    conn.execute(
                        "UPDATE shop_login_sessions SET remote_browser_status=?, remote_browser_token=?, vnc_url=? WHERE id=?",
                        (remote.status, remote.access_token, remote.vnc_url, session_id),
                    )
                else:
                    state = LoginRunnerState(status="failed", step="remote_browser_start", error_summary=remote.error_summary)
                    conn.execute(
                        "UPDATE shop_login_sessions SET remote_browser_status=?, remote_browser_token=?, vnc_url=? WHERE id=?",
                        (remote.status, remote.access_token, remote.vnc_url, session_id),
                    )
                self._apply_state(conn, session_id, state)
            else:
                state = self._runner_for_mode(runner_mode).start_session(session_id, account_name, password, shop_name)
                self._apply_state(conn, session_id, state)
            conn.commit()
            return self.get_session(session_id, sync_runner=False)
        finally:
            conn.close()

    def get_session(self, session_id: str, sync_runner: bool = True) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM shop_login_sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            session = self._session_from_row(row)
            if sync_runner and session["runner_mode"] != "remote_browser" and session["status"] not in TERMINAL_STATUSES:
                state, success = self._runner_for_mode(session.get("runner_mode")).get_state(session_id)
                if success is not None:
                    self._save_success_and_apply_state(conn, session, state, success)
                else:
                    self._apply_state(conn, session_id, state)
                conn.commit()
                row = conn.execute("SELECT * FROM shop_login_sessions WHERE id=?", (session_id,)).fetchone()
                if row is None:
                    raise KeyError(session_id)
                session = self._session_from_row(row)
            return session
        finally:
            conn.close()

    def _ensure_session_can_continue(self, session: dict[str, Any]) -> None:
        if session["status"] in {"cancelled", "succeeded"}:
            raise ValueError(f"session_{session['status']}")
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            conn = self._connect()
            try:
                self._apply_state(conn, session["session_id"], LoginRunnerState(status="expired", step="expired", error_summary="session_expired"))
                conn.commit()
            finally:
                conn.close()
            raise TimeoutError("session_expired")

    def submit_sms_code(self, session_id: str, sms_code: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        self._ensure_session_can_continue(session)
        state, success = self._runner_for_mode(session.get("runner_mode")).submit_sms_code(session_id, sms_code)
        conn = self._connect()
        try:
            if success is not None:
                self._save_success_and_apply_state(conn, session, state, success)
            else:
                self._apply_state(conn, session_id, state)
            conn.commit()
            return self.get_session(session_id)
        finally:
            conn.close()

    def submit_captcha(self, session_id: str, captcha_code: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        self._ensure_session_can_continue(session)
        state, _ = self._runner_for_mode(session.get("runner_mode")).submit_captcha(session_id, captcha_code)
        if state.error_summary == "unsupported_captcha_flow":
            raise NotImplementedError("unsupported_captcha_flow")
        conn = self._connect()
        try:
            self._apply_state(conn, session_id, state)
            conn.commit()
            return self.get_session(session_id)
        finally:
            conn.close()

    def cancel_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session["status"] == "cancelled":
            return session
        if session.get("runner_mode") == "remote_browser":
            self.remote_browser_service.close_session(session_id)
            state = LoginRunnerState(status="cancelled", step="cancelled")
        else:
            state = self._runner_for_mode(session.get("runner_mode")).cancel(session_id)
        conn = self._connect()
        try:
            self._apply_state(conn, session_id, state, cancelled=True)
            conn.commit()
            return self.get_session(session_id)
        finally:
            conn.close()

    def get_auth_status(self, shop_id: str) -> dict[str, object]:
        return self.auth_service.get_auth_status(shop_id)

    def get_onboarding_checklist(self, shop_id: str) -> dict[str, Any]:
        if is_temporary_shop_id(shop_id):
            blocked = self._check_item(
                "real_shop_identity_bound",
                "真实店铺身份已绑定",
                "failed",
                True,
                "授权已完成，但尚未绑定真实 PDD 店铺 ID，不能继续接入验收或启用 AI。",
            )
            return {
                "shop_id": shop_id,
                "ready_for_ai": False,
                "blocking_items": ["real_shop_identity_bound"],
                "items": [blocked],
            }
        self.init_schema()
        items = [
            self._check_auth_valid(shop_id),
            self._check_product_sync_completed(shop_id),
            self._check_coverage_ready(shop_id),
            self._check_knowledge_active(shop_id),
            self._check_no_send_validated(shop_id),
            self._check_provider_status(shop_id),
            self.get_worker_status(shop_id, as_checklist_item=True),
            self._check_human_lock_management(shop_id),
        ]
        blocking_items = [item["key"] for item in items if item["required"] and item["status"] != "passed"]
        return {
            "shop_id": shop_id,
            "ready_for_ai": not blocking_items,
            "blocking_items": blocking_items,
            "items": items,
        }

    def mark_no_send_validation_passed(self, shop_id: str, operator: str = "local_admin", summary: str = "") -> dict[str, Any]:
        self.init_schema()
        now = utc_now_iso()
        run_id = f"oval-{uuid.uuid4().hex[:12]}"
        summary_payload = {"summary": summary or "manual_no_send_validation_passed"}
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO onboarding_validation_runs
                    (id, shop_id, status, mode, passed_count, failed_count, summary_json, created_by, tested_at, created_at)
                VALUES (?, ?, 'passed', 'no_send', 1, 0, ?, ?, ?, ?)
                """,
                (run_id, shop_id, json.dumps(summary_payload, ensure_ascii=False), operator, now, now),
            )
            self._record_audit(
                conn,
                shop_id=shop_id,
                action="onboarding_validation_mark_passed",
                operator=operator,
                result="succeeded",
                detail={"mode": "no_send"},
            )
            conn.commit()
            return {
                "id": run_id,
                "shop_id": shop_id,
                "status": "passed",
                "mode": "no_send",
                "passed_count": 1,
                "failed_count": 0,
                "tested_at": now,
                "created_by": operator,
                "summary": summary or "manual_no_send_validation_passed",
            }
        finally:
            conn.close()

    def get_ai_status(self, shop_id: str) -> dict[str, Any]:
        self.init_schema()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM shop_ai_settings WHERE shop_id=?", (shop_id,)).fetchone()
            if row is None:
                return {
                    "shop_id": shop_id,
                    "ai_enabled": False,
                    "enabled_at": None,
                    "enabled_by": None,
                    "disabled_at": None,
                    "disabled_by": None,
                    "last_change_reason": None,
                    "override_enabled": False,
                    "override_reason": None,
                }
            result = dict(row)
            result["ai_enabled"] = bool(result.get("ai_enabled"))
            result["override_enabled"] = bool(result.get("override_enabled"))
            return result
        finally:
            conn.close()

    def enable_ai(
        self,
        shop_id: str,
        *,
        operator: str = "local_admin",
        confirm: bool = False,
        override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        assert_real_shop_id_bound(shop_id)
        if not confirm:
            raise ValueError("confirm_required")
        checklist = self.get_onboarding_checklist(shop_id)
        if not checklist["ready_for_ai"]:
            if not override:
                raise ChecklistNotReadyError(list(checklist["blocking_items"]))
            if not (override_reason or "").strip():
                raise ValueError("override_reason_required")
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO shop_ai_settings
                    (shop_id, ai_enabled, enabled_at, enabled_by, disabled_at, disabled_by, last_change_reason,
                     override_enabled, override_reason, created_at, updated_at)
                VALUES (?, 1, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(shop_id) DO UPDATE SET
                    ai_enabled=1,
                    enabled_at=excluded.enabled_at,
                    enabled_by=excluded.enabled_by,
                    disabled_at=NULL,
                    disabled_by=NULL,
                    last_change_reason=excluded.last_change_reason,
                    override_enabled=excluded.override_enabled,
                    override_reason=excluded.override_reason,
                    updated_at=excluded.updated_at
                """,
                (
                    shop_id,
                    now,
                    operator,
                    override_reason or "checklist_ready",
                    int(bool(override)),
                    override_reason,
                    now,
                    now,
                ),
            )
            self._record_audit(
                conn,
                shop_id=shop_id,
                action="enable_ai_override" if override else "enable_ai",
                operator=operator,
                result="succeeded",
                detail={"override": bool(override), "blocking_items": checklist["blocking_items"]},
            )
            conn.commit()
            return self.get_ai_status(shop_id)
        finally:
            conn.close()

    def disable_ai(self, shop_id: str, *, operator: str = "local_admin", reason: str = "manual_disable") -> dict[str, Any]:
        self.init_schema()
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO shop_ai_settings
                    (shop_id, ai_enabled, enabled_at, enabled_by, disabled_at, disabled_by, last_change_reason,
                     override_enabled, override_reason, created_at, updated_at)
                VALUES (?, 0, NULL, NULL, ?, ?, ?, 0, NULL, ?, ?)
                ON CONFLICT(shop_id) DO UPDATE SET
                    ai_enabled=0,
                    disabled_at=excluded.disabled_at,
                    disabled_by=excluded.disabled_by,
                    last_change_reason=excluded.last_change_reason,
                    updated_at=excluded.updated_at
                """,
                (shop_id, now, operator, reason, now, now),
            )
            self._record_audit(
                conn,
                shop_id=shop_id,
                action="disable_ai",
                operator=operator,
                result="succeeded",
                detail={"reason": reason},
            )
            conn.commit()
            return self.get_ai_status(shop_id)
        finally:
            conn.close()

    def _check_auth_valid(self, shop_id: str) -> dict[str, Any]:
        try:
            auth = self.get_auth_status(shop_id)
            status = str(auth.get("auth_status") or "")
            if status in {"auth_valid", "valid"}:
                return {
                    "key": "auth_valid",
                    "label": "店铺授权有效",
                    "status": "passed",
                    "required": True,
                    "summary": "shop_auth 有效",
                }
            return {
                "key": "auth_valid",
                "label": "店铺授权有效",
                "status": "failed",
                "required": True,
                "summary": f"授权状态不可用：{status or 'missing'}",
            }
        except KeyError:
            return {
                "key": "auth_valid",
                "label": "店铺授权有效",
                "status": "failed",
                "required": True,
                "summary": "尚未完成店铺授权",
            }

    def _check_product_sync_completed(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            if not self._table_exists(conn, "product_sync_jobs"):
                return self._check_item("product_sync_completed", "商品同步完成", "failed", True, "尚未创建商品同步任务")
            row = conn.execute(
                "SELECT status, total_count, succeeded_count, failed_count FROM product_sync_jobs WHERE shop_id=? ORDER BY updated_at DESC LIMIT 1",
                (shop_id,),
            ).fetchone()
            total = self._product_knowledge_total(conn, shop_id)
            if row is None or total <= 0:
                return self._check_item("product_sync_completed", "商品同步完成", "failed", True, "尚未完成商品同步")
            if row["status"] in {"succeeded", "partial_failed"}:
                return self._check_item(
                    "product_sync_completed",
                    "商品同步完成",
                    "passed",
                    True,
                    f"最近同步 {row['status']}，本地商品数 {total}",
                )
            return self._check_item("product_sync_completed", "商品同步完成", "failed", True, f"最近同步状态 {row['status']}")
        finally:
            conn.close()

    def _check_coverage_ready(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            total = self._product_knowledge_total(conn, shop_id)
            if total <= 0:
                return self._check_item("coverage_ready", "商品知识覆盖率达标", "warning", False, "暂无商品知识覆盖率")
            internal_shop_id = self._internal_shop_id(conn, shop_id)
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN COALESCE(price, price_min, price_max, '') != '' THEN 1 ELSE 0 END) AS has_price,
                    SUM(CASE WHEN COALESCE(specifications, '') != '' THEN 1 ELSE 0 END) AS has_specs
                FROM product_knowledge WHERE shop_id=?
                """,
                (internal_shop_id,),
            ).fetchone()
            has_price = int(row["has_price"] or 0)
            has_specs = int(row["has_specs"] or 0)
            if has_price > 0 and has_specs > 0:
                return self._check_item("coverage_ready", "商品知识覆盖率达标", "passed", False, f"价格覆盖 {has_price}，规格覆盖 {has_specs}")
            return self._check_item("coverage_ready", "商品知识覆盖率达标", "warning", False, f"价格覆盖 {has_price}，规格覆盖 {has_specs}")
        finally:
            conn.close()

    def _check_knowledge_active(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            if not self._table_exists(conn, "knowledge_versions"):
                return self._check_item("knowledge_active", "知识版本已生效", "warning", False, "Knowledge Center 版本表尚未初始化")
            count = conn.execute(
                """
                SELECT COUNT(*) FROM knowledge_versions
                WHERE shop_id=? AND (is_active=1 OR status='active')
                """,
                (shop_id,),
            ).fetchone()[0]
            if int(count or 0) > 0:
                return self._check_item("knowledge_active", "知识版本已生效", "passed", False, f"已有 {count} 个 active version")
            return self._check_item("knowledge_active", "知识版本已生效", "warning", False, "暂未发现 active version，可先使用商品原始知识 fallback")
        except sqlite3.OperationalError:
            return self._check_item("knowledge_active", "知识版本已生效", "warning", False, "知识版本状态暂不可读")
        finally:
            conn.close()

    def _check_no_send_validated(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT status, tested_at FROM onboarding_validation_runs WHERE shop_id=? ORDER BY tested_at DESC LIMIT 1",
                (shop_id,),
            ).fetchone()
            if row is not None and row["status"] == "passed":
                return self._check_item("no_send_validated", "试聊验证完成", "passed", True, f"最近通过时间 {row['tested_at']}")
            return self._check_item("no_send_validated", "试聊验证完成", "failed", True, "尚未完成 no-send 验收")
        finally:
            conn.close()

    def _check_provider_status(self, shop_id: str) -> dict[str, Any]:
        return self._check_item(
            "provider_status",
            "服务配置可用",
            "passed",
            True,
            "默认检查不调用 LLM/Ollama/pgvector；真实服务状态请查看服务状态页",
        )

    def _check_human_lock_management(self, shop_id: str) -> dict[str, Any]:
        return self._check_item("human_lock_management", "人工锁管理可用", "passed", True, "Human Locks API 已接入，解锁按 shop_id 隔离")

    def _load_worker_status_payload(self) -> dict[str, Any] | None:
        path = self.worker_status_path
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"computed_status": "invalid", "worker_status": "invalid", "status_file_path": str(path)}
        if not isinstance(payload, dict):
            return {"computed_status": "invalid", "worker_status": "invalid", "status_file_path": str(path)}
        updated_at = payload.get("updated_at")
        computed_status = "running"
        try:
            if updated_at is None or time.time() - float(updated_at) > 60:
                computed_status = "stale"
        except (TypeError, ValueError):
            computed_status = "stale"
        if payload.get("shutdown_completed_at"):
            computed_status = "stopped"
        payload["computed_status"] = computed_status
        payload["worker_status"] = computed_status
        return payload

    def _check_auth_valid(self, shop_id: str) -> dict[str, Any]:
        try:
            auth = self.get_auth_status(shop_id)
            status = str(auth.get("auth_status") or "")
            if status in {"auth_valid", "valid"}:
                return self._check_item("auth_valid", "店铺授权有效", "passed", True, "shop_auth 有效")
            return self._check_item("auth_valid", "店铺授权有效", "failed", True, f"授权状态不可用：{status or 'missing'}")
        except KeyError:
            return self._check_item("auth_valid", "店铺授权有效", "failed", True, "尚未完成店铺授权")

    def _check_product_sync_completed(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            if not self._table_exists(conn, "product_sync_jobs"):
                return self._check_item("product_sync_completed", "商品同步完成", "failed", True, "尚未创建商品同步任务")
            row = conn.execute(
                "SELECT status, total_count, succeeded_count, failed_count FROM product_sync_jobs WHERE shop_id=? ORDER BY updated_at DESC LIMIT 1",
                (shop_id,),
            ).fetchone()
            total = self._product_knowledge_total(conn, shop_id)
            if row is None or total <= 0:
                return self._check_item("product_sync_completed", "商品同步完成", "failed", True, "尚未完成商品同步")
            if row["status"] in {"succeeded", "partial_failed"}:
                return self._check_item(
                    "product_sync_completed",
                    "商品同步完成",
                    "passed",
                    True,
                    f"最近同步 {row['status']}，本地商品数 {total}",
                )
            return self._check_item("product_sync_completed", "商品同步完成", "failed", True, f"最近同步状态 {row['status']}")
        finally:
            conn.close()

    def _check_coverage_ready(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            total = self._product_knowledge_total(conn, shop_id)
            if total <= 0:
                return self._check_item("coverage_ready", "商品知识覆盖率达标", "warning", False, "暂无商品知识覆盖率")
            internal_shop_id = self._internal_shop_id(conn, shop_id)
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN COALESCE(price, price_min, price_max, '') != '' THEN 1 ELSE 0 END) AS has_price,
                    SUM(CASE WHEN COALESCE(specifications, '') != '' THEN 1 ELSE 0 END) AS has_specs
                FROM product_knowledge WHERE shop_id=?
                """,
                (internal_shop_id,),
            ).fetchone()
            has_price = int(row["has_price"] or 0)
            has_specs = int(row["has_specs"] or 0)
            status = "passed" if has_price > 0 and has_specs > 0 else "warning"
            return self._check_item("coverage_ready", "商品知识覆盖率达标", status, False, f"价格覆盖 {has_price}，规格覆盖 {has_specs}")
        finally:
            conn.close()

    def _check_knowledge_active(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            if not self._table_exists(conn, "knowledge_versions"):
                return self._check_item("knowledge_active", "知识版本已生效", "warning", False, "Knowledge Center 版本表尚未初始化")
            count = conn.execute(
                """
                SELECT COUNT(*) FROM knowledge_versions
                WHERE shop_id=? AND (is_active=1 OR status='active')
                """,
                (shop_id,),
            ).fetchone()[0]
            if int(count or 0) > 0:
                return self._check_item("knowledge_active", "知识版本已生效", "passed", False, f"已有 {count} 个 active version")
            return self._check_item("knowledge_active", "知识版本已生效", "warning", False, "暂未发现 active version，可先使用商品原始知识 fallback")
        except sqlite3.OperationalError:
            return self._check_item("knowledge_active", "知识版本已生效", "warning", False, "知识版本状态暂不可读")
        finally:
            conn.close()

    def _check_no_send_validated(self, shop_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT status, tested_at FROM onboarding_validation_runs WHERE shop_id=? ORDER BY tested_at DESC LIMIT 1",
                (shop_id,),
            ).fetchone()
            if row is not None and row["status"] == "passed":
                return self._check_item("no_send_validated", "试聊验证完成", "passed", True, f"最近通过时间 {row['tested_at']}")
            return self._check_item("no_send_validated", "试聊验证完成", "failed", True, "尚未完成 no-send 验收")
        finally:
            conn.close()

    def _check_provider_status(self, shop_id: str) -> dict[str, Any]:
        return self._check_item(
            "provider_status",
            "服务配置可用",
            "passed",
            True,
            "默认检查不调用 LLM/Ollama/pgvector；真实服务状态请查看服务状态页",
        )

    def _check_human_lock_management(self, shop_id: str) -> dict[str, Any]:
        return self._check_item("human_lock_management", "人工锁管理可用", "passed", True, "Human Locks API 已接入，解锁按 shop_id 隔离")

    def _check_item(self, key: str, label: str, status: str, required: bool, summary: str) -> dict[str, Any]:
        return {"key": key, "label": label, "status": status, "required": required, "summary": summary}

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        return row is not None

    def _internal_shop_id(self, conn: sqlite3.Connection, platform_shop_id: str) -> int | None:
        if not self._table_exists(conn, "shops") or not self._table_exists(conn, "channels"):
            return None
        row = conn.execute(
            """
            SELECT shops.id FROM shops
            JOIN channels ON channels.id = shops.channel_id
            WHERE shops.shop_id=? AND channels.channel_name='pinduoduo'
            """,
            (platform_shop_id,),
        ).fetchone()
        return int(row["id"]) if row else None

    def _product_knowledge_total(self, conn: sqlite3.Connection, platform_shop_id: str) -> int:
        if not self._table_exists(conn, "product_knowledge"):
            return 0
        internal_shop_id = self._internal_shop_id(conn, platform_shop_id)
        if internal_shop_id is None:
            return 0
        row = conn.execute("SELECT COUNT(*) FROM product_knowledge WHERE shop_id=?", (internal_shop_id,)).fetchone()
        return int(row[0] or 0)

    def _record_audit(
        self,
        conn: sqlite3.Connection,
        *,
        shop_id: str,
        action: str,
        operator: str,
        result: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO web_admin_audit_log (id, shop_id, action, operator, result, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"audit-{uuid.uuid4().hex[:12]}",
                shop_id,
                action,
                operator,
                result,
                json.dumps(detail or {}, ensure_ascii=False),
                utc_now_iso(),
            ),
        )

    def check_remote_browser_login(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        self._ensure_session_can_continue(session)
        if session.get("runner_mode") != "remote_browser":
            raise ValueError("not_remote_browser_session")
        result = self.remote_browser_service.check_login_success(session_id)
        conn = self._connect()
        try:
            if result.status == "succeeded":
                if not result.cookie_value:
                    self._apply_state(
                        conn,
                        session_id,
                        LoginRunnerState(status="failed", step="remote_browser_check", error_summary="auth_cookie_missing"),
                    )
                    conn.commit()
                    return self.get_session(session_id, sync_runner=False)
                shop_id = str(result.shop_id or "")
                if not shop_id or is_temporary_shop_id(shop_id):
                    self._save_pending_identity_auth(conn, session, result)
                    self.remote_browser_service.close_session(session_id)
                    conn.execute(
                        "UPDATE shop_login_sessions SET remote_browser_status=? WHERE id=?",
                        ("closed", session_id),
                    )
                    conn.commit()
                    return self.get_session(session_id, sync_runner=False)
                account_name = str(result.account_name or session.get("account_name") or "")
                success = LoginRunnerSuccess(
                    shop_id=shop_id,
                    shop_name=str(result.shop_name or session.get("shop_name") or shop_id),
                    user_id=str(result.user_id or shop_id),
                    account_name=account_name,
                    cookie_value=str(result.cookie_value or ""),
                    token_value=result.token_value,
                )
                self._save_success_and_apply_state(conn, session, LoginRunnerState(status="succeeded", step="succeeded"), success)
                self.remote_browser_service.close_session(session_id)
                conn.execute(
                    "UPDATE shop_login_sessions SET remote_browser_status=? WHERE id=?",
                    ("closed", session_id),
                )
            elif result.status == "still_waiting_user_verification":
                self._apply_state(
                    conn,
                    session_id,
                    LoginRunnerState(status="waiting_user_verification", step="waiting_user_verification"),
                )
            else:
                self._apply_state(
                    conn,
                    session_id,
                    LoginRunnerState(status="failed", step="remote_browser_check", error_summary=result.error_summary or "remote_browser_check_failed"),
                )
            conn.commit()
            return self.get_session(session_id, sync_runner=False)
        finally:
            conn.close()

    def _worker_consistency_current(self, *, ai_enabled: bool, shop_status: str, websocket_status: str) -> dict[str, Any]:
        if shop_status in {"missing", "invalid", "stale", "unknown"}:
            return {
                "consistency_status": f"worker_status_{shop_status}",
                "attention_required": True,
                "recommended_action": "Worker status is unavailable or stale. Check the worker process and status file.",
            }
        if ai_enabled and shop_status == "running":
            return {
                "consistency_status": "ai_enabled_worker_running",
                "attention_required": False,
                "recommended_action": None,
            }
        if ai_enabled:
            return {
                "consistency_status": "ai_enabled_worker_not_running",
                "attention_required": True,
                "recommended_action": "AI is enabled, but this shop is not running in the worker. Start or restart the worker after review.",
            }
        if shop_status == "running" or websocket_status == "connected":
            return {
                "consistency_status": "ai_disabled_worker_still_running",
                "attention_required": True,
                "recommended_action": "AI is disabled, but the worker still shows this shop as running. Wait for the worker gate check or restart the worker.",
            }
        return {
            "consistency_status": "ai_disabled_worker_stopped",
            "attention_required": False,
            "recommended_action": None,
        }

    def get_worker_status(self, shop_id: str, *, as_checklist_item: bool = False) -> dict[str, Any]:
        ai_enabled = bool(self.get_ai_status(shop_id).get("ai_enabled"))
        payload = self._load_worker_status_payload()
        if not payload:
            summary = "Worker status file is missing. Web Admin only shows status and does not start or stop workers."
            consistency = self._worker_consistency_current(
                ai_enabled=ai_enabled,
                shop_status="unknown",
                websocket_status="unknown",
            )
            if as_checklist_item:
                return self._check_item("worker_status", "Worker 状态", "warning", False, summary)
            return {
                "shop_id": shop_id,
                "status": "unknown",
                "process_id": None,
                "last_seen_at": None,
                "websocket_status": "unknown",
                "summary": summary,
                "ai_enabled": ai_enabled,
                **consistency,
            }

        status = str(payload.get("computed_status") or payload.get("worker_status") or payload.get("worker_state") or "unknown")
        pid = payload.get("pid")
        updated_at = payload.get("updated_at")
        accounts = [item for item in payload.get("accounts", []) if str(item.get("shop_id") or "") == str(shop_id)]
        connections = [item for item in payload.get("connections", []) if str(item.get("shop_id") or "") == str(shop_id)]
        running = any(str(item.get("state") or "").lower() == "running" for item in accounts)
        connected = any(str(item.get("state") or "").lower() == "connected" for item in connections)
        if status == "running" and running:
            shop_status = "running"
        elif status in {"missing", "invalid", "stale", "stopped"}:
            shop_status = status
        else:
            shop_status = "stopped"
        websocket_status = "connected" if connected else "unknown"
        user_ids = [str(item.get("user_id") or "") for item in accounts if item.get("user_id")]
        summary = "Web Admin only shows worker status and does not start or stop workers."
        if user_ids:
            summary += f" Matched account(s): {', '.join(user_ids[:3])}."
        elif shop_status == "stopped":
            summary += " This shop is not running in the worker status file."
        consistency = self._worker_consistency_current(
            ai_enabled=ai_enabled,
            shop_status=shop_status,
            websocket_status=websocket_status,
        )

        if as_checklist_item:
            item_status = "warning" if consistency["attention_required"] else "passed"
            return self._check_item("worker_status", "Worker 状态", item_status, False, summary)
        return {
            "shop_id": shop_id,
            "status": shop_status,
            "process_id": pid,
            "last_seen_at": updated_at,
            "websocket_status": websocket_status,
            "summary": summary,
            "ai_enabled": ai_enabled,
            **consistency,
        }
