-- Add text_overrides JSON column to customer_applications
-- Allows per-application placeholder overrides applied before standard substitutions in PDF render
ALTER TABLE customer_applications
  ADD COLUMN IF NOT EXISTS text_overrides JSONB;
