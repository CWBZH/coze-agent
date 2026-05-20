"""Build sanitized human-transfer alert context from local database."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Optional

from sqlalchemy import desc

from database.models import Account, AgentMessage, Conversation, Shop
from utils.logger_loguru import get_logger

logger = get_logger("HumanAlertContext")

MAX_ALERT_PREVIEW_CHARS = 500
REDACTED = "***REDACTED***"

_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(?:token|cookie|access_token|authorization|api_key|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bark-[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bfastgpt-[A-Za-z0-9._~+/=-]+"),
]


def _fingerprint(value: object) -> tuple[int, str]:
    value_text = "" if value is None else str(value)
    value_hash = hashlib.sha256(value_text.encode("utf-8")).hexdigest()[:12]
    return len(value_text), value_hash


def redact_alert_text(value: object) -> str:
    """Mask credential-like values before they can enter PushPlus content."""
    text = "" if value is None else str(value)
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def make_alert_preview(value: object, limit: int = MAX_ALERT_PREVIEW_CHARS) -> tuple[str, bool, int, str]:
    raw = "" if value is None else str(value)
    sanitized = redact_alert_text(raw)
    truncated = len(sanitized) > limit
    preview = sanitized[:limit] if truncated else sanitized
    raw_length, raw_hash = _fingerprint(raw)
    return preview, truncated, raw_length, raw_hash


@dataclass
class HumanAlertContext:
    shop_id: str
    shop_name: str = ""
    account_name: str = ""
    buyer_id: str = ""
    session_id: str = ""
    session_status: str = ""
    latest_user_message: str = ""
    latest_assistant_message: str = ""
    latest_user_message_truncated: bool = False
    latest_assistant_message_truncated: bool = False


class HumanAlertContextBuilder:
    def __init__(self, db_manager):
        self.db = db_manager

    def build(self, shop_platform_id: str, buyer_id: str) -> HumanAlertContext:
        context = HumanAlertContext(shop_id=str(shop_platform_id), buyer_id=str(buyer_id))
        try:
            with self.db.session_scope() as session:
                shop = session.query(Shop).filter(Shop.shop_id == str(shop_platform_id)).first()
                if not shop:
                    return context

                context.shop_name = shop.shop_name or ""
                account = session.query(Account).filter(Account.shop_id == shop.id).first()
                if account:
                    context.account_name = account.username or ""

                conv = session.query(Conversation).filter(
                    Conversation.shop_id == shop.id,
                    Conversation.buyer_id == str(buyer_id),
                ).order_by(desc(Conversation.updated_at)).first()
                if not conv:
                    return context

                context.session_id = conv.session_id
                context.session_status = conv.status or ""
                context.latest_user_message, context.latest_user_message_truncated = self._latest_message(
                    session,
                    conv.session_id,
                    "user",
                )
                context.latest_assistant_message, context.latest_assistant_message_truncated = self._latest_message(
                    session,
                    conv.session_id,
                    "assistant",
                )
                return context
        except Exception as e:
            logger.warning(
                "build human alert context failed: "
                f"shop_id={shop_platform_id}, buyer_id={buyer_id}, error_type={type(e).__name__}"
            )
            return context

    def _latest_message(self, session, session_id: str, role: str) -> tuple[str, bool]:
        row: Optional[AgentMessage] = session.query(AgentMessage).filter(
            AgentMessage.session_id == session_id,
            AgentMessage.role == role,
        ).order_by(desc(AgentMessage.timestamp)).first()
        if not row or not row.content:
            return "", False
        preview, truncated, _, _ = make_alert_preview(row.content)
        return preview, truncated


def _metadata_line(metadata: dict, key: str, default: object = "") -> str:
    value = metadata.get(key, default) if metadata else default
    return f"{key}={redact_alert_text(value)}"


def format_human_alert_message(
    alert_context: HumanAlertContext,
    reason: str,
    alert_level: str,
    now: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> str:
    now = now or datetime.now()
    metadata = dict(metadata or {})
    level_label = "high" if alert_level == "high" else "low"
    shop_label = alert_context.shop_name or "unknown_shop"
    account_label = alert_context.account_name or "unknown_account"
    session_status = alert_context.session_status or "unknown"

    buyer_preview, buyer_truncated, buyer_length, buyer_hash = make_alert_preview(
        alert_context.latest_user_message
    )
    reply_preview, reply_truncated, reply_length, reply_hash = make_alert_preview(
        alert_context.latest_assistant_message
    )

    if metadata.get("buyer_message_preview"):
        buyer_preview, buyer_truncated, buyer_length, buyer_hash = make_alert_preview(
            metadata.get("buyer_message_preview")
        )
    if metadata.get("seller_or_ai_reply_preview"):
        reply_preview, reply_truncated, reply_length, reply_hash = make_alert_preview(
            metadata.get("seller_or_ai_reply_preview")
        )

    buyer_truncated = buyer_truncated or alert_context.latest_user_message_truncated
    reply_truncated = reply_truncated or alert_context.latest_assistant_message_truncated
    buyer_length = metadata.get("content_length", buyer_length)
    buyer_hash = metadata.get("content_hash", buyer_hash)
    reply_length = metadata.get("reply_length", reply_length)
    reply_hash = metadata.get("reply_hash", reply_hash)

    buyer_preview = buyer_preview or "none"
    reply_preview = reply_preview or "none"

    metadata_lines = [
        _metadata_line(metadata, "trace_id"),
        _metadata_line(metadata, "source_message_id"),
        _metadata_line(metadata, "queue_message_id"),
        _metadata_line(metadata, "session_id", alert_context.session_id),
        _metadata_line(metadata, "customer_uid", alert_context.buyer_id),
        _metadata_line(metadata, "action"),
        _metadata_line(metadata, "message_type"),
        _metadata_line(metadata, "final_status"),
        f"content_length={buyer_length}",
        f"content_hash={redact_alert_text(buyer_hash)}",
        f"reply_length={reply_length}",
        f"reply_hash={redact_alert_text(reply_hash)}",
        f"buyer_message_truncated={str(bool(buyer_truncated)).lower()}",
        f"seller_or_ai_reply_truncated={str(bool(reply_truncated)).lower()}",
    ]

    return "\n".join(
        [
            "[customer-agent manual transfer alert]",
            f"shop={shop_label} ({alert_context.shop_id})",
            f"account={account_label}",
            f"buyer={alert_context.buyer_id}",
            f"alert_level={level_label}",
            f"reason={redact_alert_text(reason)}",
            "",
            "Trace:",
            *metadata_lines,
            "",
            "buyer_message_preview:",
            buyer_preview,
            "",
            "seller_or_ai_reply_preview:",
            reply_preview,
            "",
            f"session_status={session_status}",
            f"timestamp={now.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "Please handle this conversation in the customer service console.",
        ]
    )
