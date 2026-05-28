import json
import sqlite3
from pathlib import Path

import pytest

from web_api.services.shop_auth_service import AuthSavePayload, ShopAuthService
from web_api.services.shop_auth_resolver import ShopAuthResolver


def _init_schema(db_path: Path) -> None:
    schema = Path("deploy/sql/shop_onboarding_schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def _insert_legacy_account(db_path: Path, *, shop_id: str = "565617", user_id: str = "legacy-user", cookies: str | None = None) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT OR IGNORE INTO channels (channel_name, description) VALUES ('pinduoduo', 'PDD')")
        channel_id = conn.execute("SELECT id FROM channels WHERE channel_name='pinduoduo'").fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO shops (channel_id, shop_id, shop_name, created_at) VALUES (?, ?, ?, ?)",
            (channel_id, shop_id, "测试店铺", "2026-05-27T00:00:00+00:00"),
        )
        shop_pk = conn.execute("SELECT id FROM shops WHERE channel_id=? AND shop_id=?", (channel_id, shop_id)).fetchone()[0]
        conn.execute(
            "INSERT INTO accounts (shop_id, user_id, username, password, cookies, status) VALUES (?, ?, ?, '', ?, 1)",
            (shop_pk, user_id, "legacy-seller", cookies or json.dumps({"legacy": "cookie"})),
        )
        conn.commit()
    finally:
        conn.close()


def test_shop_auth_resolver_prefers_encrypted_shop_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    db_path = tmp_path / "auth.db"
    _init_schema(db_path)
    _insert_legacy_account(db_path, cookies=json.dumps({"legacy": "cookie"}))
    ShopAuthService(db_path=db_path).save_auth(
        AuthSavePayload(
            shop_id="565617",
            shop_name="测试店铺",
            platform="pdd",
            account_name="seller_account_10000000000",
            user_id="seller-user",
            cookie_value=json.dumps({"new": "cookie"}),
        )
    )

    result = ShopAuthResolver(db_path=db_path).get_cookies("565617")

    assert result.status == "ok"
    assert result.source == "shop_auth"
    assert result.cookies == {"new": "cookie"}
    assert result.user_id == "seller-user"


def test_shop_auth_resolver_falls_back_to_legacy_accounts_cookies(tmp_path):
    db_path = tmp_path / "auth.db"
    _init_schema(db_path)
    _insert_legacy_account(db_path, cookies=json.dumps({"legacy": "cookie"}))

    result = ShopAuthResolver(db_path=db_path).get_cookies("565617")

    assert result.status == "ok"
    assert result.source == "legacy_accounts"
    assert result.cookies == {"legacy": "cookie"}
    assert result.user_id == "legacy-user"


def test_shop_auth_resolver_parses_browser_cookie_header(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    db_path = tmp_path / "auth.db"
    _init_schema(db_path)
    ShopAuthService(db_path=db_path).save_auth(
        AuthSavePayload(
            shop_id="565617",
            shop_name="测试店铺",
            platform="pdd",
            account_name="seller_account_10000000000",
            user_id="seller-user",
            cookie_value="api_uid=abc; mms_b84d1838=xyz",
        )
    )

    result = ShopAuthResolver(db_path=db_path).get_cookies("565617")

    assert result.status == "ok"
    assert result.cookies == {"api_uid": "abc", "mms_b84d1838": "xyz"}


def test_shop_auth_resolver_reports_decrypt_failure_without_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    db_path = tmp_path / "auth.db"
    _init_schema(db_path)
    _insert_legacy_account(db_path, cookies=json.dumps({"legacy": "cookie"}))
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO shop_auth
                (shop_id, platform, account_name, auth_status, cookie_encrypted, safe_display, created_at, updated_at)
            VALUES (?, 'pdd', 'seller', 'auth_valid', 'not-valid-ciphertext', 'seller', ?, ?)
            """,
            ("565617", "2026-05-27T00:00:00+00:00", "2026-05-27T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    result = ShopAuthResolver(db_path=db_path).get_cookies("565617")

    assert result.status == "auth_invalid"
    assert result.source == "shop_auth"
    assert result.cookies == {}
    assert result.error_type == "auth_decrypt_failed"


def test_product_sync_resolves_cookies_through_auth_resolver():
    from Knowledge.product_sync import ProductSyncService

    class FakeResolver:
        def get_cookies(self, shop_id, platform="pdd", user_id=None):
            assert shop_id == "565617"
            assert platform == "pdd"
            assert user_id is None
            return type(
                "Result",
                (),
                {"status": "ok", "cookies": {"resolved": "cookie"}, "user_id": "resolver-user", "source": "shop_auth"},
            )()

    service = ProductSyncService(db_manager=object(), auth_resolver=FakeResolver())

    user_id, cookies = service._resolve_account("565617", "")

    assert user_id == "resolver-user"
    assert cookies == {"resolved": "cookie"}
