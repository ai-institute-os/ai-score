-- Application Verification fields.
-- Adds per-field AI verification status, results (JSONB), and timestamp
-- to customer_applications. Verification runs as a separate phase before
-- Generate Questions and is tracked independently from agent research.

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS agent_verification_status TEXT NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS agent_verification_results JSONB,
    ADD COLUMN IF NOT EXISTS agent_verified_at          TIMESTAMPTZ;
