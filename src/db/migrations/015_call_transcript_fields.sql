-- Call transcript and extracted data fields.
-- Stores the raw transcript text and structured extraction result
-- from the Whisper + LLM processing step in the Called stage.

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS call_transcript      TEXT,
    ADD COLUMN IF NOT EXISTS call_extracted_data  JSONB;
