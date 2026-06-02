from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import requests


@dataclass
class RemoteBrowserSession:
    login_session_id: str
    status: str
    access_token: str
    vnc_url: str | None = None
    error_summary: str | None = None
    shop_identity_status: str = "unknown"
    created_at: str | None = None
    expires_at: str | None = None
    closed_at: str | None = None
    cdp_url: str | None = None
    novnc_port: int | None = None
    vnc_port: int | None = None
    display_num: int | None = None
    profile_dir: str | None = None


@dataclass
class ManagedRemoteBrowserProcess:
    process: subprocess.Popen[Any]
    display_num: int
    vnc_port: int
    novnc_port: int
    cdp_port: int
    profile_dir: str


@dataclass
class RemoteBrowserCheckResult:
    status: str
    shop_id: str | None = None
    shop_name: str | None = None
    user_id: str | None = None
    account_name: str | None = None
    shop_identity_status: str = "unknown"
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
        health_check: bool | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("WEB_NOVNC_BASE_URL") or "").rstrip("/")
        self.cdp_url = (cdp_url or os.environ.get("WEB_REMOTE_BROWSER_CDP_URL") or "http://127.0.0.1:9222").rstrip("/")
        self.session_ttl_seconds = session_ttl_seconds
        self.mode = (os.environ.get("WEB_REMOTE_BROWSER_MODE") or "external").strip().lower()
        self.repo_root = Path(os.environ.get("WEB_REMOTE_BROWSER_REPO_ROOT") or Path.cwd()).resolve()
        self.start_script = Path(
            os.environ.get("WEB_REMOTE_BROWSER_START_SCRIPT") or self.repo_root / "deploy" / "linux" / "start-novnc.sh"
        )
        self.managed_public_host = os.environ.get("WEB_REMOTE_BROWSER_PUBLIC_HOST") or ""
        self.managed_profile_root = Path(
            os.environ.get("WEB_REMOTE_BROWSER_PROFILE_ROOT") or self.repo_root / "temp" / "remote-browser-sessions"
        )
        self.managed_display_start = int(os.environ.get("WEB_REMOTE_BROWSER_DISPLAY_START", "120"))
        self.managed_vnc_port_start = int(os.environ.get("WEB_REMOTE_BROWSER_VNC_PORT_START", "59020"))
        self.managed_novnc_port_start = int(os.environ.get("WEB_REMOTE_BROWSER_NOVNC_PORT_START", "6100"))
        self.managed_cdp_port_start = int(os.environ.get("WEB_REMOTE_BROWSER_CDP_PORT_START", "9300"))
        self.health_check = (
            health_check
            if health_check is not None
            else os.environ.get("WEB_NOVNC_HEALTHCHECK_ENABLED", "1").lower() not in {"0", "false", "no"}
        )
        self._sessions: dict[str, RemoteBrowserSession] = {}
        self._managed_processes: dict[str, ManagedRemoteBrowserProcess] = {}

    def create_session(self, login_session_id: str, login_url: str) -> RemoteBrowserSession:
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(24)
        if not self.base_url and self.mode != "managed":
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

        if self.mode == "managed":
            session = self._create_managed_session(login_session_id, login_url, token, now)
            self._sessions[login_session_id] = session
            return session

        health_error = self._health_error()
        if health_error:
            session = RemoteBrowserSession(
                login_session_id=login_session_id,
                status="failed",
                access_token=token,
                error_summary=health_error,
                created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
            )
            self._sessions[login_session_id] = session
            return session

        vnc_url = (
            f"{self.base_url}/vnc.html"
            f"?autoconnect=1&resize=remote&path=websockify&session={login_session_id}&token={token}"
        )
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

    def _create_managed_session(
        self,
        login_session_id: str,
        login_url: str,
        token: str,
        now: datetime,
    ) -> RemoteBrowserSession:
        if not self.start_script.exists():
            return RemoteBrowserSession(
                login_session_id=login_session_id,
                status="failed",
                access_token=token,
                error_summary="missing_dependency:remote_browser_start_script",
                created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
            )

        try:
            managed = self._launch_managed_browser(login_session_id, login_url)
            public_base_url = self._managed_public_base_url(managed.novnc_port)
            local_base_url = f"http://127.0.0.1:{managed.novnc_port}"
            cdp_url = f"http://127.0.0.1:{managed.cdp_port}"
            health_error = self._managed_health_error(local_base_url, cdp_url)
            if health_error:
                self._terminate_managed_process(login_session_id)
                return RemoteBrowserSession(
                    login_session_id=login_session_id,
                    status="failed",
                    access_token=token,
                    error_summary=health_error,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
                    cdp_url=cdp_url,
                    novnc_port=managed.novnc_port,
                    vnc_port=managed.vnc_port,
                    display_num=managed.display_num,
                    profile_dir=managed.profile_dir,
                )
            vnc_url = (
                f"{public_base_url}/vnc.html"
                f"?autoconnect=1&resize=remote&path=websockify&session={login_session_id}&token={token}"
            )
            return RemoteBrowserSession(
                login_session_id=login_session_id,
                status="ready",
                access_token=token,
                vnc_url=vnc_url,
                created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
                cdp_url=cdp_url,
                novnc_port=managed.novnc_port,
                vnc_port=managed.vnc_port,
                display_num=managed.display_num,
                profile_dir=managed.profile_dir,
            )
        except Exception as exc:
            self._terminate_managed_process(login_session_id)
            return RemoteBrowserSession(
                login_session_id=login_session_id,
                status="failed",
                access_token=token,
                error_summary=f"remote_browser_start_failed:{type(exc).__name__}",
                created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
            )

    def _launch_managed_browser(self, login_session_id: str, login_url: str) -> ManagedRemoteBrowserProcess:
        index = len(self._managed_processes) + len(self._sessions)
        display_num = self._find_free_display(self.managed_display_start + index)
        vnc_port = self._find_free_port(self.managed_vnc_port_start + index)
        novnc_port = self._find_free_port(self.managed_novnc_port_start + index)
        cdp_port = self._find_free_port(self.managed_cdp_port_start + index)
        profile_dir = str((self.managed_profile_root / login_session_id).resolve())
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "DISPLAY_NUM": str(display_num),
                "VNC_PORT": str(vnc_port),
                "NOVNC_PORT": str(novnc_port),
                "CHROME_DEBUG_PORT": str(cdp_port),
                "PROFILE_DIR": profile_dir,
                "PDD_LOGIN_URL": login_url,
            }
        )
        process = subprocess.Popen(
            ["bash", str(self.start_script)],
            cwd=str(self.repo_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        managed = ManagedRemoteBrowserProcess(
            process=process,
            display_num=display_num,
            vnc_port=vnc_port,
            novnc_port=novnc_port,
            cdp_port=cdp_port,
            profile_dir=profile_dir,
        )
        self._managed_processes[login_session_id] = managed
        return managed

    def _managed_public_base_url(self, novnc_port: int) -> str:
        configured = os.environ.get("WEB_REMOTE_BROWSER_PUBLIC_BASE_URL_TEMPLATE")
        if configured:
            return configured.format(port=novnc_port).rstrip("/")
        parsed = urlparse(self.base_url)
        scheme = parsed.scheme or "http"
        host = self.managed_public_host or parsed.hostname or "127.0.0.1"
        return f"{scheme}://{host}:{novnc_port}"

    def _managed_health_error(self, public_base_url: str, cdp_url: str) -> str | None:
        if not self.health_check:
            return None
        deadline = time.time() + float(os.environ.get("WEB_REMOTE_BROWSER_START_TIMEOUT_SECONDS", "15"))
        last_error = "managed_remote_browser_unreachable"
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{public_base_url}/vnc.html", timeout=2) as response:
                    if response.status >= 500:
                        last_error = f"novnc_unreachable:http_{response.status}"
                        time.sleep(0.5)
                        continue
                with urllib.request.urlopen(f"{cdp_url}/json/list", timeout=2) as response:
                    if response.status >= 500:
                        last_error = f"chrome_cdp_unreachable:http_{response.status}"
                        time.sleep(0.5)
                        continue
                return None
            except Exception as exc:
                last_error = f"managed_remote_browser_unreachable:{type(exc).__name__}"
                time.sleep(0.5)
        return last_error

    def _find_free_display(self, start: int) -> int:
        value = max(1, int(start))
        used_displays = {item.display_num for item in self._managed_processes.values()}
        while value in used_displays:
            value += 1
        return value

    def _find_free_port(self, start: int) -> int:
        port = max(1024, int(start))
        while not self._port_available(port):
            port += 1
        return port

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) != 0

    def _health_error(self) -> str | None:
        if not self.health_check:
            return None
        try:
            with urllib.request.urlopen(f"{self.base_url}/vnc.html", timeout=2) as response:
                if response.status >= 500:
                    return f"novnc_unreachable:http_{response.status}"
        except Exception:
            return "novnc_unreachable:check_customer_agent_novnc_service_or_nginx_6088"
        websocket_error = self._websockify_health_error()
        if websocket_error:
            return websocket_error
        try:
            self._get_cdp_pages()
        except Exception:
            return "chrome_cdp_unreachable:check_WEB_REMOTE_BROWSER_CDP_URL_or_chrome_9222"
        return None

    def _websockify_health_error(self) -> str | None:
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        netloc = parsed.netloc
        path_prefix = parsed.path.strip("/")
        ws_path = "/".join(part for part in (path_prefix, "websockify") if part)
        ws_url = f"{scheme}://{netloc}/{ws_path}"
        try:
            import websocket  # type: ignore
        except Exception:
            return "novnc_websockify_check_unavailable:missing_websocket_client"
        try:
            ws = websocket.create_connection(ws_url, timeout=2)
            ws.close()
        except Exception:
            return "novnc_websockify_unreachable:check_nginx_websocket_proxy_or_websockify_port"
        return None

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
            cdp_url = session.cdp_url or self.cdp_url
            pages = self._get_cdp_pages(cdp_url)
            urls = [str(page.get("url") or "") for page in pages]
            cookie_value = self._read_pdd_cookies_from_cdp(pages, cdp_url=cdp_url)
        except Exception:
            return RemoteBrowserCheckResult(status="still_waiting_user_verification")

        pdd_urls = [url for url in urls if "pinduoduo.com" in url or "yangkeduo.com" in url]
        login_urls = [url for url in pdd_urls if "login" in url.lower()]
        if cookie_value and pdd_urls and not login_urls:
            identity = self._resolve_shop_identity(pages, cookie_value)
            if not identity:
                return RemoteBrowserCheckResult(
                    status="succeeded",
                    cookie_value=cookie_value,
                    shop_identity_status="pending_real_shop_id",
                )
            return RemoteBrowserCheckResult(
                status="succeeded",
                shop_id=identity.get("shop_id"),
                shop_name=identity.get("shop_name"),
                user_id=identity.get("user_id"),
                account_name=identity.get("account_name"),
                cookie_value=cookie_value,
                shop_identity_status="bound",
            )
        return RemoteBrowserCheckResult(status="still_waiting_user_verification")

    def close_session(self, login_session_id: str) -> None:
        session = self._sessions.get(login_session_id)
        if session is None:
            return
        session.status = "closed"
        session.closed_at = datetime.now(timezone.utc).isoformat()
        self._terminate_managed_process(login_session_id)

    def _terminate_managed_process(self, login_session_id: str) -> None:
        managed = self._managed_processes.pop(login_session_id, None)
        if managed is None:
            return
        process = managed.process
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def _is_expired(self, session: RemoteBrowserSession) -> bool:
        if not session.expires_at:
            return False
        try:
            expires_at = datetime.fromisoformat(session.expires_at)
        except ValueError:
            return False
        return expires_at < datetime.now(timezone.utc)

    def _get_cdp_pages(self, cdp_url: str | None = None) -> list[dict[str, Any]]:
        base = (cdp_url or self.cdp_url).rstrip("/")
        with urllib.request.urlopen(f"{base}/json/list", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []

    def _read_pdd_cookies_from_cdp(self, pages: list[dict[str, Any]], *, cdp_url: str | None = None) -> str:
        page = next((item for item in pages if item.get("type") == "page" and item.get("webSocketDebuggerUrl")), None)
        if not page:
            return ""
        try:
            import websocket  # type: ignore
        except Exception:
            return ""

        ws = websocket.create_connection(str(page["webSocketDebuggerUrl"]), timeout=3, origin=(cdp_url or self.cdp_url))
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

    def _extract_shop_identity_from_cdp(self, pages: list[dict[str, Any]]) -> str:
        page = next((item for item in pages if item.get("type") == "page" and item.get("webSocketDebuggerUrl")), None)
        if not page:
            return ""
        candidates = [str(page.get("url") or ""), str(page.get("title") or "")]
        runtime_payload = self._evaluate_runtime_snapshot(str(page.get("webSocketDebuggerUrl") or ""))
        if runtime_payload:
            candidates.append(runtime_payload)
        combined = "\n".join(candidates)
        patterns = (
            r"\bmall[_-]?id[\"'\s:=]+([0-9]{4,})",
            r"\bshop[_-]?id[\"'\s:=]+([0-9]{4,})",
            r"\bmallId[\"'\s:=]+([0-9]{4,})",
            r"\bshopId[\"'\s:=]+([0-9]{4,})",
        )
        for pattern in patterns:
            match = re.search(pattern, combined, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    def _resolve_shop_identity(self, pages: list[dict[str, Any]], cookie_value: str) -> dict[str, str]:
        page_identity = self._extract_shop_identity_from_cdp(pages)
        api_identity = self._fetch_shop_identity_from_pdd_api(cookie_value)
        identity: dict[str, str] = {}
        identity.update(api_identity)
        if page_identity and not identity.get("shop_id"):
            identity["shop_id"] = page_identity
        if not self._is_real_pdd_id(identity.get("shop_id")):
            return {}
        return identity

    def _fetch_shop_identity_from_pdd_api(self, cookie_value: str) -> dict[str, str]:
        cookies = self._parse_cookie_header(cookie_value)
        if not cookies:
            return {}

        identity: dict[str, str] = {}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://mms.pinduoduo.com",
            "Referer": "https://mms.pinduoduo.com/home",
        }

        try:
            user_response = requests.post(
                "https://mms.pinduoduo.com/janus/api/new/userinfo",
                data="",
                cookies=cookies,
                headers=headers,
                timeout=10,
            )
            user_payload = user_response.json()
            if user_payload.get("success"):
                result = user_payload.get("result") or {}
                if result.get("mall_id"):
                    identity["shop_id"] = str(result.get("mall_id"))
                if result.get("id"):
                    identity["user_id"] = str(result.get("id"))
                if result.get("username"):
                    identity["account_name"] = str(result.get("username"))
        except Exception:
            pass

        try:
            shop_response = requests.post(
                "https://mms.pinduoduo.com/earth/api/merchant/queryMerchantInfoByMallId",
                json={},
                cookies=cookies,
                headers=headers,
                timeout=10,
            )
            shop_payload = shop_response.json()
            if shop_payload.get("success"):
                result = shop_payload.get("result") or {}
                if result.get("mallId"):
                    identity["shop_id"] = str(result.get("mallId"))
                if result.get("mallName"):
                    identity["shop_name"] = str(result.get("mallName"))
        except Exception:
            pass

        if not self._is_real_pdd_id(identity.get("shop_id")):
            return {}
        return identity

    @staticmethod
    def _parse_cookie_header(cookie_value: str) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for part in str(cookie_value or "").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            if key:
                cookies[key] = value.strip()
        return cookies

    @staticmethod
    def _is_real_pdd_id(value: str | None) -> bool:
        value = str(value or "").strip()
        return bool(re.fullmatch(r"\d{4,}", value))

    def _evaluate_runtime_snapshot(self, websocket_url: str) -> str:
        if not websocket_url:
            return ""
        try:
            import websocket  # type: ignore
        except Exception:
            return ""
        expression = """
        JSON.stringify({
          href: location.href,
          title: document.title,
          localStorage: Object.assign({}, localStorage),
          sessionStorage: Object.assign({}, sessionStorage),
          bodyText: document.body ? document.body.innerText.slice(0, 8000) : ''
        })
        """
        try:
            ws = websocket.create_connection(websocket_url, timeout=3, origin=self.cdp_url)
            try:
                ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": expression}}))
                for _ in range(10):
                    message = json.loads(ws.recv())
                    if message.get("id") == 2:
                        return str(message.get("result", {}).get("result", {}).get("value") or "")
            finally:
                ws.close()
        except Exception:
            return ""
        return ""
