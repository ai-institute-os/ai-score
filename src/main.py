import structlog
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.config import get_settings
from src.llm import PromptRouter, PromptCache, RateLimiter
from src.api.routes import router
from src.api.apply_routes import router as apply_router

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
            "claude": settings.rate_limit_claude,
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
app.include_router(apply_router, prefix="/api/v1")

# Serve static assets (apply form HTML)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/apply", include_in_schema=False)
async def apply_form():
    """Serve the customer pre-qualification apply form."""
    return FileResponse(str(_static_dir / "apply.html"))


@app.get("/admin", include_in_schema=False)
async def admin_dashboard():
    """Serve the AIScore admin dashboard."""
    return FileResponse(str(_static_dir / "admin.html"))
