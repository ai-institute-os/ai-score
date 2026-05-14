-- Application review fields — new public application flow with English field names.
-- Adds country, industry, business_description, competitors, application_goal,
-- and audit timestamps / actor fields for approve/reject transitions.
-- Also makes telefon nullable so the new public endpoint can omit it.

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS country              VARCHAR,
    ADD COLUMN IF NOT EXISTS industry             VARCHAR,
    ADD COLUMN IF NOT EXISTS business_description TEXT,
    ADD COLUMN IF NOT EXISTS competitors          TEXT,
    ADD COLUMN IF NOT EXISTS application_goal     TEXT,
    ADD COLUMN IF NOT EXISTS submitted_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approved_at          TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rejected_at          TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approved_by          VARCHAR,
    ADD COLUMN IF NOT EXISTS rejected_by          VARCHAR,
    ADD COLUMN IF NOT EXISTS rejection_reason     TEXT;

ALTER TABLE customer_applications
    ALTER COLUMN telefon DROP NOT NULL;
