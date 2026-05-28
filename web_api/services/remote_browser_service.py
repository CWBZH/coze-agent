from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


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

    The service controls the Web API contract for noVNC login sessions and can
    detect login completion through Chrome DevTools Protocol. It never returns
    or logs raw cookies; the caller is responsible for encrypting persisted auth.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        cdp_url: str | None = None,
        session_ttl_seconds: int = 1800,
    ) -> None:
        self.base_url = (base_url or os.environ.get("WEB_NOVNC_BASE_URL") or "").rstrip("/")
        self.cdp_url = (cdp_url or os.environ.get("WEB_REMOTE_BROWSER_CDP_URL") or "http://127.0.0.1:9222").rstrip("/")
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, RemoteBrowserSession] = {}

    def create_session(self, login_session_id: str, login_url: str) -> RemoteBrowserSession:
        now = datetime.now(timezone.utc)
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
        if self._is_expired(session):
            self.close_session(login_session_id)
            return RemoteBrowserCheckResult(status="failed", error_summary="session_expired")

        try:
            pages = self._get_cdp_pages()
            urls = [str(page.get("url") or "") for page in pages]
            cookie_value = self._read_pdd_cookies_from_cdp(pages)
        except Exception:
            return RemoteBrowserCheckResult(status="still_waiting_user_verification")

        pdd_urls = [url for url in urls if "pinduoduo.com" in url or "yangkeduo.com" in url]
        login_urls = [url for url in pdd_urls if "login" in url.lower()]
        if cookie_value and pdd_urls and not login_urls:
            session_key = login_session_id.replace("login-", "")
            return RemoteBrowserCheckResult(
                status="succeeded",
                shop_id=f"remote-{session_key}",
                user_id=f"remote-{session_key}",
                cookie_value=cookie_value,
            )
        return RemoteBrowserCheckResult(status="still_waiting_user_verification")

    def close_session(self, login_session_id: str) -> None:
        session = self._sessions.get(login_session_id)
        if session is None:
            return
        session.status = "closed"
        session.closed_at = datetime.now(timezone.utc).isoformat()

    def _is_expired(self, session: RemoteBrowserSession) -> bool:
        if not session.expires_at:
            return False
        try:
            expires_at = datetime.fromisoformat(session.expires_at)
        except ValueError:
            return False
        return expires_at < datetime.now(timezone.utc)

    def _get_cdp_pages(self) -> list[dict[str, Any]]:
        with urllib.request.urlopen(f"{self.cdp_url}/json/list", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []

    def _read_pdd_cookies_from_cdp(self, pages: list[dict[str, Any]]) -> str:
        page = next((item for item in pages if item.get("type") == "page" and item.get("webSocketDebuggerUrl")), None)
        if not page:
            return ""
        try:
            import websocket  # type: ignore
        except Exception:
            return ""

        ws = websocket.create_connection(str(page["webSocketDebuggerUrl"]), timeout=3)
        try:
            ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
            result: dict[str, Any] = {}
            for _ in range(10):
                message = json.loads(ws.recv())
                if message.get("id") == 1:
                    result = message
                    break
        finally:
            ws.close()

        cookies = result.get("result", {}).get("cookies", [])
        if not isinstance(cookies, list):
            return ""
        pdd_cookies = [
            cookie
            for cookie in cookies
            if isinstance(cookie, dict)
            and ("pinduoduo.com" in str(cookie.get("domain", "")) or "yangkeduo.com" in str(cookie.get("domain", "")))
            and cookie.get("name")
        ]
        return "; ".join(f"{cookie['name']}={cookie.get('value', '')}" for cookie in pdd_cookies)
