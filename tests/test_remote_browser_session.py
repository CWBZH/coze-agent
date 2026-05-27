import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_shop_onboarding_service
from web_api.main import app
from web_api.services.pdd_login_runner import FakePddLoginRunner
from web_api.services.remote_browser_service import RemoteBrowserCheckResult, RemoteBrowserSession
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
                "account_name": "seller_account_13570354888",
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
                "account_name": "seller_account_13570354888",
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
            account_name="seller_account_13570354888",
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
                "account_name": "seller_account_13570354888",
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
