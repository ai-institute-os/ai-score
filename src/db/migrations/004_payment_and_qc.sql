-- Extend customer_application_status enum with QC failure + escalation states
-- and add payment/QC tracking columns to customer_applications.

-- Add new enum values (safe — ALTER TYPE ADD VALUE is non-blocking in Postgres 12+)
ALTER TYPE customer_application_status ADD VALUE IF NOT EXISTS 'QC_FAILED';
ALTER TYPE customer_application_status ADD VALUE IF NOT EXISTS 'ESCALATED';
ALTER TYPE customer_application_status ADD VALUE IF NOT EXISTS 'RETRY';
ALTER TYPE customer_application_status ADD VALUE IF NOT EXISTS 'CANCELLED';

-- Payment link fields
ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS stripe_session_id        TEXT,
    ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT,
    ADD COLUMN IF NOT EXISTS payment_url              TEXT;

-- QC loop tracking
ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS qc_failure_count   INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS has_been_escalated BOOLEAN NOT NULL DEFAULT FALSE;
