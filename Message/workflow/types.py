"""Shared AI workflow data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class WorkflowAction(str, Enum):
    REPLY = "reply"
    TRANSFER_HUMAN = "transfer_human"
    REQUEST_EVIDENCE = "request_evidence"
    BLOCK = "block"
    SKIP = "skip"
    FALLBACK = "fallback"


@dataclass
class WorkflowContext:
    trace_id: str = ""
    shop_id: str = ""
    user_id: str = ""
    customer_uid: str = ""
    buyer_id: str = ""
    session_id: str = ""
    chat_id: str = ""
    dataset_id: str = ""
    message_type: str = "text"
    content: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    goods_context: Any = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductContext:
    goods_id: str = ""
    product_name: str = ""
    shop_id: str = ""
    source: str = "none"
    confidence: float = 0.0
    candidates_summary: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "none"
    inherited: bool = False
    age_messages: int = 0


@dataclass
class WorkflowResult:
    action: WorkflowAction
    reply_text: str = ""
    intent: str = ""
    reason: str = ""
    final_status: str = ""
    risk_flags: List[str] = field(default_factory=list)
    knowledge_refs: List[Dict[str, Any]] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)
    raw_error_type: str = ""
    raw_error_summary: str = ""


def action_value(action: WorkflowAction | str) -> str:
    if isinstance(action, WorkflowAction):
        return action.value
    return str(action or "")
