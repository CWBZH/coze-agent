-- pgvector schema for internal workflow RAG knowledge chunks.
-- Apply manually in a PostgreSQL database with the pgvector extension enabled.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_id TEXT NOT NULL UNIQUE,
    shop_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version TEXT NOT NULL,
    index_run_id TEXT,
    namespace TEXT,
    is_test_data BOOLEAN NOT NULL DEFAULT false,
    created_by TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL,
    -- Do not pin the dimension here. Production can switch embedding models
    -- (for example text vs multimodal providers) without recreating the table.
    embedding VECTOR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS index_run_id TEXT;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS namespace TEXT;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS is_test_data BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector USING embedding::vector;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_shop_domain
    ON knowledge_chunks (shop_id, domain);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_version
    ON knowledge_chunks (version);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content_hash
    ON knowledge_chunks (content_hash);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source_type
    ON knowledge_chunks (source_type);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_shop_domain_version
    ON knowledge_chunks (shop_id, domain, version);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_index_run_id
    ON knowledge_chunks (index_run_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_namespace_source_type
    ON knowledge_chunks (namespace, source_type);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_metadata_index_run_id
    ON knowledge_chunks ((metadata_json ->> 'index_run_id'));

-- Pick one vector index depending on the installed pgvector version and data size.
-- HNSW generally has better query latency when supported:
-- CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw
--     ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
--
-- IVFFLAT is broadly supported but should be created after loading representative data:
-- CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_ivfflat
--     ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
