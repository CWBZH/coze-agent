from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi.responses import JSONResponse


SENSITIVE_MARKERS = ("cookie", "token", "password", "authorization", "access_token", "api_key", "secret")


@dataclass
class ApiError(Exception):
    error_type: str
    error_summary: str
    status_code: int = 400
    retryable: bool = False
    next_action: str = ""
    trace_id: str | None = None

    def to_payload(self) -> dict[str, object]:
        return standard_error_payload(
            self.error_type,
            self.error_summary,
            retryable=self.retryable,
            next_action=self.next_action,
            trace_id=self.trace_id,
        )


def standard_error_payload(
    error_type: str,
    error_summary: str,
    *,
    retryable: bool = False,
    next_action: str = "",
    trace_id: str | None = None,
) -> dict[str, object]:
    return {
        "error_type": error_type,
        "error_summary": sanitize_error_summary(error_summary),
        "trace_id": trace_id or f"api-{uuid.uuid4().hex[:16]}",
        "retryable": retryable,
        "next_action": sanitize_error_summary(next_action),
    }


def api_error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.to_payload())


def sanitize_error_summary(value: object) -> str:
    text = str(value or "")
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return "redacted_sensitive_error"
    return text[:500]

