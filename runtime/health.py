"""Minimal in-process health helpers for the headless worker."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _stringify_path(path: Any) -> str:
    if path is None:
        return ""
    return str(path)


def _safe_account(account_key: str, account: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "account_key": account_key,
        "channel_name": account.get("channel_name", ""),
        "shop_id": account.get("shop_id", ""),
        "user_id": account.get("user_id", ""),
        "username": account.get("username", ""),
        "status": account.get("status", ""),
        "state": account.get("state", ""),
        "error_type": account.get("error_type", ""),
        "error_summary": account.get("error_summary", ""),
    }


def _error_summary(error: Any) -> Dict[str, str]:
    if not error:
        return {"error_type": "", "error_summary": ""}
    text = str(error)
    if ":" in text:
        error_type, summary = text.split(":", 1)
        return {"error_type": error_type.strip(), "error_summary": summary.strip()[:240]}
    return {"error_type": "error", "error_summary": text[:240]}


def build_status_snapshot(
    status_manager: Any,
    worker_state: Any = None,
    app_env: str = "",
    status_file_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a serializable status snapshot without starting an HTTP service."""
    now = time.time()
    statuses = status_manager.get_all_status() if status_manager else []
    connections: List[Dict[str, Any]] = []
    for status in statuses:
        state = getattr(status, "state", None)
        connections.append(
            {
                "shop_id": getattr(status, "shop_id", ""),
                "user_id": getattr(status, "user_id", ""),
                "username": getattr(status, "username", ""),
                "state": getattr(state, "value", str(state)) if state is not None else "",
                "error_count": getattr(status, "error_count", 0),
                "reconnect_count": getattr(status, "reconnect_count", 0),
            }
        )

    channels = getattr(worker_state, "channels", {}) if worker_state else {}
    tasks = getattr(worker_state, "tasks", {}) if worker_state else {}
    running_accounts = getattr(worker_state, "running_accounts", set()) if worker_state else set()
    failed_accounts = getattr(worker_state, "failed_accounts", set()) if worker_state else set()
    stopped_accounts = getattr(worker_state, "stopped_accounts", set()) if worker_state else set()
    account_errors = getattr(worker_state, "account_errors", {}) if worker_state else {}
    started_at = getattr(worker_state, "started_at", None) if worker_state else None
    shutdown_started_at = getattr(worker_state, "shutdown_started_at", None) if worker_state else None
    shutdown_completed_at = getattr(worker_state, "shutdown_completed_at", None) if worker_state else None
    exit_reason = getattr(worker_state, "exit_reason", "") if worker_state else ""
    shutdown_requested = getattr(worker_state, "shutdown_requested", False) if worker_state else False
    shutdown_reason = getattr(worker_state, "shutdown_reason", "") if worker_state else ""
    shutdown_timeout = getattr(worker_state, "shutdown_timeout", 0) if worker_state else 0
    worker_id = getattr(worker_state, "worker_id", "") if worker_state else ""
    state_app_env = getattr(worker_state, "app_env", "") if worker_state else ""
    state_status_file_path = getattr(worker_state, "status_file_path", None) if worker_state else None
    accounts_by_key = getattr(worker_state, "accounts", {}) if worker_state else {}
    status_path = status_file_path or state_status_file_path
    is_final_snapshot = bool(shutdown_completed_at)
    is_shutting_down = bool(shutdown_started_at or shutdown_requested)
    if is_final_snapshot:
        worker_state_name = "stopped"
        snapshot_phase = "final"
    elif is_shutting_down:
        worker_state_name = "shutting_down"
        snapshot_phase = "shutting_down"
    else:
        worker_state_name = "running"
        snapshot_phase = "running"

    account_items: List[Dict[str, Any]] = []
    for account_key, account in accounts_by_key.items():
        safe = _safe_account(account_key, account)
        if is_final_snapshot and account_key not in failed_accounts:
            safe["state"] = "stopped"
        elif account_key in running_accounts:
            safe["state"] = safe["state"] or "running"
        elif account_key in failed_accounts:
            safe["state"] = safe["state"] or "failed"
        elif account_key in stopped_accounts:
            safe["state"] = safe["state"] or "stopped"
        if account_key in account_errors:
            safe.update(_error_summary(account_errors.get(account_key)))
        account_items.append(safe)

    if is_final_snapshot:
        for connection in connections:
            if connection.get("state") == "connected":
                connection["state"] = "disconnected"
        connected_count = 0
    else:
        connected_count = status_manager.get_connected_count() if status_manager else 0

    return {
        "schema_version": 1,
        "worker_id": worker_id,
        "pid": os.getpid(),
        "app_env": app_env or state_app_env,
        "snapshot_phase": snapshot_phase,
        "worker_state": worker_state_name,
        "started_at": started_at,
        "updated_at": now,
        "uptime_seconds": round(now - started_at, 3) if started_at else 0,
        "shutdown_requested": shutdown_requested,
        "shutdown_reason": shutdown_reason,
        "shutdown_started_at": shutdown_started_at,
        "shutdown_completed_at": shutdown_completed_at,
        "exit_reason": exit_reason,
        "connected_count": connected_count,
        "connection_count": len(connections),
        "connections": connections,
        "account_count": len(accounts_by_key) if accounts_by_key else len(channels),
        "accounts": sorted(account_items, key=lambda item: item.get("account_key", "")),
        "running_accounts": sorted(running_accounts),
        "failed_accounts": sorted(failed_accounts),
        "stopped_accounts": sorted(stopped_accounts),
        "account_errors": {key: _error_summary(value) for key, value in account_errors.items()},
        "channel_ids": dict(getattr(worker_state, "channel_ids", {}) if worker_state else {}),
        "task_ids": dict(getattr(worker_state, "account_task_ids", {}) if worker_state else {}),
        "shutdown_timeout": shutdown_timeout,
        "status_file_path": _stringify_path(status_path),
    }
