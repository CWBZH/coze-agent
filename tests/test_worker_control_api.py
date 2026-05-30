import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_shop_onboarding_service, get_worker_control_service
from web_api.main import app
from web_api.services.shop_auth_service import AuthSavePayload
from web_api.services.shop_onboarding_service import ShopOnboardingService
from web_api.services.worker_control_service import WorkerControlService


def _client(tmp_path: Path) -> tuple[TestClient, ShopOnboardingService, WorkerControlService, Path]:
    db_path = tmp_path / "worker_control.db"
    onboarding = ShopOnboardingService(db_path=db_path)
    onboarding.init_schema()
    worker_control = WorkerControlService(db_path=db_path, auth_service=onboarding.auth_service)
    worker_control.init_schema()
    app.dependency_overrides[get_shop_onboarding_service] = lambda: onboarding
    app.dependency_overrides[get_worker_control_service] = lambda: worker_control
    return TestClient(app), onboarding, worker_control, db_path


def _clear() -> None:
    app.dependency_overrides.clear()


def _save_auth(service: ShopOnboardingService, shop_id: str = "565617") -> None:
    service.auth_service.save_auth(
        AuthSavePayload(
            shop_id=shop_id,
            shop_name="Production Shop",
            platform="pdd",
            account_name="seller_10000000000",
            user_id="seller-user",
            cookie_value="session=DO_NOT_RETURN_COOKIE",
        )
    )


def test_worker_start_command_creates_desired_state_command_and_event(tmp_path):
    client, onboarding, _, db_path = _client(tmp_path)
    try:
        _save_auth(onboarding)

        response = client.post("/api/shops/565617/worker/start", json={"operator": "local_admin"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["desired_state"] == "running"
        assert payload["command"] == "start"
        assert payload["status"] == "pending"
        assert payload["trace_id"].startswith("workerctl-")
        assert "DO_NOT_RETURN_COOKIE" not in response.text

        conn = sqlite3.connect(db_path)
        try:
            desired = conn.execute(
                "SELECT desired_state FROM shop_worker_desired_state WHERE shop_id='565617'"
            ).fetchone()[0]
            command = conn.execute(
                "SELECT command, status FROM worker_control_commands WHERE shop_id='565617'"
            ).fetchone()
            event = conn.execute(
                "SELECT event_type, status FROM worker_events WHERE shop_id='565617'"
            ).fetchone()
        finally:
            conn.close()
        assert desired == "running"
        assert command == ("start", "pending")
        assert event == ("worker_start_requested", "pending")
    finally:
        _clear()


def test_worker_stop_command_does_not_require_valid_auth(tmp_path):
    client, _, _, db_path = _client(tmp_path)
    try:
        response = client.post(
            "/api/shops/565617/worker/stop",
            json={"operator": "local_admin", "reason": "manual stop"},
        )

        assert response.status_code == 200
        assert response.json()["desired_state"] == "stopped"
        conn = sqlite3.connect(db_path)
        try:
            desired = conn.execute(
                "SELECT desired_state, reason FROM shop_worker_desired_state WHERE shop_id='565617'"
            ).fetchone()
        finally:
            conn.close()
        assert desired == ("stopped", "manual stop")
    finally:
        _clear()


def test_worker_start_requires_valid_auth_and_real_shop_id(tmp_path):
    client, _, _, _ = _client(tmp_path)
    try:
        missing_auth = client.post("/api/shops/565617/worker/start", json={"operator": "local_admin"})
        assert missing_auth.status_code == 409
        missing_auth_payload = missing_auth.json()
        assert missing_auth_payload["error_type"] == "AUTH_REQUIRED"
        assert "店铺登录授权" in missing_auth_payload["error_summary"]
        assert "远程浏览器登录授权" in missing_auth_payload["next_action"]
        assert missing_auth_payload["trace_id"]
        assert "redacted_sensitive_error" not in missing_auth.text

        remote_id = client.post("/api/shops/remote-login123/worker/start", json={"operator": "local_admin"})
        assert remote_id.status_code == 409
        assert remote_id.json()["error_type"] == "SHOP_ID_NOT_BOUND"
    finally:
        _clear()


def test_worker_restart_updates_commands_and_list_endpoint(tmp_path):
    client, onboarding, _, _ = _client(tmp_path)
    try:
        _save_auth(onboarding)

        response = client.post(
            "/api/shops/565617/worker/restart",
            json={"operator": "local_admin", "reason": "config changed"},
        )
        assert response.status_code == 200

        listed = client.get("/api/shops/565617/worker/commands")
        assert listed.status_code == 200
        payload = listed.json()
        assert payload["total"] == 1
        assert payload["items"][0]["command"] == "restart"
        assert payload["items"][0]["desired_state"] == "running"

        events = client.get("/api/worker/events?shop_id=565617")
        assert events.status_code == 200
        assert events.json()["items"][0]["event_type"] == "worker_restart_requested"
    finally:
        _clear()
