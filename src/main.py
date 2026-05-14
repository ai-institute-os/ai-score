import structlog
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import get_settings
from src.llm import PromptRouter, PromptCache, RateLimiter
from src.api.rate_limit import limiter
from src.api.routes import router
from src.api.apply_routes import router as apply_router

log = structlog.get_logger()

_router: PromptRouter | None = None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        # Only add HSTS when served over HTTPS (avoid poisoning local dev)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response


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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_settings = get_settings()

app.add_middleware(SlowAPIMiddleware)
_allowed_hosts = [h.strip() for h in _settings.allowed_hosts.split(",") if h.strip()]
if _allowed_hosts and _allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)
    
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(router, prefix="/api/v1")
app.include_router(apply_router, prefix="/api/v1")

# Serve static assets (apply form HTML)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/apply", include_in_schema=False)
async def apply_form():
    """Serve the customer pre-qualification apply form."""
    return FileResponse(str(_static_dir / "apply.html"))


@app.get("/admin", include_in_schema=False)
async def admin_dashboard():
    """Serve the AIScore admin dashboard."""
    return FileResponse(str(_static_dir / "admin.html"))


@app.get("/admin/orders", include_in_schema=False)
async def admin_orders():
    """Serve the AIScore admin orders list."""
    return FileResponse(str(_static_dir / "admin_orders.html"))


@app.get("/admin/applications", include_in_schema=False)
async def admin_applications_list():
    """Serve the applications list page."""
    return FileResponse(str(_static_dir / "admin_applications.html"))


@app.get("/admin/applications/{application_id}/review", include_in_schema=False)
async def admin_application_review(application_id: str):
    """Serve the single-application review page."""
    return FileResponse(str(_static_dir / "admin_review.html"))


_templates_dir = Path(__file__).parent / "templates"


@app.get("/report-status/{order_id}", include_in_schema=False)
async def report_status_page(order_id: str):
    """Customer-facing status page that live-polls rapport generation progress."""
    return FileResponse(str(_templates_dir / "report_status.html"))
