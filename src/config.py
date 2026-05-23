from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://aiscore:aiscore_dev@localhost:5432/aiscore"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "info"

    # Default provider keys (overridden per-tenant from DB)
    openai_api_key: str = ""
    google_api_key: str = ""
    perplexity_api_key: str = ""
    anthropic_api_key: str = ""

    # Rate limits (requests per minute)
    rate_limit_openai: int = 60
    rate_limit_gemini: int = 60
    rate_limit_perplexity: int = 20
    rate_limit_claude: int = 50

    cache_ttl_seconds: int = 300

    # Scoring & change detection
    scoring_window_days: int = 7
    scoring_alert_threshold: float = 10.0

    # Stripe (payment links)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    payment_success_url: str = "https://app.aiscore.dk/payment/success"
    payment_cancel_url: str = "https://app.aiscore.dk/payment/cancel"

    # Resend (outbound email)
    resend_api_key: str = ""
    resend_from_email: str = "rapport@aiscore.dk"

    # Internal alert recipients
    qc_alert_email: str = "research@aiscore.dk"
    admin_email: str = "dennis@aiscore.dk"
    admin_review_email: str = "amministrazionemfce@gmail.com"

    # Base URL for admin review links in emails (set APP_BASE_URL in production, e.g. https://<railway-domain>)
    app_base_url: str = "http://localhost:8000"

    # Calendly integration
    # calendly_api_token: Personal Access Token from https://calendly.com/integrations/api_webhooks
    # calendly_event_type_uri: full API URI of the event type, e.g.
    #   https://api.calendly.com/event_types/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    #   (get it from GET https://api.calendly.com/event_types with your token)
    calendly_api_token: str = ""
    calendly_event_type_uri: str = ""
    calendly_webhook_secret: str = ""

    # Admin API key — temporary default "admin"; override via ADMIN_API_KEY env var in production
    admin_api_key: str = "admin"

    # Fernet key for encrypting LLM provider API keys at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Must be set in production. If absent, keys are stored as plaintext (unsafe).
    llm_encryption_key: str = ""

    # AISelect — Stripe price IDs mapped to subscription tiers
    # Set these to the actual Stripe price IDs from your dashboard.
    aiselect_price_starter: str = ""
    aiselect_price_pro: str = ""
    aiselect_price_enterprise: str = ""

    # AISelect — base URL used to build password reset links and API calls
    aiselect_base_url: str = "https://aiselect.dk"

    # AISelect — admin secret for /api/invite and /api/provision endpoints
    # Must match ADMIN_SECRET in the AISelect environment.
    aiselect_admin_secret: str = ""

    # Runtime environment: "production" enables HTTPS redirect and strict headers
    environment: str = "development"

    # Comma-separated list of allowed hostnames for TrustedHostMiddleware
    allowed_hosts: str = "*"

    # Paperclip — used by error-alert middleware to wake System-Søren on 5xx errors
    paperclip_api_url: str = ""
    paperclip_api_key: str = ""
    paperclip_company_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
