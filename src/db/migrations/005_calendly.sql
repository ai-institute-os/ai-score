-- Track Calendly booking URI on customer applications.
-- Set when invitee.created fires; cleared on invitee.canceled.
ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS calendly_event_uri TEXT;
