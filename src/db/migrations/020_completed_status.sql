-- Add COMPLETED terminal status for applications that have finished the full review call flow.
ALTER TYPE customer_application_status ADD VALUE IF NOT EXISTS 'COMPLETED';

-- Track when review call invitation email was sent
ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS review_call_invitation_sent_at TIMESTAMPTZ;
