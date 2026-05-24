-- Scoring pipeline state for CustomerApplication.
-- Tracks async LLM scoring job status and stores per-provider results
-- used to inject real data into the PDF report template.
--
--   scoring_status   : not_started | running | done | error
--   scoring_results  : JSON with per-provider mention/selection counts and sample quotes

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS scoring_status  VARCHAR NOT NULL DEFAULT 'not_started',
    ADD COLUMN IF NOT EXISTS scoring_results JSONB;
