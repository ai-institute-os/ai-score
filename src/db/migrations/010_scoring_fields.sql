-- Scoring data for CustomerApplication — persisted after the IN_PRODUCTION run.
-- These values are substituted into the Puppeteer PDF report template.
--
--   overall_score  : weighted aggregate AIScore (0–100)
--   queries_run    : total number of LLM queries executed for this analysis
--   rank           : position of the company brand in LLM response context

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS overall_score  INTEGER,
    ADD COLUMN IF NOT EXISTS queries_run    INTEGER,
    ADD COLUMN IF NOT EXISTS rank           INTEGER;
