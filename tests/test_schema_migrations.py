import sqlite3

from web_api.services.schema_migration_service import SchemaMigrationService
from web_api.services.shop_service import ShopService
from web_api.services.sqlite_readonly import ReadOnlySqlite


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def test_schema_migrations_upgrade_legacy_sqlite_idempotently(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                shop_id TEXT,
                shop_name TEXT
            );
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                user_id TEXT,
                username TEXT,
                password TEXT,
                cookies TEXT
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                buyer_id TEXT
            );
            CREATE TABLE product_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                goods_id TEXT,
                goods_name TEXT,
                price TEXT,
                specifications TEXT,
                raw_detail_json TEXT
            );
            INSERT INTO channels (id, channel_name) VALUES (1, 'pinduoduo');
            INSERT INTO shops (id, channel_id, shop_id, shop_name) VALUES (1, 1, '565617', 'Real Shop');
            INSERT INTO shops (id, channel_id, shop_id, shop_name) VALUES (2, 1, 'remote-old-session', 'Temporary Shop');
            INSERT INTO accounts (shop_id, user_id, username, password, cookies) VALUES (1, 'seller-1', 'seller', '', '');
            INSERT INTO accounts (shop_id, user_id, username, password, cookies) VALUES (2, 'seller-2', 'temp-seller', '', '');
            INSERT INTO product_knowledge (shop_id, goods_id, goods_name) VALUES (2, 'temp-goods', 'temporary');
            INSERT INTO conversations (shop_id, buyer_id) VALUES (1, 'buyer-1');
            """
        )
        conn.commit()
    finally:
        conn.close()

    service = SchemaMigrationService(db_path)
    first = service.migrate()
    second = service.migrate()

    assert first["applied"]
    assert second["applied"] == []

    conn = sqlite3.connect(db_path)
    try:
        assert "schema_migrations" in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "status" in _columns(conn, "accounts")
        assert "fastgpt_dataset_id" in _columns(conn, "shops")
        assert "shop_logo" in _columns(conn, "shops")
        assert "description" in _columns(conn, "shops")
        assert "updated_at" in _columns(conn, "conversations")
        assert "created_at" in _columns(conn, "product_knowledge")
        assert "usage" in _columns(conn, "product_knowledge")
        assert "shop_identity_status" in _columns(conn, "shop_login_sessions")
        assert "remote-old-session" not in [
            row[0] for row in conn.execute("SELECT shop_id FROM shops").fetchall()
        ]
        assert [row[0] for row in conn.execute("SELECT shop_id FROM quarantined_temporary_shops").fetchall()] == [
            "remote-old-session"
        ]
        assert conn.execute("SELECT COUNT(*) FROM product_knowledge WHERE goods_id='temp-goods'").fetchone()[0] == 0
    finally:
        conn.close()

    shops, warning = ShopService(ReadOnlySqlite(db_path)).list_shops()
    assert warning is None
    assert len(shops) == 1
    assert shops[0].shop_id == "565617"


def test_schema_migrations_backfill_real_shops_from_valid_shop_auth(tmp_path):
    db_path = tmp_path / "auth_backfill.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL,
                UNIQUE(channel_id, shop_id)
            );
            CREATE TABLE shop_auth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'pdd',
                account_name TEXT,
                auth_status TEXT NOT NULL,
                cookie_encrypted TEXT,
                token_encrypted TEXT,
                safe_display TEXT,
                last_login_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(shop_id, platform)
            );
            INSERT INTO shop_auth
                (shop_id, platform, account_name, auth_status, cookie_encrypted, safe_display, created_at, updated_at)
            VALUES
                ('565617', 'pdd', 'seller', 'valid', 'encrypted-only', '135***888', '2026-05-29T00:00:00+00:00', '2026-05-29T00:00:00+00:00'),
                ('remote-login-session', 'pdd', 'seller', 'valid', 'encrypted-only', '135***888', '2026-05-29T00:00:00+00:00', '2026-05-29T00:00:00+00:00');
            """
        )
        conn.commit()
    finally:
        conn.close()

    SchemaMigrationService(db_path).migrate()
    SchemaMigrationService(db_path).migrate()

    shops, warning = ShopService(ReadOnlySqlite(db_path)).list_shops()
    assert warning is None
    assert [shop.shop_id for shop in shops] == ["565617"]
