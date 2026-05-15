-- Agent research fields — background browsing/research step triggered after application submit.
-- Adds agent_* columns to customer_applications for storing research results,
-- fit recommendations, interview questions, and error tracking.

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS agent_research_status    VARCHAR         DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS agent_website_summary    TEXT,
    ADD COLUMN IF NOT EXISTS agent_business_summary   TEXT,
    ADD COLUMN IF NOT EXISTS agent_target_audience    TEXT,
    ADD COLUMN IF NOT EXISTS agent_products_services  TEXT,
    ADD COLUMN IF NOT EXISTS agent_market_context     TEXT,
    ADD COLUMN IF NOT EXISTS agent_competitor_notes   TEXT,
    ADD COLUMN IF NOT EXISTS agent_fit_recommendation VARCHAR,
    ADD COLUMN IF NOT EXISTS agent_fit_reason         TEXT,
    ADD COLUMN IF NOT EXISTS agent_missing_information TEXT,
    ADD COLUMN IF NOT EXISTS agent_interview_questions JSONB,
    ADD COLUMN IF NOT EXISTS agent_prompt_directions   JSONB,
    ADD COLUMN IF NOT EXISTS agent_researched_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS agent_research_error     TEXT;
