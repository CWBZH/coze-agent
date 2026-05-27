"""Opt-in local private trace writer for manual QA.

Normal logs and artifacts stay metadata-only. This module writes full prompts,
messages, retrieved content, and replies only when explicitly enabled with
``AI_WORKFLOW_DEBUG_TRACE=1``. Files are local private diagnostics under
``temp/debug_traces`` by default and should not be committed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SECRET_KEY_RE = re.compile(r"(token|cookie|access_token|authorization|api[_-]?key|secret|password|dsn)", re.I)


def private_trace_enabled() -> bool:
    return str(os.environ.get("AI_WORKFLOW_DEBUG_TRACE", "")).strip().lower() in {"1", "true", "yes", "on"}


def write_private_trace(trace_id: str, event: str, payload: dict[str, Any]) -> Path | None:
    if not private_trace_enabled():
        return None
    root = _debug_trace_dir()
    root.mkdir(parents=True, exist_ok=True)
    safe_id = _safe_trace_id(trace_id)
    path = root / f"{safe_id}.json"
    document: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                document = loaded
        except Exception:
            document = {}
    document.setdefault("trace_id", str(trace_id or "missing-trace"))
    document["updated_at"] = datetime.now(timezone.utc).isoformat()
    events = document.setdefault("events", {})
    if not isinstance(events, dict):
        events = {}
        document["events"] = events
    events[str(event or "event")] = _sanitize(payload)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def _debug_trace_dir() -> Path:
    configured = os.environ.get("AI_WORKFLOW_DEBUG_TRACE_DIR", "")
    root = Path(configured) if configured else Path("temp") / "debug_traces"
    root = root.expanduser()
    if root.is_absolute():
        return root
    return Path.cwd() / root


def _safe_trace_id(trace_id: str) -> str:
    value = str(trace_id or "missing-trace").strip() or "missing-trace"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:160]


def _sanitize(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY_RE.search(str(key or "")):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _sanitize_text(str(value))


def _sanitize_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._\-]+", "Bearer <redacted>", value)
    value = re.sub(
        r"(?i)(token|cookie|access_token|authorization|api_key|secret|password)\s*[:=]\s*[^,\s]+",
        r"\1=<redacted>",
        value,
    )
    value = re.sub(r"ark-[A-Za-z0-9._\-]+", "ark-<redacted>", value)
    value = re.sub(r"fastgpt-[A-Za-z0-9._\-]+", "fastgpt-<redacted>", value)
    value = re.sub(r"postgresql://[^\s]+", "postgresql://<redacted>", value)
    return value
