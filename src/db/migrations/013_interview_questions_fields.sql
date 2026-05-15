-- Interview questions supplementary fields.
-- Adds agent_question_categories, agent_research_summary, and questions_generated_at
-- to customer_applications. agent_interview_questions already exists from migration 012.

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS agent_question_categories JSONB,
    ADD COLUMN IF NOT EXISTS agent_research_summary    TEXT,
    ADD COLUMN IF NOT EXISTS questions_generated_at    TIMESTAMPTZ;
