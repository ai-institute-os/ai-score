-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ─────────────────────────────────────────────
-- Multi-tenant configuration
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-tenant provider credentials (encrypted at rest in production)
CREATE TABLE IF NOT EXISTS tenant_provider_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,   -- 'openai' | 'gemini' | 'perplexity' | 'claude'
    api_key         TEXT,
    extra_config    JSONB NOT NULL DEFAULT '{}',   -- endpoint, deployment, etc.
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider)
);

-- ─────────────────────────────────────────────
-- Core LLM response table (TimescaleDB hypertable)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_responses (
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Request
    prompt          TEXT NOT NULL,
    prompt_hash     TEXT NOT NULL,   -- SHA-256 of prompt for cache lookup
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    -- Response
    response_text   TEXT,
    error           TEXT,
    -- Scoring (populated by phase-2 pipeline)
    score           NUMERIC(5, 2),
    -- Telemetry
    latency_ms      INTEGER,
    tokens_used     INTEGER,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    -- Time
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Metadata
    request_id      UUID,            -- groups parallel calls for one prompt
    cached          BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id, timestamp)
);

-- Convert to TimescaleDB hypertable partitioned by timestamp
SELECT create_hypertable(
    'llm_responses',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_llm_responses_tenant_ts
    ON llm_responses (tenant_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_llm_responses_prompt_hash
    ON llm_responses (prompt_hash, tenant_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_llm_responses_provider
    ON llm_responses (provider, tenant_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_llm_responses_request_id
    ON llm_responses (request_id);

-- ─────────────────────────────────────────────
-- Prompt request log (groups parallel calls)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prompt_requests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    prompt      TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | complete | partial | error
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_prompt_requests_tenant
    ON prompt_requests (tenant_id, created_at DESC);

-- ─────────────────────────────────────────────
-- Continuous aggregate: daily provider stats per tenant
-- ─────────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_provider_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp)   AS bucket,
    tenant_id,
    provider,
    model,
    COUNT(*)                          AS total_calls,
    COUNT(*) FILTER (WHERE error IS NULL) AS successful_calls,
    AVG(latency_ms)                   AS avg_latency_ms,
    SUM(tokens_used)                  AS total_tokens,
    AVG(score)                        AS avg_score
FROM llm_responses
GROUP BY bucket, tenant_id, provider, model
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'daily_provider_stats',
    start_offset    => INTERVAL '3 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE
);
