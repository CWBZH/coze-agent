import sqlite3
from pathlib import Path

from runtime.worker_manager import WorkerManager, WorkerManagerConfig
from web_api.services.schema_migration_service import SchemaMigrationService
from web_api.services.shop_auth_service import AuthSavePayload, ShopAuthService
from web_api.services.worker_control_service import WorkerControlService


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.pid = 12345

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self) -> None:
        self.killed = True


def _save_auth(db_path: Path) -> None:
    SchemaMigrationService(db_path).migrate()
    ShopAuthService(db_path).save_auth(
        AuthSavePayload(
            shop_id="565617",
            shop_name="Production Shop",
            platform="pdd",
            account_name="seller_10000000000",
            user_id="seller-user",
            cookie_value="session=DO_NOT_RETURN_COOKIE",
        )
    )


def test_worker_manager_dispatches_start_command_without_exposing_secrets(tmp_path):
    db_path = tmp_path / "worker_manager.db"
    _save_auth(db_path)
    control = WorkerControlService(db_path)
    command = control.request_start("565617", operator="local_admin")
    launched: list[tuple[list[str], dict[str, str], Path]] = []

    def fake_launcher(cmd, env, cwd):
        launched.append((cmd, env, cwd))
        return FakeProcess()

    manager = WorkerManager(
        WorkerManagerConfig(
            db_path=db_path,
            status_file=tmp_path / "runtime" / "worker_status.json",
            stop_file=tmp_path / "runtime.stop",
            log_dir=tmp_path / "logs",
            python_executable="python-test",
        ),
        process_launcher=fake_launcher,
        repo_root=Path.cwd(),
    )

    assert manager.run_once() is True

    assert launched
    cmd, env, _ = launched[0]
    assert cmd[:3] == ["python-test", "-m", "runtime.worker"]
    assert "--all-enabled" in cmd
    assert env["DB_PATH"] == str(db_path)
    assert "DO_NOT_RETURN_COOKIE" not in str(launched)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, started_at, finished_at FROM worker_control_commands WHERE id=?",
            (command["id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT event_type, status FROM worker_events WHERE shop_id='565617' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "succeeded"
    assert row[1]
    assert row[2]
    assert event == ("worker_start_dispatched", "succeeded")


def test_worker_manager_dispatches_stop_command_with_stop_file(tmp_path):
    db_path = tmp_path / "worker_manager.db"
    control = WorkerControlService(db_path)
    command = control.request_stop("565617", operator="local_admin", reason="manual")
    stop_file = tmp_path / "runtime.stop"
    manager = WorkerManager(
        WorkerManagerConfig(db_path=db_path, stop_file=stop_file, status_file=tmp_path / "status.json"),
        process_launcher=lambda cmd, env, cwd: FakeProcess(),
        repo_root=Path.cwd(),
    )
    manager.process = FakeProcess()

    assert manager.run_once() is True

    assert stop_file.exists()
    assert manager.process.terminated is True
    conn = sqlite3.connect(db_path)
    try:
        status = conn.execute(
            "SELECT status FROM worker_control_commands WHERE id=?",
            (command["id"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "succeeded"
