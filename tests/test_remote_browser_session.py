import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_shop_onboarding_service
from web_api.main import app
from web_api.services.pdd_login_runner import FakePddLoginRunner
from web_api.services.remote_browser_service import RemoteBrowserCheckResult, RemoteBrowserSession
from web_api.services.remote_browser_service import RemoteBrowserService
from web_api.services.shop_onboarding_service import ShopOnboardingService


class FakeRemoteBrowserService:
    def __init__(self) -> None:
        self.sessions: dict[str, RemoteBrowserSession] = {}
        self.closed: list[str] = []
        self.next_check_result = RemoteBrowserCheckResult(status="still_waiting_user_verification")

    def create_session(self, login_session_id: str, login_url: str) -> RemoteBrowserSession:
        session = RemoteBrowserSession(
            login_session_id=login_session_id,
            status="ready",
            access_token=f"token-{login_session_id}",
            vnc_url=f"http://127.0.0.1:6080/vnc.html?session={login_session_id}&token=token-{login_session_id}",
        )
        self.sessions[login_session_id] = session
        return session

    def get_session(self, login_session_id: str) -> RemoteBrowserSession | None:
        return self.sessions.get(login_session_id)

    def check_login_success(self, login_session_id: str) -> RemoteBrowserCheckResult:
        return self.next_check_result

    def close_session(self, login_session_id: str) -> None:
        self.closed.append(login_session_id)
        if login_session_id in self.sessions:
            self.sessions[login_session_id].status = "closed"


def _client_for_remote(db_path: Path, remote_service: FakeRemoteBrowserService) -> TestClient:
    service = ShopOnboardingService(
        db_path=db_path,
        runner=FakePddLoginRunner(),
        remote_browser_service=remote_service,
    )
    service.init_schema()
    app.dependency_overrides[get_shop_onboarding_service] = lambda: service
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_remote_browser_mode_creates_tokenized_vnc_session(tmp_path):
    remote = FakeRemoteBrowserService()
    client = _client_for_remote(tmp_path / "onboarding.db", remote)
    try:
        response = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "测试店铺",
                "account_name": "seller_account_10000000000",
                "password": "DO_NOT_LEAK_PASSWORD",
                "runner_mode": "remote_browser",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["runner_mode"] == "remote_browser"
        assert payload["status"] == "waiting_user_verification"
        assert payload["remote_browser_available"] is True
        assert payload["remote_browser_status"] == "ready"
        assert payload["vnc_url_ready"] is True
        assert "token=" in payload["vnc_url"]
        assert "DO_NOT_LEAK_PASSWORD" not in response.text
        assert "cookie" not in response.text.lower()
    finally:
        _clear_overrides()


def test_remote_browser_default_ttl_is_30_minutes():
    service = RemoteBrowserService(base_url="http://127.0.0.1:6088")

    assert service.session_ttl_seconds == 1800


def test_remote_browser_check_result_supports_pending_shop_identity():
    result = RemoteBrowserCheckResult(
        status="succeeded",
        cookie_value="fake-cookie-value",
        shop_identity_status="pending_real_shop_id",
    )

    assert result.status == "succeeded"
    assert result.shop_identity_status == "pending_real_shop_id"
    assert result.shop_id is None


def test_remote_browser_resolves_shop_identity_with_pdd_readonly_apis(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, "cookies": kwargs.get("cookies")})
        assert kwargs.get("cookies") == {"api_uid": "fake-api-uid", "webp": "1"}
        if "userinfo" in url:
            return FakeResponse(
                {
                    "success": True,
                    "result": {
                        "mall_id": "323473738",
                        "id": "seller-user-id",
                        "username": "seller_account_10000000000",
                    },
                }
            )
        return FakeResponse({"success": True, "result": {"mallId": "323473738", "mallName": "美肌萌主驿站"}})

    monkeypatch.setattr("web_api.services.remote_browser_service.requests.post", fake_post)
    service = RemoteBrowserService(base_url="http://127.0.0.1:6088")

    identity = service._fetch_shop_identity_from_pdd_api("api_uid=fake-api-uid; webp=1")

    assert identity == {
        "shop_id": "323473738",
        "user_id": "seller-user-id",
        "account_name": "seller_account_10000000000",
        "shop_name": "美肌萌主驿站",
    }
    assert len(calls) == 2


def test_remote_browser_check_login_auto_binds_shop_identity_from_cdp_cookie(monkeypatch):
    service = RemoteBrowserService(base_url="http://127.0.0.1:6088")
    session = service.create_session("login-auto-bind", "https://mms.pinduoduo.com/login")

    monkeypatch.setattr(
        service,
        "_get_cdp_pages",
        lambda: [{"type": "page", "url": "https://mms.pinduoduo.com/home", "webSocketDebuggerUrl": "ws://local"}],
    )
    monkeypatch.setattr(service, "_read_pdd_cookies_from_cdp", lambda pages: "api_uid=fake-api-uid; webp=1")
    monkeypatch.setattr(
        service,
        "_fetch_shop_identity_from_pdd_api",
        lambda cookie: {
            "shop_id": "323473738",
            "shop_name": "美肌萌主驿站",
            "user_id": "seller-user-id",
            "account_name": "seller_account_10000000000",
        },
    )

    result = service.check_login_success(session.login_session_id)

    assert result.status == "succeeded"
    assert result.shop_identity_status == "bound"
    assert result.shop_id == "323473738"
    assert result.shop_name == "美肌萌主驿站"
    assert result.user_id == "seller-user-id"
    assert result.account_name == "seller_account_10000000000"


def test_remote_browser_check_login_waiting_and_success_saves_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    remote = FakeRemoteBrowserService()
    client = _client_for_remote(tmp_path / "onboarding.db", remote)
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "测试店铺",
                "account_name": "seller_account_10000000000",
                "password": "DO_NOT_LEAK_PASSWORD",
                "runner_mode": "remote_browser",
            },
        ).json()

        waiting = client.post(f"/api/shops/onboarding/{session['session_id']}/check-login")
        assert waiting.status_code == 200
        assert waiting.json()["status"] == "waiting_user_verification"

        remote.next_check_result = RemoteBrowserCheckResult(
            status="succeeded",
            shop_id="565617",
            shop_name="测试店铺",
            user_id="fake-user-565617",
            account_name="seller_account_10000000000",
            cookie_value="fake-cookie-value",
        )
        succeeded = client.post(f"/api/shops/onboarding/{session['session_id']}/check-login")

        assert succeeded.status_code == 200
        payload = succeeded.json()
        assert payload["status"] == "succeeded"
        assert payload["shop_id"] == "565617"
        assert session["session_id"] in remote.closed
        assert "fake-cookie-value" not in succeeded.text
        assert "DO_NOT_LEAK_PASSWORD" not in succeeded.text

        conn = sqlite3.connect(tmp_path / "onboarding.db")
        try:
            stored = conn.execute("SELECT cookie_encrypted FROM shop_auth WHERE shop_id='565617'").fetchone()
            assert stored is not None
            assert "fake-cookie-value" not in str(stored[0])
            account = conn.execute("SELECT password, cookies FROM accounts LIMIT 1").fetchone()
            assert account is not None
            assert account[0] == ""
            assert account[1] is None
        finally:
            conn.close()
    finally:
        _clear_overrides()


def test_remote_browser_cancel_closes_session(tmp_path):
    remote = FakeRemoteBrowserService()
    client = _client_for_remote(tmp_path / "onboarding.db", remote)
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "测试店铺",
                "account_name": "seller_account_10000000000",
                "password": "DO_NOT_LEAK_PASSWORD",
                "runner_mode": "remote_browser",
            },
        ).json()

        cancelled = client.post(f"/api/shops/onboarding/{session['session_id']}/cancel")

        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert session["session_id"] in remote.closed
    finally:
        _clear_overrides()
