-- ============================================================
-- Octopoda PostgreSQL Schema
-- ============================================================
-- Run once on a fresh database. Requires pgvector extension.
-- All tenant data is isolated via Row-Level Security (RLS).
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 1. TENANT REGISTRY (accounts, auth, billing)
-- ============================================================

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id               TEXT PRIMARY KEY,
    email                   TEXT UNIQUE NOT NULL,
    password_hash           TEXT NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    plan                    TEXT DEFAULT 'free',
    max_agents              INTEGER DEFAULT 100,
    max_memories            INTEGER DEFAULT 100000,
    active                  BOOLEAN DEFAULT TRUE,
    verified                BOOLEAN DEFAULT FALSE,
    first_name              TEXT DEFAULT '',
    last_name               TEXT DEFAULT '',
    company                 TEXT DEFAULT '',
    use_case                TEXT DEFAULT '',
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT
);

-- Idempotent additions for existing DBs (safe no-op on fresh installs)
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;

-- Platform free-tier extraction counter. Separate table so we can do atomic
-- UPSERT-with-RETURNING across multiple uvicorn workers. Previous
-- implementation used an in-process threading.Lock which allowed parallel
-- writes hitting different workers to overwrite each other's counters.
CREATE TABLE IF NOT EXISTS platform_usage (
    tenant_id   TEXT PRIMARY KEY,
    used        INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash        TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    key_prefix      TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_used       TIMESTAMPTZ,
    active          BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);

-- ============================================================
-- 2. CORE MEMORY STORAGE (nodes)
-- ============================================================

CREATE TABLE IF NOT EXISTS nodes (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    name            TEXT NOT NULL,
    data            JSONB NOT NULL DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    embedding       vector(384),
    valid_from      DOUBLE PRECISION DEFAULT 0,
    valid_until     DOUBLE PRECISION DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Unique constraint: one active version per key per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_tenant_name_version
    ON nodes(tenant_id, name, valid_from);

-- Fast lookups by tenant + name (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_nodes_tenant_name
    ON nodes(tenant_id, name) WHERE valid_until = 0;

-- Prefix search (used by query_prefix, search, memory listing)
CREATE INDEX IF NOT EXISTS idx_nodes_name_prefix
    ON nodes(tenant_id, name text_pattern_ops) WHERE valid_until = 0;

-- pgvector HNSW index for semantic search
CREATE INDEX IF NOT EXISTS idx_nodes_embedding
    ON nodes USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- Full-text search
CREATE INDEX IF NOT EXISTS idx_nodes_data_gin
    ON nodes USING gin (data jsonb_path_ops);

-- ============================================================
-- 3. FACT EMBEDDINGS (LLM-extracted facts)
-- ============================================================

CREATE TABLE IF NOT EXISTS fact_embeddings (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    node_id         BIGINT,
    node_name       TEXT NOT NULL,
    fact_text       TEXT NOT NULL,
    category        TEXT DEFAULT 'general',
    embedding       vector(384),
    collection      TEXT DEFAULT 'default',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_facts_tenant_node
    ON fact_embeddings(tenant_id, node_name);

CREATE INDEX IF NOT EXISTS idx_facts_embedding
    ON fact_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- ============================================================
-- 4. KNOWLEDGE GRAPH
-- ============================================================

CREATE TABLE IF NOT EXISTS entities (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    name            TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    collection      TEXT DEFAULT 'default',
    first_seen      TIMESTAMPTZ DEFAULT NOW(),
    last_seen       TIMESTAMPTZ DEFAULT NOW(),
    mention_count   INTEGER DEFAULT 1,
    source_node_id  BIGINT,
    UNIQUE(tenant_id, name, entity_type, collection)
);

CREATE INDEX IF NOT EXISTS idx_entities_tenant
    ON entities(tenant_id, name);

CREATE TABLE IF NOT EXISTS relationships (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    source_entity_id    BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id    BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation            TEXT NOT NULL,
    collection          TEXT DEFAULT 'default',
    confidence          FLOAT DEFAULT 1.0,
    source_node_id      BIGINT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_relationships_tenant
    ON relationships(tenant_id, source_entity_id);

-- ============================================================
-- 5. TENANT SETTINGS (LLM config, preferences)
-- ============================================================

CREATE TABLE IF NOT EXISTS tenant_settings (
    tenant_id       TEXT PRIMARY KEY REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    settings        JSONB DEFAULT '{}',
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 6. ROW-LEVEL SECURITY — THE TRUST WALL
-- ============================================================
-- Every table with tenant data gets RLS.
-- The API sets: SET LOCAL app.tenant_id = '{tenant_id}'
-- before each transaction. PostgreSQL refuses to return
-- rows that don't match. Application bugs cannot override this.
-- ============================================================

-- Create an application role that RLS applies to
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'octopoda_app') THEN
        CREATE ROLE octopoda_app LOGIN PASSWORD 'octopoda_app_password';
    END IF;
END
$$;

-- Grant access to all tables
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO octopoda_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO octopoda_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO octopoda_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO octopoda_app;

-- Enable RLS on all tenant-scoped tables
ALTER TABLE nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_settings ENABLE ROW LEVEL SECURITY;

-- RLS policies: only return rows matching current tenant
CREATE POLICY tenant_nodes ON nodes
    FOR ALL TO octopoda_app
    USING (tenant_id = current_setting('app.tenant_id', TRUE))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY tenant_facts ON fact_embeddings
    FOR ALL TO octopoda_app
    USING (tenant_id = current_setting('app.tenant_id', TRUE))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY tenant_entities ON entities
    FOR ALL TO octopoda_app
    USING (tenant_id = current_setting('app.tenant_id', TRUE))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY tenant_relationships ON relationships
    FOR ALL TO octopoda_app
    USING (tenant_id = current_setting('app.tenant_id', TRUE))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY tenant_settings_policy ON tenant_settings
    FOR ALL TO octopoda_app
    USING (tenant_id = current_setting('app.tenant_id', TRUE))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', TRUE));

-- Admin role (vultradmin) bypasses RLS for migrations and management
-- This is the default behavior for table owners

-- ============================================================
-- 7. HELPER FUNCTIONS
-- ============================================================

-- Set tenant context for the current transaction
CREATE OR REPLACE FUNCTION set_tenant(p_tenant_id TEXT) RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.tenant_id', p_tenant_id, TRUE);
END;
$$ LANGUAGE plpgsql;
