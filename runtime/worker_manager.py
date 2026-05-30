"""Worker Manager for executing Web Admin worker control commands."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from web_api.services.schema_migration_service import SchemaMigrationService
from web_api.services.shop_auth_service import utc_now_iso
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


ProcessLauncher = Callable[[list[str], dict[str, str], Path], Any]


@dataclass
class WorkerManagerConfig:
    db_path: Path = DEFAULT_DB_PATH
    status_file: Path = Path("temp/runtime/worker_status.json")
    stop_file: Path = Path("runtime.stop")
    log_dir: Path = Path("logs")
    python_executable: str = sys.executable
    status_interval: float = 5.0


def _default_launcher(command: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=str(cwd), env=env)


class WorkerManager:
    def __init__(
        self,
        config: WorkerManagerConfig,
        *,
        process_launcher: ProcessLauncher | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.config = config
        self.process_launcher = process_launcher or _default_launcher
        self.repo_root = repo_root or Path(__file__).resolve().parents[1]
        self.process: Any | None = None

    def init_schema(self) -> None:
        SchemaMigrationService(self.config.db_path).migrate()

    def _connect(self) -> sqlite3.Connection:
        self.config.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.config.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def run_once(self) -> bool:
        self.init_schema()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM worker_control_commands
                WHERE status='pending'
                ORDER BY requested_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return False
            self._mark_command(conn, row["id"], "running", started_at=utc_now_iso())
            conn.commit()
            try:
                self._dispatch_command(str(row["command"]))
            except Exception as exc:
                self._mark_command(
                    conn,
                    row["id"],
                    "failed",
                    finished_at=utc_now_iso(),
                    error_type=exc.__class__.__name__,
                    error_summary=str(exc)[:300],
                )
                self._record_event(
                    conn,
                    shop_id=row["shop_id"],
                    event_type=f"worker_{row['command']}_dispatch_failed",
                    status="failed",
                    summary=f"Worker command dispatch failed: {exc.__class__.__name__}",
                    trace_id=row["trace_id"],
                )
                conn.commit()
                return True
            self._mark_command(conn, row["id"], "succeeded", finished_at=utc_now_iso())
            self._record_event(
                conn,
                shop_id=row["shop_id"],
                event_type=f"worker_{row['command']}_dispatched",
                status="succeeded",
                summary=f"Worker command dispatched by Worker Manager: {row['command']}",
                trace_id=row["trace_id"],
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def run_forever(self, *, interval: float = 3.0) -> None:
        while True:
            self.run_once()
            time.sleep(interval)

    def _dispatch_command(self, command: str) -> None:
        if command == "start":
            self._start_worker()
            return
        if command == "stop":
            self._stop_worker()
            return
        if command == "restart":
            self._stop_worker()
            self._start_worker()
            return
        raise ValueError(f"unsupported_worker_command:{command}")

    def _start_worker(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.config.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        if self.config.stop_file.exists():
            self.config.stop_file.unlink()
        env = os.environ.copy()
        env.update(
            {
                "WEB_API_SQLITE_DB_PATH": str(self.config.db_path),
                "DB_PATH": str(self.config.db_path),
                "DATA_DIR": str(self.config.db_path.parent),
                "WORKER_STATUS_PATH": str(self.config.status_file),
                "LOG_DIR": str(self.config.log_dir),
            }
        )
        command = [
            self.config.python_executable,
            "-m",
            "runtime.worker",
            "--all-enabled",
            "--status-interval",
            str(self.config.status_interval),
            "--stop-file",
            str(self.config.stop_file),
        ]
        self.process = self.process_launcher(command, env, self.repo_root)

    def _stop_worker(self) -> None:
        self.config.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.stop_file.touch()
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except Exception:
                self.process.kill()

    @staticmethod
    def _mark_command(
        conn: sqlite3.Connection,
        command_id: str,
        status: str,
        *,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_type: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        updates = ["status=?"]
        values: list[Any] = [status]
        if started_at is not None:
            updates.append("started_at=?")
            values.append(started_at)
        if finished_at is not None:
            updates.append("finished_at=?")
            values.append(finished_at)
        if error_type is not None:
            updates.append("error_type=?")
            values.append(error_type)
        if error_summary is not None:
            updates.append("error_summary=?")
            values.append(error_summary)
        values.append(command_id)
        conn.execute(f"UPDATE worker_control_commands SET {', '.join(updates)} WHERE id=?", values)

    @staticmethod
    def _record_event(
        conn: sqlite3.Connection,
        *,
        shop_id: str,
        event_type: str,
        status: str,
        summary: str,
        trace_id: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO worker_events (id, shop_id, event_type, status, summary, metadata_json, created_at, trace_id)
            VALUES (?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (f"worker-event-{uuid.uuid4().hex[:16]}", shop_id, event_type, status, summary, utc_now_iso(), trace_id),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m runtime.worker_manager")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--status-file", default="temp/runtime/worker_status.json")
    parser.add_argument("--stop-file", default="runtime.stop")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--status-interval", type=float, default=5.0)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manager = WorkerManager(
        WorkerManagerConfig(
            db_path=Path(args.db_path),
            status_file=Path(args.status_file),
            stop_file=Path(args.stop_file),
            log_dir=Path(args.log_dir),
            python_executable=args.python,
            status_interval=args.status_interval,
        )
    )
    if args.once:
        return 0 if manager.run_once() else 2
    manager.run_forever(interval=args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
