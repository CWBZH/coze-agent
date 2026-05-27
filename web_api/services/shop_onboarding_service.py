from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from web_api.services.pdd_login_runner import FakePddLoginRunner, LoginRunnerState, LoginRunnerSuccess, PddLoginRunnerProtocol, RealPddLoginRunner
from web_api.services.remote_browser_service import RemoteBrowserCheckResult, RemoteBrowserService
from web_api.services.shop_auth_service import AuthSavePayload, ShopAuthService, build_safe_account_display, utc_now_iso
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


TERMINAL_STATUSES = {"succeeded", "failed", "expired", "cancelled", "blocked_complex_verification"}


class ShopOnboardingService:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        runner: PddLoginRunnerProtocol | None = None,
        real_runner: PddLoginRunnerProtocol | None = None,
        auth_service: ShopAuthService | None = None,
        remote_browser_service: RemoteBrowserService | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.runner = runner or FakePddLoginRunner()
        self.real_runner = real_runner or RealPddLoginRunner()
        self.auth_service = auth_service or ShopAuthService(self.db_path)
        self.remote_browser_service = remote_browser_service or RemoteBrowserService()

    def init_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "deploy" / "sql" / "shop_onboarding_schema.sql"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            self._ensure_optional_columns(conn)
            conn.commit()
        finally:
            conn.close()

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
        self._apply_state(conn, session["session_id"], state, shop_id=success.shop_id, completed=True)

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
        expires_at = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
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
        if expires_at < datetime.now(UTC):
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

    def check_remote_browser_login(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        self._ensure_session_can_continue(session)
        if session.get("runner_mode") != "remote_browser":
            raise ValueError("not_remote_browser_session")
        result = self.remote_browser_service.check_login_success(session_id)
        conn = self._connect()
        try:
            if result.status == "succeeded":
                success = LoginRunnerSuccess(
                    shop_id=str(result.shop_id),
                    shop_name=str(result.shop_name or result.shop_id),
                    user_id=str(result.user_id),
                    account_name=str(result.account_name or session.get("account_name") or ""),
                    cookie_value=str(result.cookie_value),
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
