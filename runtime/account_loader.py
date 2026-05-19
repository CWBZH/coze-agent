"""Account loading helpers for the headless worker.

The first headless worker version treats accounts with status == 1 as
candidate-startable accounts. That status currently means the account is
online in the Windows UI model; it is not a persisted auto_reply_enabled flag.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


DEFAULT_CHANNEL = "pinduoduo"


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def sanitize_account(account: Dict[str, Any], channel_name: Optional[str] = None) -> Dict[str, Any]:
    """Return only non-sensitive account fields for logs and CLI output."""
    return {
        "channel_name": _safe_str(channel_name or account.get("channel_name") or DEFAULT_CHANNEL),
        "shop_id": _safe_str(account.get("shop_id")),
        "user_id": _safe_str(account.get("user_id")),
        "username": _safe_str(account.get("username")),
        "status": account.get("status"),
    }


def load_account(db_manager: Any, shop_id: str, user_id: str, channel_name: str = DEFAULT_CHANNEL) -> Optional[Dict[str, Any]]:
    """Load one account and return a sanitized account dict.

    The underlying DatabaseManager.get_account() requires the platform shop_id
    as input but returns the internal shop primary key in its shop_id field, so
    the sanitized output preserves the caller-provided platform shop_id.
    """
    account = db_manager.get_account(channel_name, shop_id, user_id)
    if not account:
        return None

    safe = sanitize_account(account, channel_name=channel_name)
    safe["shop_id"] = _safe_str(shop_id)
    return safe


def load_candidate_accounts(db_manager: Any, channel_name: str = DEFAULT_CHANNEL) -> List[Dict[str, Any]]:
    """Load candidate-startable PDD accounts.

    status == 1 is the current Windows UI online-account signal. It is only a
    candidate filter for the skeleton worker and does not mean a durable
    auto-reply-enabled setting exists.
    """
    accounts: Iterable[Dict[str, Any]] = db_manager.get_all_accounts_with_details()
    candidates: List[Dict[str, Any]] = []
    for account in accounts:
        if account.get("channel_name") != channel_name:
            continue
        if account.get("status") != 1:
            continue
        candidates.append(sanitize_account(account, channel_name=channel_name))
    return candidates

