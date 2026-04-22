-- Score alerts table for Phase 2 change detection
CREATE TABLE IF NOT EXISTS score_alerts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider     TEXT NOT NULL,
    score_before NUMERIC(5, 2) NOT NULL,
    score_after  NUMERIC(5, 2) NOT NULL,
    delta        NUMERIC(5, 2) NOT NULL,  -- positive = improvement, negative = drop
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_score_alerts_tenant_ts
    ON score_alerts (tenant_id, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_score_alerts_provider
    ON score_alerts (tenant_id, provider, triggered_at DESC);
