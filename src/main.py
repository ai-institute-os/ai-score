import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI

from src.config import get_settings
from src.llm import PromptRouter, PromptCache, RateLimiter
from src.api.routes import router

log = structlog.get_logger()

_router: PromptRouter | None = None


def get_router() -> PromptRouter:
    if _router is None:
        raise RuntimeError("App not initialized — call startup first")
    return _router


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _router
    settings = get_settings()
    cache = PromptCache(redis_url=settings.redis_url, ttl_seconds=settings.cache_ttl_seconds)
    rate_limiter = RateLimiter(
        redis_url=settings.redis_url,
        defaults={
            "openai": settings.rate_limit_openai,
            "gemini": settings.rate_limit_gemini,
            "perplexity": settings.rate_limit_perplexity,
            "copilot": settings.rate_limit_copilot,
        },
    )
    _router = PromptRouter(cache=cache, rate_limiter=rate_limiter)
    log.info("app.started", cache_ttl=settings.cache_ttl_seconds)
    yield
    log.info("app.shutdown")


app = FastAPI(
    title="AIScore / InsideAI / AISelect — LLM Integration Layer",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")
