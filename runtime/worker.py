"""Headless worker entrypoint for headless PDD account runtime startup."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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
    parser.add_argument("--all-enabled", action="store_true", help="Select all candidate accounts with status == 1.")
    parser.add_argument("--shop-id", help="Platform shop id for a single account.")
    parser.add_argument("--user-id", help="User id for a single account.")
    parser.add_argument("--run-seconds", type=float, help="Request graceful shutdown after N seconds.")
    parser.add_argument("--stop-file", help="Request graceful shutdown when this file exists.")
    parser.add_argument("--shutdown-timeout", type=float, default=10.0, help="Seconds to wait for graceful shutdown.")
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


def _make_callbacks(account: dict, state: Optional[WorkerState] = None):
    account_key = _account_key(account)

    def on_success() -> None:
        if state:
            state.running_accounts.add(account_key)
        _emit(
            "worker.account.started",
            **_account_log_fields(account),
        )

    def on_failure(error: str) -> None:
        if state:
            _record_account_error(state, account_key, str(error))
        _emit(
            "worker.account.failed",
            **_account_log_fields(account),
            error_type=type(error).__name__,
            error=str(error),
        )

    return on_success, on_failure


async def _run_account_task(account: dict, stop_event: asyncio.Event, state: WorkerState) -> None:
    from Channel.pinduoduo.pdd_channel import PDDChannel

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

    channel = PDDChannel()
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
        _emit("worker.account.stopped", **_account_log_fields(account), channel_id=id(channel))


async def _stop_channel(account_key: str, channel: Any, state: WorkerState, timeout: float = 10.0) -> None:
    _emit("worker.shutdown.account_stopping", account_key=account_key, channel_id=id(channel), timeout=timeout)
    try:
        await asyncio.wait_for(channel.stop_all_connections(), timeout=timeout)
        state.stopped_accounts.add(account_key)
        state.running_accounts.discard(account_key)
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
    run_seconds: Optional[float] = None,
    stop_file: Optional[str] = None,
    shutdown_timeout: float = 10.0,
) -> int:
    state = WorkerState(
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
    )
    _install_stop_handlers(stop_event, state=state)
    _emit("worker.started", started_at=state.started_at)
    _emit(
        "worker.accounts.starting",
        count=len(accounts),
        candidate_rule="channel_name=pinduoduo,status=1",
        candidate_note="status==1 is candidate-startable only, not durable auto_reply_enabled",
    )

    for account in accounts:
        account_key = _account_key(account)
        task = asyncio.create_task(_run_account_task(account, stop_event, state), name=f"worker.account.{account_key}")
        state.tasks[account_key] = task
        state.account_task_ids[account_key] = id(task)
        _emit("worker.account.task.created", **_account_log_fields(account), task_id=id(task))

    if not state.tasks:
        _emit("worker.accounts.loaded", count=0)
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
    return _exit_code_for_reason(state.shutdown_reason or state.exit_reason)


async def _run_single_account(
    context: RuntimeContext,
    account: dict,
    run_seconds: Optional[float] = None,
    stop_file: Optional[str] = None,
    shutdown_timeout: float = 10.0,
) -> int:
    stop_event = asyncio.Event()
    return await _run_accounts(
        [account],
        stop_event,
        run_seconds=run_seconds,
        stop_file=stop_file,
        shutdown_timeout=shutdown_timeout,
    )


async def _run_all_enabled(
    accounts: List[dict],
    run_seconds: Optional[float] = None,
    stop_file: Optional[str] = None,
    shutdown_timeout: float = 10.0,
) -> int:
    stop_event = asyncio.Event()
    return await _run_accounts(
        accounts,
        stop_event,
        run_seconds=run_seconds,
        stop_file=stop_file,
        shutdown_timeout=shutdown_timeout,
    )


async def run_async(parsed: argparse.Namespace) -> int:
    context = initialize_runtime()

    if parsed.status:
        snapshot = build_status_snapshot(context.status_manager)
        _emit("worker.status", payload=json.dumps(snapshot, ensure_ascii=False))
        if not (parsed.dry_run or parsed.all_enabled or parsed.shop_id or parsed.user_id):
            _emit("worker.exiting", code=0)
            return 0

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
            _emit("worker.dry_run", websocket_start="disabled", connect_called=False)
        elif not accounts:
            _emit("worker.accounts.loaded", count=0, websocket_start="disabled")
        else:
            code = await _run_all_enabled(
                accounts,
                run_seconds=parsed.run_seconds,
                stop_file=parsed.stop_file,
                shutdown_timeout=parsed.shutdown_timeout,
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
