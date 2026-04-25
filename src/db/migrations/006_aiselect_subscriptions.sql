-- AISelect subscription tracking
-- Stores Stripe subscription state per customer (tier, status, billing period).

CREATE TYPE subscription_tier AS ENUM ('free', 'starter', 'pro', 'enterprise');
CREATE TYPE subscription_status AS ENUM (
    'active', 'trialing', 'past_due', 'cancelled', 'incomplete', 'incomplete_expired'
);

CREATE TABLE IF NOT EXISTS aiselect_subscriptions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_email       TEXT NOT NULL,
    company_name         TEXT NOT NULL,
    stripe_customer_id   TEXT,
    stripe_subscription_id TEXT UNIQUE,
    tier                 subscription_tier   NOT NULL DEFAULT 'free',
    status               subscription_status NOT NULL DEFAULT 'incomplete',
    current_period_start TIMESTAMPTZ,
    current_period_end   TIMESTAMPTZ,
    cancelled_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_aiselect_subscriptions_email
    ON aiselect_subscriptions (customer_email);

CREATE INDEX IF NOT EXISTS idx_aiselect_subscriptions_stripe_customer
    ON aiselect_subscriptions (stripe_customer_id);

CREATE INDEX IF NOT EXISTS idx_aiselect_subscriptions_stripe_subscription
    ON aiselect_subscriptions (stripe_subscription_id);
