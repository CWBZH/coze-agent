import sqlite3
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_shop_onboarding_service
from web_api.main import app
from web_api.services import pdd_login_runner
from web_api.services.pdd_login_runner import FakePddLoginRunner, LoginRunnerState, LoginRunnerSuccess
from web_api.services.shop_onboarding_service import ShopOnboardingService


def _client_for_db(db_path: Path, runner: FakePddLoginRunner | None = None) -> TestClient:
    service = ShopOnboardingService(db_path=db_path, runner=runner or FakePddLoginRunner())
    service.init_schema()
    app.dependency_overrides[get_shop_onboarding_service] = lambda: service
    return TestClient(app)


def _client_for_service(service: ShopOnboardingService) -> TestClient:
    service.init_schema()
    app.dependency_overrides[get_shop_onboarding_service] = lambda: service
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _stored_auth_cookie(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT cookie_encrypted FROM shop_auth LIMIT 1").fetchone()
        assert row is not None
        return str(row[0])
    finally:
        conn.close()


def test_create_and_get_onboarding_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    db_path = tmp_path / "onboarding.db"
    client = _client_for_db(db_path)
    try:
        created = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "测试店铺",
                "account_name": "seller_account_10000000000",
                "password": "DO_NOT_STORE_PASSWORD",
                "operator": "local_admin",
            },
        )

        assert created.status_code == 200
        payload = created.json()
        assert payload["status"] == "waiting_sms_code"
        assert payload["needs_sms_code"] is True
        assert "password" not in created.text.lower()

        fetched = client.get(f"/api/shops/onboarding/{payload['session_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["session_id"] == payload["session_id"]
        assert fetched.json()["safe_display"] == "seller_account_100***000"
    finally:
        _clear_overrides()


def test_submit_sms_success_saves_encrypted_auth_and_binds_shop(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    db_path = tmp_path / "onboarding.db"
    client = _client_for_db(db_path)
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={"platform": "pdd", "shop_name": "测试店铺", "account_name": "seller_account_10000000000", "password": "secret"},
        ).json()

        submitted = client.post(f"/api/shops/onboarding/{session['session_id']}/submit-sms-code", json={"sms_code": "123456"})

        assert submitted.status_code == 200
        payload = submitted.json()
        assert payload["status"] == "succeeded"
        assert payload["shop_id"] == "565617"
        assert "fake-cookie-value" not in submitted.text
        assert "secret" not in submitted.text

        auth = client.get("/api/shops/565617/auth-status")
        assert auth.status_code == 200
        auth_payload = auth.json()
        assert auth_payload["auth_status"] == "auth_valid"
        assert auth_payload["safe_display"] == "seller_account_100***000"
        assert auth_payload["insecure_auth_storage"] is False
        assert "cookie" not in auth.text.lower()

        stored_cookie = _stored_auth_cookie(db_path)
        assert "fake-cookie-value" not in stored_cookie

        conn = sqlite3.connect(db_path)
        try:
            account = conn.execute("SELECT username, password, cookies FROM accounts LIMIT 1").fetchone()
            assert account is not None
            assert account[0] == "seller_account_10000000000"
            assert account[1] == ""
            assert account[2] is None
        finally:
            conn.close()
    finally:
        _clear_overrides()


def test_submit_captcha_is_controlled_unsupported_flow(tmp_path):
    client = _client_for_db(tmp_path / "onboarding.db")
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={"platform": "pdd", "shop_name": "测试店铺", "account_name": "seller", "password": "secret"},
        ).json()

        response = client.post(f"/api/shops/onboarding/{session['session_id']}/submit-captcha", json={"captcha_code": "abcd"})

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "unsupported_captcha_flow"
    finally:
        _clear_overrides()


def test_cancel_session_is_idempotent(tmp_path):
    client = _client_for_db(tmp_path / "onboarding.db")
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={"platform": "pdd", "shop_name": "测试店铺", "account_name": "seller", "password": "secret"},
        ).json()

        first = client.post(f"/api/shops/onboarding/{session['session_id']}/cancel")
        second = client.post(f"/api/shops/onboarding/{session['session_id']}/cancel")

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["status"] == "cancelled"
    finally:
        _clear_overrides()


def test_expired_session_cannot_accept_sms_code(tmp_path):
    db_path = tmp_path / "onboarding.db"
    client = _client_for_db(db_path)
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={"platform": "pdd", "shop_name": "测试店铺", "account_name": "seller", "password": "secret"},
        ).json()
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("UPDATE shop_login_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (session["session_id"],))
            conn.commit()
        finally:
            conn.close()

        response = client.post(f"/api/shops/onboarding/{session['session_id']}/submit-sms-code", json={"sms_code": "123456"})

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "session_expired"
    finally:
        _clear_overrides()


def test_auth_status_not_found_and_complex_verification(tmp_path):
    client = _client_for_db(tmp_path / "onboarding.db")
    try:
        missing = client.get("/api/shops/missing-shop/auth-status")
        assert missing.status_code == 404

        session = client.post(
            "/api/shops/onboarding",
            json={"platform": "pdd", "shop_name": "测试店铺", "account_name": "seller", "password": "secret"},
        ).json()
        blocked = client.post(f"/api/shops/onboarding/{session['session_id']}/submit-sms-code", json={"sms_code": "999999"})

        assert blocked.status_code == 200
        assert blocked.json()["status"] == "blocked_complex_verification"
        assert "cookie" not in blocked.text.lower()
    finally:
        _clear_overrides()


class FakeRealRunner(FakePddLoginRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started: list[tuple[str, str, str | None]] = []
        self.cancelled: list[str] = []
        self.polled: list[str] = []

    def start_session(self, session_id: str, account_name: str, password: str | None, shop_name: str | None = None) -> LoginRunnerState:
        self.started.append((session_id, account_name, password))
        self._sessions[session_id] = {"account_name": account_name, "shop_name": shop_name, "password": None}
        return LoginRunnerState(status="opening_login_page", step="opening_login_page")

    def get_state(self, session_id: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        self.polled.append(session_id)
        return (LoginRunnerState(status="waiting_sms_code", step="waiting_sms_code", needs_sms_code=True), None)

    def cancel(self, session_id: str) -> LoginRunnerState:
        self.cancelled.append(session_id)
        return super().cancel(session_id)


def test_real_runner_mode_uses_injected_runner_and_polling_does_not_expose_secrets(tmp_path):
    db_path = tmp_path / "onboarding.db"
    real_runner = FakeRealRunner()
    service = ShopOnboardingService(db_path=db_path, runner=FakePddLoginRunner(), real_runner=real_runner)
    client = _client_for_service(service)
    try:
        created = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "测试店铺",
                "account_name": "seller_account_10000000000",
                "password": "DO_NOT_LEAK_PASSWORD",
                "runner_mode": "real",
            },
        )

        assert created.status_code == 200
        session_id = created.json()["session_id"]
        assert created.json()["status"] == "opening_login_page"
        assert real_runner.started == [(session_id, "seller_account_10000000000", "DO_NOT_LEAK_PASSWORD")]
        assert "DO_NOT_LEAK_PASSWORD" not in created.text

        polled = client.get(f"/api/shops/onboarding/{session_id}")

        assert polled.status_code == 200
        assert polled.json()["status"] == "waiting_sms_code"
        assert polled.json()["needs_sms_code"] is True
        assert real_runner.polled == [session_id]
        assert "DO_NOT_LEAK_PASSWORD" not in polled.text
        assert "cookie" not in polled.text.lower()
    finally:
        _clear_overrides()


def test_real_runner_cancel_closes_runner_session(tmp_path):
    db_path = tmp_path / "onboarding.db"
    real_runner = FakeRealRunner()
    service = ShopOnboardingService(db_path=db_path, runner=FakePddLoginRunner(), real_runner=real_runner)
    client = _client_for_service(service)
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "测试店铺",
                "account_name": "seller",
                "password": "secret",
                "runner_mode": "real",
            },
        ).json()

        cancelled = client.post(f"/api/shops/onboarding/{session['session_id']}/cancel")

        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert real_runner.cancelled == [session["session_id"]]
    finally:
        _clear_overrides()


def test_real_runner_mode_sms_success_saves_encrypted_auth_without_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    db_path = tmp_path / "onboarding.db"
    real_runner = FakeRealRunner()
    service = ShopOnboardingService(db_path=db_path, runner=FakePddLoginRunner(), real_runner=real_runner)
    client = _client_for_service(service)
    try:
        session = client.post(
            "/api/shops/onboarding",
            json={
                "platform": "pdd",
                "shop_name": "测试店铺",
                "account_name": "seller_account_10000000000",
                "password": "DO_NOT_LEAK_PASSWORD",
                "runner_mode": "real",
            },
        ).json()

        submitted = client.post(f"/api/shops/onboarding/{session['session_id']}/submit-sms-code", json={"sms_code": "123456"})

        assert submitted.status_code == 200
        assert submitted.json()["status"] == "succeeded"
        assert submitted.json()["runner_mode"] == "real"
        assert "fake-cookie-value" not in submitted.text
        assert "DO_NOT_LEAK_PASSWORD" not in submitted.text

        stored_cookie = _stored_auth_cookie(db_path)
        assert "fake-cookie-value" not in stored_cookie
    finally:
        _clear_overrides()


def test_real_runner_login_selectors_are_utf8_chinese_and_diagnostic():
    selector_values = "\n".join(
        selector
        for selectors in pdd_login_runner.LOGIN_SELECTOR_GROUPS.values()
        for selector in selectors
    )

    assert "账号登录" in selector_values
    assert "密码登录" in selector_values
    assert "登录" in selector_values
    assert "短信" in selector_values
    assert "验证码" in selector_values
    assert "璐" not in selector_values
    assert "鐧" not in selector_values


def test_real_runner_timeout_state_preserves_failed_stage():
    state = pdd_login_runner.login_stage_failure_state("password_input", "timeout")

    assert state.status == "failed"
    assert state.step == "password_input"
    assert state.error_summary == "password_input_timeout"


def test_real_runner_does_not_fail_terminal_when_shop_info_not_ready(monkeypatch):
    runner = pdd_login_runner.RealPddLoginRunner(timeout_seconds=1)
    session_id = "login-unit-shop-info"
    runner._sessions[session_id] = {
        "account_name": "seller",
        "password": "DO_NOT_STORE",
        "sms_code": None,
        "sms_event": None,
        "state": pdd_login_runner.LoginRunnerState(status="logging_in", step="logging_in"),
        "success": None,
        "cancel_requested": False,
    }

    class FakeContext:
        async def cookies(self):
            return [{"name": "session", "value": "fake-cookie-value"}]

    monkeypatch.setattr(pdd_login_runner, "_fetch_pdd_user_info", lambda cookies: {})
    monkeypatch.setattr(pdd_login_runner, "_fetch_pdd_shop_info", lambda cookies: {})

    completed = asyncio.run(runner._complete_success(session_id, "seller", FakeContext()))
    state, success = runner.get_state(session_id)

    assert completed is False
    assert success is None
    assert state.status == "logging_in"
    assert state.error_summary is None
