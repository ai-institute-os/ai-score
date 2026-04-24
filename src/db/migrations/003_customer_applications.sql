-- Customer application pre-qualification gate + CRM state machine
-- States: APPLIED → UNDER_REVIEW → APPROVED → CALLED → AWAITING_PAYMENT → PAID → IN_PRODUCTION → QC_REVIEW → QC_PASSED → READY_FOR_REVIEW_CALL
-- REJECTED is a terminal state reachable from APPLIED or UNDER_REVIEW

CREATE TYPE customer_application_status AS ENUM (
    'APPLIED',
    'UNDER_REVIEW',
    'APPROVED',
    'REJECTED',
    'CALLED',
    'AWAITING_PAYMENT',
    'PAID',
    'IN_PRODUCTION',
    'QC_REVIEW',
    'QC_PASSED',
    'READY_FOR_REVIEW_CALL'
);

CREATE TABLE IF NOT EXISTS customer_applications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firmanavn       TEXT NOT NULL,
    website         TEXT NOT NULL,
    kontaktperson   TEXT NOT NULL,
    email           TEXT NOT NULL,
    telefon         TEXT NOT NULL,
    virksomhedsinfo TEXT NOT NULL,
    status          customer_application_status NOT NULL DEFAULT 'APPLIED',
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customer_applications_status
    ON customer_applications (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_applications_email
    ON customer_applications (email);

-- Full audit log of every state transition
CREATE TABLE IF NOT EXISTS customer_application_state_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id  UUID NOT NULL REFERENCES customer_applications(id) ON DELETE CASCADE,
    from_status     customer_application_status,           -- NULL on initial APPLIED entry
    to_status       customer_application_status NOT NULL,
    changed_by      TEXT,                                  -- admin identifier or system
    note            TEXT,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_application_state_logs_application
    ON customer_application_state_logs (application_id, changed_at DESC);
