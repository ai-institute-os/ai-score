-- Migration 021: add payment_token column for secure Payment Intent lookup
ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS payment_token VARCHAR(64) UNIQUE;

CREATE INDEX IF NOT EXISTS ix_customer_applications_payment_token
    ON customer_applications (payment_token);
