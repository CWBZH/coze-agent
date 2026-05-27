"""FastGPT-backed AI workflow engine."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict

from Message.handlers.fastgpt_handler import FastGPTHandler

from .base import AIWorkflowEngine
from .types import WorkflowAction, WorkflowContext, WorkflowResult


_CREDENTIAL_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\bark-[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\bfastgpt-[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(
        r"(?i)\b(token|cookie|access_token|authorization|api_key|secret)\b\s*[:=]\s*[^,\s]+"
    ),
]


def _sanitize_error_summary(value: Any, limit: int = 160) -> str:
    text = "" if value is None else str(value)
    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub("***REDACTED***", text)
    return text[:limit]


class FastGPTWorkflowEngine(AIWorkflowEngine):
    def __init__(self, fastgpt_handler: FastGPTHandler | None = None):
        self.fastgpt_handler = fastgpt_handler or FastGPTHandler()

    async def run(self, context: WorkflowContext) -> WorkflowResult:
        messages = context.messages or [{"role": "user", "content": context.content or ""}]
        shop_name = str(context.metadata.get("shop_name") or "")
        try:
            result: Dict[str, Any] = await asyncio.to_thread(
                self.fastgpt_handler.call,
                messages,
                context.dataset_id,
                chat_id=context.chat_id,
                shop_id=context.shop_id,
                shop_name=shop_name,
            )
        except Exception as exc:
            return WorkflowResult(
                action=WorkflowAction.FALLBACK,
                reason="fastgpt_exception",
                trace={
                    "fastgpt_success": False,
                    "content_is_none": True,
                    "tokens": 0,
                },
                raw_error_type=type(exc).__name__,
                raw_error_summary=_sanitize_error_summary(exc),
            )

        success = bool(result.get("success"))
        content = result.get("content")
        trace = {
            "fastgpt_success": success,
            "content_is_none": content is None,
            "tokens": result.get("tokens", 0),
        }
        if success and content:
            return WorkflowResult(
                action=WorkflowAction.REPLY,
                reply_text=str(content),
                final_status="workflow_reply",
                trace=trace,
            )

        error_type = "FastGPTFailure" if success is False else "EmptyContent"
        return WorkflowResult(
            action=WorkflowAction.FALLBACK,
            reason=str(result.get("error") or error_type),
            trace=trace,
            raw_error_type=error_type,
            raw_error_summary=_sanitize_error_summary(result.get("error") or error_type),
        )
