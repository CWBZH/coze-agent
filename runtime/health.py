"""Minimal in-process health helpers for the headless worker."""
from __future__ import annotations

import time
from typing import Any, Dict, List


def build_status_snapshot(status_manager: Any, worker_state: Any = None) -> Dict[str, Any]:
    """Build a serializable status snapshot without starting an HTTP service."""
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
    exit_reason = getattr(worker_state, "exit_reason", "") if worker_state else ""
    shutdown_requested = getattr(worker_state, "shutdown_requested", False) if worker_state else False
    shutdown_reason = getattr(worker_state, "shutdown_reason", "") if worker_state else ""
    shutdown_timeout = getattr(worker_state, "shutdown_timeout", 0) if worker_state else 0

    return {
        "connected_count": status_manager.get_connected_count() if status_manager else 0,
        "connection_count": len(connections),
        "connections": connections,
        "account_count": len(channels),
        "running_accounts": sorted(running_accounts),
        "failed_accounts": sorted(failed_accounts),
        "stopped_accounts": sorted(stopped_accounts),
        "account_errors": dict(account_errors),
        "channel_ids": dict(getattr(worker_state, "channel_ids", {}) if worker_state else {}),
        "task_ids": dict(getattr(worker_state, "account_task_ids", {}) if worker_state else {}),
        "exit_reason": exit_reason,
        "uptime_seconds": round(time.time() - started_at, 3) if started_at else 0,
        "shutdown_requested": shutdown_requested,
        "shutdown_reason": shutdown_reason,
        "shutdown_timeout": shutdown_timeout,
    }
