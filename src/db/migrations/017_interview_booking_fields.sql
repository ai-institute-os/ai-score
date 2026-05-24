ALTER TABLE customer_applications
  ADD COLUMN IF NOT EXISTS interviewer_email VARCHAR,
  ADD COLUMN IF NOT EXISTS interview_start_time TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS interview_duration_minutes INTEGER DEFAULT 30,
  ADD COLUMN IF NOT EXISTS interview_notes TEXT;
