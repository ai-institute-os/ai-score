-- Auto-generated questions for customer applications.
-- Questions are generated automatically on submission and stored in admin for review
-- before being visible to the customer.

ALTER TABLE customer_applications
    ADD COLUMN IF NOT EXISTS detected_company_type     TEXT,
    ADD COLUMN IF NOT EXISTS company_type_confidence   REAL,
    ADD COLUMN IF NOT EXISTS generated_questions       JSONB,
    ADD COLUMN IF NOT EXISTS questions_status          TEXT NOT NULL DEFAULT 'pending';

-- questions_status values: 'pending' | 'approved' | 'rejected'
-- generated_questions is a JSON array: [{"id": "q1", "question": "...", "category": "..."}]
