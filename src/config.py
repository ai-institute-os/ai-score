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
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-05-01-preview"
    bing_search_api_key: str = ""

    # Rate limits (requests per minute)
    rate_limit_openai: int = 60
    rate_limit_gemini: int = 60
    rate_limit_perplexity: int = 20
    rate_limit_copilot: int = 30

    cache_ttl_seconds: int = 300

    # Scoring & change detection
    scoring_window_days: int = 7
    scoring_alert_threshold: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
