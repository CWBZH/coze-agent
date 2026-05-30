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
    vnc_url TEXT,
    shop_identity_status TEXT NOT NULL DEFAULT 'unknown',
    auth_status TEXT,
    cookie_encrypted TEXT,
    token_encrypted TEXT
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
    shop_binding_status TEXT NOT NULL DEFAULT 'bound',
    credential_mode TEXT NOT NULL DEFAULT 'browser_only',
    auth_state_reason TEXT,
    last_auth_event_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(shop_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_shop_auth_shop_id ON shop_auth(shop_id);
CREATE INDEX IF NOT EXISTS idx_shop_auth_status ON shop_auth(auth_status);

CREATE TABLE IF NOT EXISTS worker_control_commands (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_type TEXT,
    error_summary TEXT,
    trace_id TEXT
);

CREATE TABLE IF NOT EXISTS shop_worker_desired_state (
    shop_id TEXT PRIMARY KEY,
    desired_state TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS worker_events (
    id TEXT PRIMARY KEY,
    shop_id TEXT,
    event_type TEXT NOT NULL,
    status TEXT,
    summary TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    trace_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_worker_control_commands_status ON worker_control_commands(status);
CREATE INDEX IF NOT EXISTS idx_worker_control_commands_shop_status ON worker_control_commands(shop_id, status);
CREATE INDEX IF NOT EXISTS idx_worker_events_shop_created ON worker_events(shop_id, created_at);

CREATE TABLE IF NOT EXISTS onboarding_validation_runs (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'no_send',
    passed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    created_by TEXT NOT NULL DEFAULT 'local_admin',
    tested_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_onboarding_validation_shop_id ON onboarding_validation_runs(shop_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_validation_status ON onboarding_validation_runs(status);

CREATE TABLE IF NOT EXISTS shop_ai_settings (
    shop_id TEXT PRIMARY KEY,
    ai_enabled INTEGER NOT NULL DEFAULT 0,
    enabled_at TEXT,
    enabled_by TEXT,
    disabled_at TEXT,
    disabled_by TEXT,
    last_change_reason TEXT,
    override_enabled INTEGER NOT NULL DEFAULT 0,
    override_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_admin_audit_log (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    action TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT 'local_admin',
    result TEXT NOT NULL,
    detail_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_web_admin_audit_shop_id ON web_admin_audit_log(shop_id);
CREATE INDEX IF NOT EXISTS idx_web_admin_audit_action ON web_admin_audit_log(action);
