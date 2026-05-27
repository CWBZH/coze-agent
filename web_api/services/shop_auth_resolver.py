from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web_api.services.shop_auth_service import ShopAuthCipher
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


@dataclass(frozen=True)
class ShopAuthResolution:
    status: str
    cookies: dict[str, str]
    source: str
    user_id: str | None = None
    account_name: str | None = None
    error_type: str | None = None


class ShopAuthResolver:
    """Resolve PDD cookies for server-side use without exposing secrets.

    Resolution order:
    1. Valid encrypted shop_auth record.
    2. Legacy accounts.cookies fallback.

    A present but undecryptable shop_auth record is treated as auth_invalid and
    does not silently fall back to legacy credentials.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, cipher: ShopAuthCipher | None = None) -> None:
        self.db_path = Path(db_path)
        self.cipher = cipher or ShopAuthCipher.from_env()

    def get_cookies(self, shop_id: str, platform: str = "pdd", user_id: str | None = None) -> ShopAuthResolution:
        conn = self._connect()
        try:
            auth = self._get_shop_auth(conn, str(shop_id), platform)
            if auth is not None:
                status = str(auth["auth_status"] or "")
                encrypted = auth["cookie_encrypted"]
                if status == "auth_valid" and encrypted:
                    try:
                        cookies = self._parse_cookies(self.cipher.decrypt(str(encrypted)))
                    except Exception:
                        return ShopAuthResolution(
                            status="auth_invalid",
                            cookies={},
                            source="shop_auth",
                            account_name=auth["account_name"],
                            error_type="auth_decrypt_failed",
                        )
                    if cookies:
                        account = self._get_legacy_account(conn, str(shop_id), user_id, account_name=auth["account_name"])
                        return ShopAuthResolution(
                            status="ok",
                            cookies=cookies,
                            source="shop_auth",
                            user_id=str(account["user_id"]) if account is not None and account["user_id"] is not None else None,
                            account_name=str(auth["account_name"] or "") or None,
                        )
                    return ShopAuthResolution(
                        status="auth_invalid",
                        cookies={},
                        source="shop_auth",
                        account_name=auth["account_name"],
                        error_type="auth_cookie_empty",
                    )
            return self._resolve_legacy(conn, str(shop_id), user_id)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_shop_auth(self, conn: sqlite3.Connection, shop_id: str, platform: str) -> sqlite3.Row | None:
        if not self._table_exists(conn, "shop_auth"):
            return None
        return conn.execute(
            """
            SELECT shop_id, platform, account_name, auth_status, cookie_encrypted
            FROM shop_auth
            WHERE shop_id=? AND platform=?
            """,
            (shop_id, platform),
        ).fetchone()

    def _resolve_legacy(self, conn: sqlite3.Connection, shop_id: str, user_id: str | None) -> ShopAuthResolution:
        account = self._get_legacy_account(conn, shop_id, user_id)
        if account is None:
            return ShopAuthResolution(status="missing", cookies={}, source="none", error_type="auth_missing")
        cookies = self._parse_cookies(account["cookies"])
        if not cookies:
            return ShopAuthResolution(
                status="missing",
                cookies={},
                source="legacy_accounts",
                user_id=str(account["user_id"] or "") or None,
                account_name=str(account["username"] or "") or None,
                error_type="legacy_cookie_missing",
            )
        return ShopAuthResolution(
            status="ok",
            cookies=cookies,
            source="legacy_accounts",
            user_id=str(account["user_id"] or "") or None,
            account_name=str(account["username"] or "") or None,
        )

    def _get_legacy_account(
        self,
        conn: sqlite3.Connection,
        shop_id: str,
        user_id: str | None,
        account_name: Any = None,
    ) -> sqlite3.Row | None:
        if not all(self._table_exists(conn, table) for table in ("channels", "shops", "accounts")):
            return None
        channel_name = _channel_name_for_platform("pdd")
        query = """
            SELECT accounts.user_id, accounts.username, accounts.cookies, accounts.status
            FROM accounts
            JOIN shops ON accounts.shop_id = shops.id
            JOIN channels ON shops.channel_id = channels.id
            WHERE channels.channel_name=? AND shops.shop_id=?
        """
        params: list[Any] = [channel_name, shop_id]
        if user_id:
            query += " AND accounts.user_id=?"
            params.append(user_id)
            return conn.execute(query + " LIMIT 1", params).fetchone()
        if account_name:
            row = conn.execute(query + " AND accounts.username=? LIMIT 1", params + [account_name]).fetchone()
            if row is not None:
                return row
        return conn.execute(query + " ORDER BY accounts.status DESC, accounts.id ASC LIMIT 1", params).fetchone()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        return row is not None

    @staticmethod
    def _parse_cookies(value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items() if k}
        if isinstance(value, str) and value.strip():
            data = json.loads(value)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if k}
        return {}


def _channel_name_for_platform(platform: str) -> str:
    return "pinduoduo" if platform in {"pdd", "pinduoduo"} else platform
