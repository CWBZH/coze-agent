CREATE TABLE IF NOT EXISTS knowledge_sop (
    id INTEGER PRIMARY KEY,
    shop_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    content_hash TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'local_admin',
    updated_by TEXT NOT NULL DEFAULT 'local_admin',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_sop_shop_id ON knowledge_sop (shop_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_sop_shop_domain ON knowledge_sop (shop_id, domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_sop_status ON knowledge_sop (status);

CREATE TABLE IF NOT EXISTS product_manual_overrides (
    id INTEGER PRIMARY KEY,
    shop_id TEXT NOT NULL,
    goods_id TEXT NOT NULL,
    goods_name TEXT,
    usage_override TEXT,
    ingredients_override TEXT,
    warnings_override TEXT,
    shelf_life_override TEXT,
    manual_notes TEXT,
    specs_override TEXT,
    price_note_override TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    content_hash TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'local_admin',
    updated_by TEXT NOT NULL DEFAULT 'local_admin',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (shop_id, goods_id)
);

CREATE INDEX IF NOT EXISTS idx_product_manual_overrides_shop_goods ON product_manual_overrides (shop_id, goods_id);
CREATE INDEX IF NOT EXISTS idx_product_manual_overrides_status ON product_manual_overrides (status);

CREATE TABLE IF NOT EXISTS knowledge_versions (
    id INTEGER PRIMARY KEY,
    shop_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_index',
    is_active INTEGER NOT NULL DEFAULT 0,
    index_job_id INTEGER,
    created_by TEXT NOT NULL DEFAULT 'local_admin',
    created_at TEXT NOT NULL,
    indexed_at TEXT,
    activated_at TEXT,
    retired_at TEXT,
    error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_versions_shop_id ON knowledge_versions (shop_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_source ON knowledge_versions (shop_id, source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_domain ON knowledge_versions (shop_id, source_type, domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_active ON knowledge_versions (is_active);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_version ON knowledge_versions (version);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_content_hash ON knowledge_versions (content_hash);

CREATE TABLE IF NOT EXISTS knowledge_index_jobs (
    id INTEGER PRIMARY KEY,
    shop_id TEXT NOT NULL,
    version_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    embedded_count INTEGER NOT NULL DEFAULT 0,
    indexed_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    index_run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_index_jobs_shop_id ON knowledge_index_jobs (shop_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_index_jobs_version_id ON knowledge_index_jobs (version_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_index_jobs_status ON knowledge_index_jobs (status);
CREATE INDEX IF NOT EXISTS idx_knowledge_index_jobs_source ON knowledge_index_jobs (source_type, source_id);
