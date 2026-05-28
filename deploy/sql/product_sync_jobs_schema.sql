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

CREATE TABLE IF NOT EXISTS product_sync_jobs (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    internal_shop_id INTEGER,
    status TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'full',
    total_count INTEGER NOT NULL DEFAULT 0,
    succeeded_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    coverage_json TEXT,
    error_summary TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_sync_jobs_shop_id ON product_sync_jobs(shop_id);
CREATE INDEX IF NOT EXISTS idx_product_sync_jobs_status ON product_sync_jobs(status);
CREATE INDEX IF NOT EXISTS idx_product_sync_jobs_updated_at ON product_sync_jobs(updated_at);

CREATE TABLE IF NOT EXISTS product_sync_job_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    goods_id TEXT,
    goods_name TEXT,
    status TEXT NOT NULL,
    error_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_sync_items_job_id ON product_sync_job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_product_sync_items_shop_id ON product_sync_job_items(shop_id);
CREATE INDEX IF NOT EXISTS idx_product_sync_items_status ON product_sync_job_items(status);

CREATE TABLE IF NOT EXISTS product_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL,
    goods_id TEXT NOT NULL,
    goods_name TEXT,
    price TEXT,
    price_min TEXT,
    price_max TEXT,
    sold_quantity INTEGER,
    thumb_url TEXT,
    specifications TEXT,
    usage TEXT,
    ingredients TEXT,
    shelf_life TEXT,
    warnings TEXT,
    manual_notes TEXT,
    raw_detail_json TEXT,
    knowledge_status TEXT DEFAULT 'synced',
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(shop_id, goods_id)
);

CREATE INDEX IF NOT EXISTS idx_product_knowledge_shop_goods ON product_knowledge(shop_id, goods_id);
