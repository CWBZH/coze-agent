from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class RemoteBrowserSession:
    login_session_id: str
    status: str
    access_token: str
    vnc_url: str | None = None
    error_summary: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    closed_at: str | None = None


@dataclass
class RemoteBrowserCheckResult:
    status: str
    shop_id: str | None = None
    shop_name: str | None = None
    user_id: str | None = None
    account_name: str | None = None
    cookie_value: str | None = None
    token_value: str | None = None
    error_summary: str | None = None


class RemoteBrowserService:
    """Tokenized remote browser session manager.

    This service provides the Web API contract for noVNC-style login sessions.
    In environments without noVNC/websockify/Xvfb, sessions fail closed with a
    sanitized missing dependency status instead of exposing an unauthenticated
    browser endpoint.
    """

    def __init__(self, *, base_url: str | None = None, session_ttl_seconds: int = 600) -> None:
        self.base_url = (base_url or os.environ.get("WEB_NOVNC_BASE_URL") or "").rstrip("/")
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, RemoteBrowserSession] = {}

    def create_session(self, login_session_id: str, login_url: str) -> RemoteBrowserSession:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(24)
        if not self.base_url:
            session = RemoteBrowserSession(
                login_session_id=login_session_id,
                status="failed",
                access_token=token,
                error_summary="missing_dependency:novnc_base_url",
                created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
            )
            self._sessions[login_session_id] = session
            return session

        vnc_url = f"{self.base_url}/vnc.html?session={login_session_id}&token={token}"
        session = RemoteBrowserSession(
            login_session_id=login_session_id,
            status="ready",
            access_token=token,
            vnc_url=vnc_url,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
        )
        self._sessions[login_session_id] = session
        return session

    def get_session(self, login_session_id: str) -> RemoteBrowserSession | None:
        return self._sessions.get(login_session_id)

    def check_login_success(self, login_session_id: str) -> RemoteBrowserCheckResult:
        session = self.get_session(login_session_id)
        if session is None:
            return RemoteBrowserCheckResult(status="failed", error_summary="remote_browser_session_not_found")
        if session.status == "failed":
            return RemoteBrowserCheckResult(status="failed", error_summary=session.error_summary)
        return RemoteBrowserCheckResult(status="still_waiting_user_verification")

    def close_session(self, login_session_id: str) -> None:
        session = self._sessions.get(login_session_id)
        if session is None:
            return
        session.status = "closed"
        session.closed_at = datetime.now(UTC).isoformat()

