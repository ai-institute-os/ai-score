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
    payment_success_url: str = "https://aiscore.dk/payment/success"
    payment_cancel_url: str = "https://aiscore.dk/payment/cancel"

    # SMTP (outbound email)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@aiscore.dk"
    smtp_from_name: str = "AIScore"

    # Internal alert recipients
    qc_alert_email: str = "research@aiscore.dk"
    admin_email: str = "dennis@aiscore.dk"

    # Calendly webhook signing secret
    calendly_webhook_secret: str = ""

    # AISelect — Stripe price IDs mapped to subscription tiers
    # Set these to the actual Stripe price IDs from your dashboard.
    aiselect_price_starter: str = ""
    aiselect_price_pro: str = ""
    aiselect_price_enterprise: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
