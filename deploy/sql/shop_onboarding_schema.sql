CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    shop_id TEXT NOT NULL,
    shop_name TEXT NOT NULL,
    shop_logo TEXT,
    description TEXT,
    created_at TEXT,
    UNIQUE(channel_id, shop_id)
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL DEFAULT '',
    cookies TEXT,
    status INTEGER
);

CREATE TABLE IF NOT EXISTS shop_login_sessions (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'pdd',
    shop_id TEXT,
    shop_name TEXT,
    account_name TEXT,
    safe_display TEXT,
    runner_mode TEXT NOT NULL DEFAULT 'fake',
    status TEXT NOT NULL,
    step TEXT NOT NULL,
    needs_sms_code INTEGER NOT NULL DEFAULT 0,
    needs_captcha INTEGER NOT NULL DEFAULT 0,
    captcha_image_ref TEXT,
    error_summary TEXT,
    created_by TEXT NOT NULL DEFAULT 'local_admin',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    cancelled_at TEXT,
    remote_browser_status TEXT,
    remote_browser_token TEXT,
    vnc_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_shop_login_sessions_status ON shop_login_sessions(status);
CREATE INDEX IF NOT EXISTS idx_shop_login_sessions_shop_id ON shop_login_sessions(shop_id);
CREATE INDEX IF NOT EXISTS idx_shop_login_sessions_account_name ON shop_login_sessions(account_name);

CREATE TABLE IF NOT EXISTS shop_auth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'pdd',
    account_name TEXT,
    auth_status TEXT NOT NULL,
    cookie_encrypted TEXT,
    token_encrypted TEXT,
    safe_display TEXT,
    last_login_at TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(shop_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_shop_auth_shop_id ON shop_auth(shop_id);
CREATE INDEX IF NOT EXISTS idx_shop_auth_status ON shop_auth(auth_status);
