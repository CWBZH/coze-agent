"""Headless worker entrypoint for headless PDD account runtime startup."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from runtime.account_loader import load_account, load_candidate_accounts
from runtime.health import build_status_snapshot


INTERRUPT_EXIT_CODE = 130
INTERRUPT_REASONS = {"SIGINT", "KeyboardInterrupt", "keyboard_interrupt"}


@dataclass
class RuntimeContext:
    settings: Any
    db_manager: Any
    status_manager: Any


@dataclass
class WorkerState:
    worker_id: str
    app_env: str
    status_file_path: Path
    status_manager: Any
    started_at: float
    shutdown_started_at: Optional[float]
    shutdown_completed_at: Optional[float]
    shutdown_requested: bool
    shutdown_reason: str
    shutdown_timeout: float
    exit_reason: str
    channels: Dict[str, Any]
    tasks: Dict[str, asyncio.Task]
    running_accounts: Set[str]
    failed_accounts: Set[str]
    stopped_accounts: Set[str]
    account_errors: Dict[str, str]
    account_task_ids: Dict[str, int]
    channel_ids: Dict[str, int]
    accounts: Dict[str, Dict[str, Any]]
    status_write_tasks: Set[asyncio.Task]


def _emit(event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    print(" ".join(parts))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m runtime.worker",
        description="Headless worker for customer-agent-refactor-v3.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List target accounts without starting WebSocket.")
    parser.add_argument("--status", action="store_true", help="Print in-process runtime status snapshot.")
    parser.add_argument("--healthcheck", action="store_true", help="Check worker health from the status JSON file.")
    parser.add_argument("--all-enabled", action="store_true", help="Select all candidate accounts with status == 1.")
    parser.add_argument("--shop-id", help="Platform shop id for a single account.")
    parser.add_argument("--user-id", help="User id for a single account.")
    parser.add_argument("--run-seconds", type=float, help="Request graceful shutdown after N seconds.")
    parser.add_argument("--stop-file", help="Request graceful shutdown when this file exists.")
    parser.add_argument("--shutdown-timeout", type=float, default=10.0, help="Seconds to wait for graceful shutdown.")
    parser.add_argument("--status-interval", type=float, default=5.0, help="Seconds between worker status file writes.")
    parser.add_argument("--status-file", help="Read worker status from this JSON file when using --status.")
    parser.add_argument("--status-stale-seconds", type=float, default=30.0, help="Seconds before a running status file is considered stale.")
    parser.add_argument("--json", action="store_true", help="Output status as JSON when using --status.")
    return parser


def initialize_runtime() -> RuntimeContext:
    """Initialize settings, DI, DB, and status manager for headless mode."""
    os.environ["HEADLESS_MODE"] = "1"

    from core import settings
    from core.connection_status import ConnectionStatusManager
    from core.di_container import configure_standard_services, container
    from database.db_manager import DatabaseManager

    _emit("worker.starting")
    configure_standard_services()
    db_manager = container.get(DatabaseManager)
    status_manager = container.get(ConnectionStatusManager)
    _emit(
        "worker.config.loaded",
        APP_ENV=settings.APP_ENV,
        DB_PATH=settings.db_path(),
        LOG_DIR=settings.log_dir(),
        WORKER_STATUS_PATH=settings.worker_status_path(),
        HEADLESS_MODE=os.getenv("HEADLESS_MODE", ""),
    )
    _emit("worker.db.ready", db_manager_id=id(db_manager))
    return RuntimeContext(settings=settings, db_manager=db_manager, status_manager=status_manager)


def resolve_accounts(args: argparse.Namespace, db_manager: Any) -> List[dict]:
    if args.shop_id or args.user_id:
        if not args.shop_id or not args.user_id:
            raise ValueError("--shop-id and --user-id must be provided together")
        account = load_account(db_manager, args.shop_id, args.user_id)
        return [account] if account else []

    if args.all_enabled or args.dry_run:
        return load_candidate_accounts(db_manager)

    return []


def print_accounts(accounts: List[dict]) -> None:
    _emit("worker.accounts.loaded", count=len(accounts))
    for account in accounts:
        _emit(
            "worker.account",
            channel_name=account.get("channel_name", ""),
            shop_id=account.get("shop_id", ""),
            user_id=account.get("user_id", ""),
            username=account.get("username", ""),
            status=account.get("status", ""),
        )


def _safe_status_account(account: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "account_key": account.get("account_key", ""),
        "channel_name": account.get("channel_name", ""),
        "shop_id": account.get("shop_id", ""),
        "user_id": account.get("user_id", ""),
        "username": account.get("username", ""),
        "status": account.get("status", ""),
        "state": account.get("state", ""),
        "error_type": account.get("error_type", ""),
        "error_summary": account.get("error_summary", ""),
    }


def _safe_status_connection(connection: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "shop_id": connection.get("shop_id", ""),
        "user_id": connection.get("user_id", ""),
        "username": connection.get("username", ""),
        "state": connection.get("state", ""),
        "error_count": connection.get("error_count", 0),
        "reconnect_count": connection.get("reconnect_count", 0),
    }


def _normalize_status_payload(payload: Dict[str, Any], status_file_path: Path) -> Dict[str, Any]:
    normalized = {
        "schema_version": payload.get("schema_version", 1),
        "worker_id": payload.get("worker_id", ""),
        "pid": payload.get("pid", ""),
        "app_env": payload.get("app_env", ""),
        "snapshot_phase": payload.get("snapshot_phase", ""),
        "worker_state": payload.get("worker_state", ""),
        "started_at": payload.get("started_at"),
        "updated_at": payload.get("updated_at"),
        "uptime_seconds": payload.get("uptime_seconds", 0),
        "shutdown_requested": payload.get("shutdown_requested", False),
        "shutdown_reason": payload.get("shutdown_reason", ""),
        "shutdown_started_at": payload.get("shutdown_started_at"),
        "shutdown_completed_at": payload.get("shutdown_completed_at"),
        "exit_reason": payload.get("exit_reason", ""),
        "connected_count": payload.get("connected_count", 0),
        "connection_count": payload.get("connection_count", 0),
        "account_count": payload.get("account_count", 0),
        "running_accounts": payload.get("running_accounts", []),
        "failed_accounts": payload.get("failed_accounts", []),
        "stopped_accounts": payload.get("stopped_accounts", []),
        "account_errors": payload.get("account_errors", {}),
        "channel_ids": payload.get("channel_ids", {}),
        "task_ids": payload.get("task_ids", {}),
        "status_file_path": str(status_file_path),
    }
    normalized["accounts"] = [
        _safe_status_account(account)
        for account in payload.get("accounts", [])
        if isinstance(account, dict)
    ]
    normalized["connections"] = [
        _safe_status_connection(connection)
        for connection in payload.get("connections", [])
        if isinstance(connection, dict)
    ]
    return normalized


def _computed_status(payload: Dict[str, Any], stale_seconds: float, now: Optional[float] = None) -> str:
    if payload.get("shutdown_completed_at"):
        return "stopped"
    updated_at = payload.get("updated_at")
    try:
        updated_at_float = float(updated_at)
    except (TypeError, ValueError):
        return "stale"
    current = time.time() if now is None else now
    if stale_seconds >= 0 and current - updated_at_float > stale_seconds:
        return "stale"
    return "running"


def _print_status_payload(payload: Dict[str, Any]) -> None:
    for key in (
        "status_file_path",
        "computed_status",
        "worker_id",
        "pid",
        "worker_state",
        "snapshot_phase",
        "app_env",
        "updated_at",
        "uptime_seconds",
        "connected_count",
        "account_count",
        "running_accounts",
        "failed_accounts",
        "stopped_accounts",
        "exit_reason",
    ):
        _emit("worker.status", **{key: payload.get(key, "")})


def _load_status_file(status_file_path: Path, stale_seconds: float) -> tuple[int, Dict[str, Any]]:
    if not status_file_path.exists():
        return 2, {
            "computed_status": "missing",
            "worker_status": "missing",
            "status_file_path": str(status_file_path),
        }

    try:
        raw_payload = json.loads(status_file_path.read_text(encoding="utf-8"))
        if not isinstance(raw_payload, dict):
            raise ValueError("status JSON root must be an object")
    except Exception as exc:
        return 3, {
            "computed_status": "invalid",
            "worker_status": "invalid",
            "status_file_path": str(status_file_path),
            "error_type": type(exc).__name__,
        }

    payload = _normalize_status_payload(raw_payload, status_file_path)
    computed_status = _computed_status(payload, stale_seconds)
    payload["computed_status"] = computed_status
    payload["worker_status"] = computed_status
    return (4 if computed_status == "stale" else 0), payload


def _read_status_file(status_file_path: Path, stale_seconds: float, json_output: bool = False) -> int:
    code, payload = _load_status_file(status_file_path, stale_seconds)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        if code == 2:
            _emit("worker.status", worker_status="missing", status_file_path=status_file_path)
        elif code == 3:
            _emit(
                "worker.status",
                worker_status="invalid",
                status_file_path=status_file_path,
                error_type=payload.get("error_type", ""),
            )
        else:
            _print_status_payload(payload)
    return code


def _health_status(payload: Dict[str, Any]) -> str:
    computed_status = payload.get("computed_status", "")
    if computed_status in {"missing", "invalid", "stale", "stopped"}:
        return computed_status
    if computed_status != "running":
        return "degraded"
    failed_accounts = payload.get("failed_accounts") or []
    running_accounts = payload.get("running_accounts") or []
    if failed_accounts:
        return "degraded"
    if not running_accounts:
        return "degraded"
    return "healthy"


def _health_exit_code(health_status: str) -> int:
    return {
        "healthy": 0,
        "degraded": 1,
        "missing": 2,
        "invalid": 3,
        "stale": 4,
        "stopped": 5,
    }.get(health_status, 1)


def _print_health_payload(payload: Dict[str, Any]) -> None:
    for key in (
        "health_status",
        "computed_status",
        "worker_state",
        "snapshot_phase",
        "updated_at",
        "connected_count",
        "account_count",
        "running_count",
        "failed_count",
        "stopped_count",
        "exit_reason",
        "status_file_path",
    ):
        _emit("worker.healthcheck", **{key: payload.get(key, "")})


def _healthcheck_status_file(status_file_path: Path, stale_seconds: float, json_output: bool = False) -> int:
    _, payload = _load_status_file(status_file_path, stale_seconds)
    health_status = _health_status(payload)
    code = _health_exit_code(health_status)
    payload["health_status"] = health_status
    payload["exit_code"] = code
    payload["running_count"] = len(payload.get("running_accounts") or [])
    payload["failed_count"] = len(payload.get("failed_accounts") or [])
    payload["stopped_count"] = len(payload.get("stopped_accounts") or [])
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        _print_health_payload(payload)
    return code


def request_shutdown(state: WorkerState, stop_event: asyncio.Event, reason: str) -> bool:
    if state.shutdown_requested:
        _emit(
            "worker.shutdown.already_requested",
            reason=reason,
            original_reason=state.shutdown_reason,
        )
        return False

    state.shutdown_requested = True
    state.shutdown_reason = reason
    state.exit_reason = reason
    _emit("worker.shutdown.requested", reason=reason)
    stop_event.set()
    return True


def _exit_code_for_reason(reason: str) -> int:
    return INTERRUPT_EXIT_CODE if reason in INTERRUPT_REASONS else 0


async def _write_status_snapshot(state: WorkerState) -> bool:
    path = Path(state.status_file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = build_status_snapshot(
            state.status_manager,
            worker_state=state,
            app_env=state.app_env,
            status_file_path=path,
        )
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
        _emit("worker.status_writer.wrote", path=path, updated_at=snapshot.get("updated_at", ""))
        return True
    except Exception as exc:
        _emit("worker.status_writer.failed", path=path, error_type=type(exc).__name__, error=str(exc))
        return False


def _schedule_status_write(state: WorkerState) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_write_status_snapshot(state), name="worker.status_write.once")
    state.status_write_tasks.add(task)
    task.add_done_callback(state.status_write_tasks.discard)


async def _status_writer_loop(state: WorkerState, interval: float) -> None:
    _emit("worker.status_writer.started", path=state.status_file_path, interval=interval)
    stop_reason = "exited"
    try:
        while True:
            await _write_status_snapshot(state)
            if state.shutdown_completed_at is not None:
                break
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        stop_reason = "cancelled"
        raise
    except Exception as exc:
        stop_reason = "failed"
        _emit("worker.status_writer.failed", path=state.status_file_path, error_type=type(exc).__name__, error=str(exc))
    finally:
        _emit("worker.status_writer.stopped", path=state.status_file_path, reason=stop_reason)


def _install_stop_handlers(stop_event: asyncio.Event, state: WorkerState) -> None:
    loop = asyncio.get_running_loop()
    registered: Dict[str, List[str]] = {}

    def request_stop(signame: str) -> None:
        _emit("worker.shutdown.signal_received", signal=signame)
        if loop.is_running():
            loop.call_soon_threadsafe(request_shutdown, state, stop_event, signame)
        else:
            request_shutdown(state, stop_event, signame)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop, sig.name)
            registered.setdefault("loop_add_signal_handler", []).append(sig.name)
        except (NotImplementedError, RuntimeError, ValueError):
            try:
                def fallback_handler(signum, frame, signame=sig.name):
                    request_stop(signame)

                signal.signal(sig, fallback_handler)
                registered.setdefault("signal_signal", []).append(sig.name)
            except (ValueError, OSError, RuntimeError):
                registered.setdefault("fallback", []).append(sig.name)
                _emit("worker.signal.unsupported", signal=sig.name)

    for backend, signals in registered.items():
        _emit("worker.signal.handlers_registered", backend=backend, signals=",".join(signals))


def _account_key(account: dict) -> str:
    return f"{account.get('shop_id', '')}_{account.get('user_id', '')}"


def _account_log_fields(account: dict) -> Dict[str, Any]:
    return {
        "account_key": _account_key(account),
        "channel_name": account.get("channel_name", ""),
        "shop_id": account.get("shop_id", ""),
        "user_id": account.get("user_id", ""),
        "username": account.get("username", ""),
        "status": account.get("status", ""),
    }


def _record_account_error(state: WorkerState, account_key: str, error: str) -> None:
    state.failed_accounts.add(account_key)
    state.running_accounts.discard(account_key)
    state.account_errors[account_key] = error
    account = state.accounts.get(account_key)
    if account is not None:
        account["state"] = "failed"
        if ":" in error:
            error_type, summary = error.split(":", 1)
            account["error_type"] = error_type.strip()
            account["error_summary"] = summary.strip()[:240]
        else:
            account["error_type"] = "error"
            account["error_summary"] = error[:240]


def _make_callbacks(account: dict, state: Optional[WorkerState] = None):
    account_key = _account_key(account)

    def on_success() -> None:
        if state:
            state.running_accounts.add(account_key)
            account = state.accounts.get(account_key)
            if account is not None:
                account["state"] = "running"
            _schedule_status_write(state)
        _emit(
            "worker.account.started",
            **_account_log_fields(account),
        )

    def on_failure(error: str) -> None:
        if state:
            _record_account_error(state, account_key, str(error))
            _schedule_status_write(state)
        _emit(
            "worker.account.failed",
            **_account_log_fields(account),
            error_type=type(error).__name__,
            error=str(error),
        )

    return on_success, on_failure


async def _run_account_task(
    account: dict,
    stop_event: asyncio.Event,
    state: WorkerState,
    channel_factory: Optional[Callable[[], Any]] = None,
) -> None:
    account_key = _account_key(account)
    _emit(
        "worker.account.task.started",
        **_account_log_fields(account),
        task_id=state.account_task_ids.get(account_key, ""),
    )
    _emit(
        "worker.account.starting",
        **_account_log_fields(account),
    )

    if channel_factory is None:
        from Channel.pinduoduo.pdd_channel import PDDChannel
        channel_factory = PDDChannel

    channel = channel_factory()
    state.channels[account_key] = channel
    state.channel_ids[account_key] = id(channel)
    on_success, on_failure = _make_callbacks(account, state=state)
    try:
        await channel.start_account(
            shop_id=account["shop_id"],
            user_id=account["user_id"],
            on_success=on_success,
            on_failure=on_failure,
        )
        _emit("worker.waiting", account_key=account_key, channel_id=id(channel))
        await stop_event.wait()
        state.stopped_accounts.add(account_key)
        state.running_accounts.discard(account_key)
        account = state.accounts.get(account_key)
        if account is not None:
            account["state"] = "stopped"
        _emit(
            "worker.account.task.completed",
            **_account_log_fields(account),
            task_id=state.account_task_ids.get(account_key, ""),
        )
    except asyncio.CancelledError:
        state.running_accounts.discard(account_key)
        _emit(
            "worker.account.task.cancelled",
            **_account_log_fields(account),
            task_id=state.account_task_ids.get(account_key, ""),
            shutdown_requested=state.shutdown_requested,
        )
        if state.shutdown_requested:
            return
        raise
    except KeyboardInterrupt:
        _emit("worker.shutdown.signal_received", signal="KeyboardInterrupt")
        request_shutdown(state, stop_event, "keyboard_interrupt")
    except Exception as exc:
        _record_account_error(state, account_key, f"{type(exc).__name__}: {exc}")
        _emit(
            "worker.account.task.failed",
            **_account_log_fields(account),
            task_id=state.account_task_ids.get(account_key, ""),
            error_type=type(exc).__name__,
            error=str(exc),
        )
    finally:
        account_record = state.accounts.get(account_key)
        if account_record is not None and account_key not in state.failed_accounts:
            account_record["state"] = "stopped"
        _schedule_status_write(state)
        _emit("worker.account.stopped", **_account_log_fields(account), channel_id=id(channel))


async def _stop_channel(account_key: str, channel: Any, state: WorkerState, timeout: float = 10.0) -> None:
    _emit("worker.shutdown.account_stopping", account_key=account_key, channel_id=id(channel), timeout=timeout)
    try:
        await asyncio.wait_for(channel.stop_all_connections(), timeout=timeout)
        state.stopped_accounts.add(account_key)
        state.running_accounts.discard(account_key)
        account = state.accounts.get(account_key)
        if account is not None:
            account["state"] = "stopped"
        _schedule_status_write(state)
        _emit("worker.shutdown.account_stopped", account_key=account_key, channel_id=id(channel))
    except asyncio.TimeoutError:
        state.account_errors[account_key] = f"stop_timeout:{timeout}"
        _emit("worker.shutdown.account_stop_timeout", account_key=account_key, channel_id=id(channel), timeout=timeout)
        _emit("worker.shutdown.timeout", phase="account_stop", account_key=account_key, timeout=timeout)
    except Exception as exc:
        state.account_errors[account_key] = f"{type(exc).__name__}: {exc}"
        _emit(
            "worker.shutdown.account_stop_failed",
            account_key=account_key,
            channel_id=id(channel),
            error_type=type(exc).__name__,
            error=str(exc),
        )


async def _shutdown_accounts(state: WorkerState, stop_event: asyncio.Event, timeout: float = 10.0) -> None:
    state.shutdown_started_at = time.time()
    state.shutdown_timeout = timeout
    if not state.shutdown_requested:
        request_shutdown(state, stop_event, state.exit_reason or "shutdown_requested")
    _emit("worker.shutdown.started", account_count=len(state.channels), task_count=len(state.tasks), timeout=timeout)

    stop_jobs = [
        _stop_channel(account_key, channel, state, timeout=timeout)
        for account_key, channel in list(state.channels.items())
    ]
    if stop_jobs:
        try:
            await asyncio.wait_for(asyncio.gather(*stop_jobs, return_exceptions=True), timeout=timeout + 1.0)
        except asyncio.TimeoutError:
            _emit("worker.shutdown.timeout", phase="stop_channels", timeout=timeout + 1.0)
        except asyncio.CancelledError:
            if state.shutdown_requested:
                _emit("worker.shutdown.cancelled_error.handled", phase="stop_channels", reason=state.shutdown_reason)
            else:
                raise

    pending_tasks = [task for task in state.tasks.values() if not task.done()]
    if pending_tasks:
        try:
            await asyncio.wait_for(asyncio.gather(*pending_tasks, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            _emit("worker.shutdown.timeout", phase="account_tasks", timeout=timeout)
        except asyncio.CancelledError:
            if state.shutdown_requested:
                _emit("worker.shutdown.cancelled_error.handled", phase="account_tasks", reason=state.shutdown_reason)
            else:
                raise

    state.shutdown_completed_at = time.time()
    _emit(
        "worker.shutdown.completed",
        account_count=len(state.channels),
        task_count=len(state.tasks),
        running_count=len(state.running_accounts),
        failed_count=len(state.failed_accounts),
        stopped_count=len(state.stopped_accounts),
        exit_reason=state.exit_reason,
    )


async def _run_seconds_watch(state: WorkerState, stop_event: asyncio.Event, seconds: float) -> None:
    if seconds <= 0:
        request_shutdown(state, stop_event, "run_seconds_elapsed")
        _emit("worker.run_seconds.elapsed", seconds=seconds)
        return
    await asyncio.sleep(seconds)
    _emit("worker.run_seconds.elapsed", seconds=seconds)
    request_shutdown(state, stop_event, "run_seconds_elapsed")


async def _stop_file_watch(state: WorkerState, stop_event: asyncio.Event, stop_file: str) -> None:
    path = Path(stop_file)
    _emit("worker.stop_file.watching", path=path)
    while not stop_event.is_set():
        if path.exists():
            _emit("worker.stop_file.detected", path=path)
            request_shutdown(state, stop_event, "stop_file_detected")
            return
        await asyncio.sleep(1.0)


async def _run_accounts(
    accounts: List[dict],
    stop_event: asyncio.Event,
    status_manager: Any = None,
    app_env: str = "local",
    status_file_path: Optional[Path] = None,
    run_seconds: Optional[float] = None,
    stop_file: Optional[str] = None,
    shutdown_timeout: float = 10.0,
    status_interval: float = 5.0,
    channel_factory: Optional[Callable[[], Any]] = None,
) -> int:
    if status_file_path is None:
        from core import settings
        status_file_path = settings.worker_status_path()

    state = WorkerState(
        worker_id=uuid.uuid4().hex[:12],
        app_env=app_env,
        status_file_path=Path(status_file_path),
        status_manager=status_manager,
        started_at=time.time(),
        shutdown_started_at=None,
        shutdown_completed_at=None,
        shutdown_requested=False,
        shutdown_reason="",
        shutdown_timeout=shutdown_timeout,
        exit_reason="",
        channels={},
        tasks={},
        running_accounts=set(),
        failed_accounts=set(),
        stopped_accounts=set(),
        account_errors={},
        account_task_ids={},
        channel_ids={},
        accounts={},
        status_write_tasks=set(),
    )
    _install_stop_handlers(stop_event, state=state)
    _emit("worker.status_file.path", path=state.status_file_path)
    _emit("worker.started", started_at=state.started_at)
    _emit(
        "worker.accounts.starting",
        count=len(accounts),
        candidate_rule="channel_name=pinduoduo,status=1",
        candidate_note="status==1 is candidate-startable only, not durable auto_reply_enabled",
    )

    for account in accounts:
        account_key = _account_key(account)
        state.accounts[account_key] = dict(account)
        task = asyncio.create_task(
            _run_account_task(account, stop_event, state, channel_factory=channel_factory),
            name=f"worker.account.{account_key}",
        )
        state.tasks[account_key] = task
        state.account_task_ids[account_key] = id(task)
        _emit("worker.account.task.created", **_account_log_fields(account), task_id=id(task))

    await _write_status_snapshot(state)
    status_writer_task = None
    if status_interval > 0:
        status_writer_task = asyncio.create_task(
            _status_writer_loop(state, status_interval),
            name="worker.status_writer",
        )

    if not state.tasks:
        _emit("worker.accounts.loaded", count=0)
        state.exit_reason = state.exit_reason or "no_accounts"
        state.shutdown_completed_at = time.time()
        await _write_status_snapshot(state)
        if status_writer_task and not status_writer_task.done():
            status_writer_task.cancel()
            await asyncio.gather(status_writer_task, return_exceptions=True)
        return 0

    stop_wait_task = asyncio.create_task(stop_event.wait(), name="worker.stop_wait")
    control_tasks: List[asyncio.Task] = []
    if run_seconds is not None:
        control_tasks.append(asyncio.create_task(_run_seconds_watch(state, stop_event, run_seconds), name="worker.run_seconds"))
    if stop_file:
        control_tasks.append(asyncio.create_task(_stop_file_watch(state, stop_event, stop_file), name="worker.stop_file"))

    try:
        while not stop_event.is_set():
            running_tasks = [task for task in state.tasks.values() if not task.done()]
            if not running_tasks:
                if state.failed_accounts and len(state.failed_accounts) == len(state.tasks):
                    state.exit_reason = "all_accounts_failed"
                    request_shutdown(state, stop_event, "all_accounts_failed")
                    _emit("worker.accounts.failed", count=len(state.tasks), failed_count=len(state.failed_accounts))
                else:
                    state.exit_reason = state.exit_reason or "all_account_tasks_completed"
                    request_shutdown(state, stop_event, state.exit_reason)
                _emit("worker.accounts.completed", count=len(state.tasks), failed_count=len(state.failed_accounts))
                break
            await asyncio.wait([stop_wait_task, *running_tasks], return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        if state.shutdown_requested:
            _emit("worker.cancelled_error.handled", reason=state.shutdown_reason)
        else:
            request_shutdown(state, stop_event, "keyboard_interrupt")
            _emit("worker.cancelled_error.handled", reason="keyboard_interrupt")
    except KeyboardInterrupt:
        _emit("worker.shutdown.signal_received", signal="KeyboardInterrupt")
        request_shutdown(state, stop_event, "keyboard_interrupt")
    finally:
        for task in control_tasks:
            if not task.done():
                task.cancel()
        if control_tasks:
            await asyncio.gather(*control_tasks, return_exceptions=True)
        if not stop_wait_task.done():
            stop_wait_task.cancel()
            await asyncio.gather(stop_wait_task, return_exceptions=True)
        await _shutdown_accounts(state, stop_event, timeout=shutdown_timeout)
        await _write_status_snapshot(state)
        if state.status_write_tasks:
            await asyncio.gather(*list(state.status_write_tasks), return_exceptions=True)
        if status_writer_task and not status_writer_task.done():
            status_writer_task.cancel()
            await asyncio.gather(status_writer_task, return_exceptions=True)
    return _exit_code_for_reason(state.shutdown_reason or state.exit_reason)


async def _run_single_account(
    context: RuntimeContext,
    account: dict,
    run_seconds: Optional[float] = None,
    stop_file: Optional[str] = None,
    shutdown_timeout: float = 10.0,
    status_interval: float = 5.0,
) -> int:
    stop_event = asyncio.Event()
    return await _run_accounts(
        [account],
        stop_event,
        status_manager=context.status_manager,
        app_env=context.settings.APP_ENV,
        status_file_path=context.settings.worker_status_path(),
        run_seconds=run_seconds,
        stop_file=stop_file,
        shutdown_timeout=shutdown_timeout,
        status_interval=status_interval,
    )


async def _run_all_enabled(
    context: RuntimeContext,
    accounts: List[dict],
    run_seconds: Optional[float] = None,
    stop_file: Optional[str] = None,
    shutdown_timeout: float = 10.0,
    status_interval: float = 5.0,
) -> int:
    stop_event = asyncio.Event()
    return await _run_accounts(
        accounts,
        stop_event,
        status_manager=context.status_manager,
        app_env=context.settings.APP_ENV,
        status_file_path=context.settings.worker_status_path(),
        run_seconds=run_seconds,
        stop_file=stop_file,
        shutdown_timeout=shutdown_timeout,
        status_interval=status_interval,
    )


async def run_async(parsed: argparse.Namespace) -> int:
    if parsed.healthcheck:
        from core import settings

        status_file_path = Path(parsed.status_file) if parsed.status_file else settings.worker_status_path()
        code = _healthcheck_status_file(
            status_file_path=status_file_path,
            stale_seconds=parsed.status_stale_seconds,
            json_output=parsed.json,
        )
        if not parsed.json:
            _emit("worker.exiting", code=code)
        return code

    if parsed.status:
        from core import settings

        status_file_path = Path(parsed.status_file) if parsed.status_file else settings.worker_status_path()
        code = _read_status_file(
            status_file_path=status_file_path,
            stale_seconds=parsed.status_stale_seconds,
            json_output=parsed.json,
        )
        if not parsed.json:
            _emit("worker.exiting", code=code)
        return code

    context = initialize_runtime()

    accounts = resolve_accounts(parsed, context.db_manager)
    if parsed.all_enabled:
        _emit(
            "worker.accounts.candidate_rule",
            channel_name="pinduoduo",
            status=1,
            note="status==1 is candidate-startable only, not durable auto_reply_enabled",
        )

    if parsed.dry_run or parsed.all_enabled:
        print_accounts(accounts)
        if parsed.dry_run:
            _emit("worker.status_file.path", path=context.settings.worker_status_path())
            _emit("worker.dry_run", websocket_start="disabled", connect_called=False)
        elif not accounts:
            _emit("worker.accounts.loaded", count=0, websocket_start="disabled")
        else:
            code = await _run_all_enabled(
                context,
                accounts,
                run_seconds=parsed.run_seconds,
                stop_file=parsed.stop_file,
                shutdown_timeout=parsed.shutdown_timeout,
                status_interval=parsed.status_interval,
            )
            _emit("worker.exiting", code=code)
            return code
    elif parsed.shop_id or parsed.user_id:
        if not accounts:
            _emit(
                "worker.account.failed",
                shop_id=parsed.shop_id or "",
                user_id=parsed.user_id or "",
                reason="account_not_found",
            )
            _emit("worker.exiting", code=1)
            return 1
        code = await _run_single_account(
            context,
            accounts[0],
            run_seconds=parsed.run_seconds,
            stop_file=parsed.stop_file,
            shutdown_timeout=parsed.shutdown_timeout,
            status_interval=parsed.status_interval,
        )
        _emit("worker.exiting", code=code)
        return code
    else:
        _emit("worker.dry_run", websocket_start="disabled", reason="skeleton_default_no_connect")

    _emit("worker.exiting", code=0)
    return 0


def run(args: Optional[List[str]] = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(args)
    try:
        return asyncio.run(run_async(parsed))
    except KeyboardInterrupt:
        _emit("worker.keyboard_interrupt.handled")
        return INTERRUPT_EXIT_CODE
    except asyncio.CancelledError:
        _emit("worker.cancelled_error.handled", reason="outer_run")
        return INTERRUPT_EXIT_CODE


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
