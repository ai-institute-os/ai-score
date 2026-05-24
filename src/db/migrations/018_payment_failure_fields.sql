-- Migration 018: store payment failure info for one-time Stripe payments
ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS payment_failure_reason TEXT,
    ADD COLUMN IF NOT EXISTS payment_failed_at       TIMESTAMPTZ;
