-- Verification substage tracking fields.
-- Adds fine-grained tracking of where an application is in the verification flow:
-- substage values: PENDING | RUNNING | FAILED | UPDATE_REQUESTED | RESUBMITTED | VERIFIED

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS verification_substage          TEXT,
    ADD COLUMN IF NOT EXISTS verification_failed_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS update_request_email_sent_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resubmitted_at                 TIMESTAMPTZ;
