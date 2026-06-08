import asyncio
import hashlib
import hmac
import structlog
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.connection import run_migrations
from src.db import get_db
from src.db.models import CustomerApplication
from src.llm import PromptRouter, PromptCache, RateLimiter
from src.api.rate_limit import limiter
from src.api.routes import router
from src.api.apply_routes import router as apply_router, _render_report_html

log = structlog.get_logger()

_router: PromptRouter | None = None


_SYSTEM_SOREN_AGENT_ID = "05eac349-ac13-47dc-83ad-eabbbb148be4"
_AISCORE_PROJECT_ID = "c3437c5c-c453-41bd-9ad6-de62eb9ead69"


async def _alert_system_soren(path: str, status_code: int, method: str) -> None:
    settings = get_settings()
    if not (settings.paperclip_api_url and settings.paperclip_api_key and settings.paperclip_company_id):
        return
    ts = datetime.now(timezone.utc).isoformat()
    payload = {
        "title": f"SYSTEM FEJL: {method} {path} — HTTP {status_code}",
        "status": "todo",
        "priority": "critical",
        "assigneeAgentId": _SYSTEM_SOREN_AGENT_ID,
        "projectId": _AISCORE_PROJECT_ID,
        "description": (
            f"## System Alert — AIScore 5xx fejl\n\n"
            f"**Tidspunkt:** {ts}\n"
            f"**Endpoint:** `{method} {path}`\n"
            f"**HTTP Status:** {status_code}\n\n"
            f"Backend returnerede en 5xx-fejl. Tjek Railway-logs og app-status."
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{settings.paperclip_api_url}/api/companies/{settings.paperclip_company_id}/issues",
                json=payload,
                headers={"Authorization": f"Bearer {settings.paperclip_api_key}"},
            )
    except Exception:
        log.warning("paperclip.alert.failed", path=path, status=status_code)


class ErrorAlertMiddleware(BaseHTTPMiddleware):
    """Fires a Paperclip alert to System-Søren on any 5xx response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if response.status_code >= 500:
            asyncio.create_task(
                _alert_system_soren(request.url.path, response.status_code, request.method)
            )
        return response


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


_ADMIN_COOKIE = "aiscore_admin_session"
_ADMIN_PASSWORD = "admin"  # temporary hardcode — replace with env var later


def _make_admin_token(password: str) -> str:
    return hmac.new(password.encode(), b"aiscore-admin-v1", hashlib.sha256).hexdigest()


def _verify_admin_token(token: str, password: str) -> bool:
    if not password:
        return False
    expected = _make_admin_token(password)
    return hmac.compare_digest(token, expected)


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Protect /admin/* HTML pages with cookie-based auth.

    API routes (/api/v1/admin/*) keep their existing X-Admin-Key header auth.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        is_admin_html = (
            (path == "/admin" or path.startswith("/admin/"))
            and not path.startswith("/admin/login")
            and not path.startswith("/api/")
        )
        if not is_admin_html:
            return await call_next(request)

        settings = get_settings()
        token = request.cookies.get(_ADMIN_COOKIE, "")
        if _verify_admin_token(token, _ADMIN_PASSWORD):
            return await call_next(request)

        return RedirectResponse(url=f"/admin/login?next={request.url.path}", status_code=302)


def get_router() -> PromptRouter:
    if _router is None:
        raise RuntimeError("App not initialized — call startup first")
    return _router


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _router
    settings = get_settings()

    # Apply pending SQL migrations before accepting traffic
    try:
        await run_migrations()
    except Exception as exc:
        log.error("migrations.failed", error=str(exc))
        raise

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

    if not settings.admin_api_key:
        log.warning(
            "config.missing_admin_api_key",
            detail="ADMIN_API_KEY env var is not set — admin login will always reject (401) and page auth will redirect to login",
        )

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
app.add_middleware(AdminAuthMiddleware)
app.add_middleware(ErrorAlertMiddleware)

app.include_router(router, prefix="/api/v1")
app.include_router(apply_router, prefix="/api/v1")

# Serve static assets (apply form HTML)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/", include_in_schema=False)
async def landing_page():
    """Serve the AIScore marketing landing page."""
    return FileResponse(str(_static_dir / "landing.html"))


@app.get("/apply", include_in_schema=False)
async def apply_form():
    """Serve the customer pre-qualification apply form."""
    return FileResponse(str(_static_dir / "apply.html"))


@app.get("/my-page/{application_id}", include_in_schema=False)
async def my_page(application_id: str):
    """Customer portal — shows the status of a submitted application."""
    return FileResponse(str(_static_dir / "my-page.html"))


@app.get("/update-application/{application_id}", include_in_schema=False)
async def update_application_page(application_id: str):
    """Customer portal — pre-filled form to update application data after verification."""
    return FileResponse(str(_static_dir / "update_application.html"))


@app.get("/admin/login", include_in_schema=False)
async def admin_login_page(request: Request):
    """Serve the admin login page; redirect if already authenticated."""
    settings = get_settings()
    token = request.cookies.get(_ADMIN_COOKIE, "")
    if _verify_admin_token(token, _ADMIN_PASSWORD):
        return RedirectResponse(url="/admin", status_code=302)
    return FileResponse(str(_static_dir / "admin_login.html"))


@app.post("/admin/login", include_in_schema=False)
async def admin_login_submit(request: Request):
    """Validate admin key and set session cookie."""
    settings = get_settings()
    try:
        body = await request.json()
        submitted_key = body.get("admin_key", "")
    except Exception:
        return JSONResponse({"detail": "Invalid request"}, status_code=400)

    if not submitted_key or submitted_key != _ADMIN_PASSWORD:
        return JSONResponse({"detail": "Invalid admin key"}, status_code=401)

    token = _make_admin_token(_ADMIN_PASSWORD)
    response = JSONResponse({"redirect": "/admin"})
    response.set_cookie(
        key=_ADMIN_COOKIE,
        value=token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=86400 * 7,
    )
    return response


@app.get("/admin/logout", include_in_schema=False)
async def admin_logout():
    """Clear the admin session cookie."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(key=_ADMIN_COOKIE)
    return response


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
    """Redirect the old applications list page to the main admin dashboard."""
    return RedirectResponse(url="/admin", status_code=301)


@app.get("/admin/applications/{application_id}/review", include_in_schema=False)
async def admin_application_review(application_id: str):
    """Serve the single-application review page."""
    return FileResponse(str(_static_dir / "admin_review.html"))


_templates_dir = Path(__file__).parent / "templates"


@app.get("/report-status/{order_id}", include_in_schema=False)
async def report_status_page(order_id: str):
    """Customer-facing status page that live-polls rapport generation progress."""
    return FileResponse(str(_templates_dir / "report_status.html"))


@app.get("/payment/checkout", include_in_schema=False)
async def payment_checkout_page(token: str = ""):
    """Custom Stripe Elements checkout page — served when customer follows payment link."""
    return FileResponse(str(_static_dir / "checkout.html"))


@app.get("/payment/success", include_in_schema=False)
async def payment_success_page(order_id: str = ""):
    """Post-payment confirmation page — shown after successful Stripe checkout."""
    return FileResponse(str(_static_dir / "payment_success.html"))


@app.get("/payment/cancel", include_in_schema=False)
async def payment_cancel_page(order_id: str = ""):
    """Shown when customer cancels Stripe checkout."""
    return FileResponse(str(_static_dir / "payment_cancel.html"))


@app.get("/terms-of-service", include_in_schema=False)
async def terms_of_service_page():
    return FileResponse(str(_static_dir / "terms-of-service.html"))


@app.get("/privacy-policy", include_in_schema=False)
async def privacy_policy_page():
    return FileResponse(str(_static_dir / "privacy-policy.html"))


# ── Public presentation page ───────────────────────────────────────────────────

_NAILSTER_APP_ID = "4c25e701-8541-44e4-9102-efc2ed41421d"

_PRESENTATION_WRAPPER_CSS = """
<style>
  /* Presentation topbar — injected above template pages */
  .pv-topbar {
    position: fixed;
    top: 0; left: 0; right: 0;
    z-index: 200;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 32px;
    height: 56px;
    background: #0d1267;
    box-shadow: 0 2px 12px rgba(0,0,0,.3);
  }
  .pv-topbar-brand {
    font-family: "Playfair Display", Georgia, serif;
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    letter-spacing: -.01em;
    text-decoration: none;
  }
  .pv-topbar-brand .pv-o { display: inline-block; transform: scaleX(1.2); }
  .pv-topbar-brand sup {
    font-size: 0.44em; vertical-align: super; font-weight: 400;
    font-family: "Playfair Display", Georgia, serif;
  }
  .pv-topbar-sub {
    font-size: 12px; color: rgba(255,255,255,.55); margin-left: 8px;
    font-family: Inter, sans-serif; font-weight: 400;
  }
  .pv-cta {
    display: inline-flex; align-items: center; gap: 6px;
    background: #f97316; color: #fff;
    font-family: Inter, sans-serif; font-size: 14px; font-weight: 600;
    padding: 9px 22px; border-radius: 6px; text-decoration: none;
    transition: background .15s;
  }
  .pv-cta:hover { background: #ea6b0e; }
  /* Spacer so the fixed topbar doesn't overlap the first page */
  .pv-spacer { height: 56px; }
</style>
"""

_PRESENTATION_TOPBAR = """
<div class="pv-topbar">
  <div style="display:flex;align-items:baseline;gap:8px;">
    <a href="/" class="pv-topbar-brand">
      AISc<span class="pv-o">o</span>re<sup>™</sup>
    </a>
    <span class="pv-topbar-sub">by AI Institute ApS</span>
  </div>
  <a href="/apply" class="pv-cta">
    Bestil din analyse
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
  </a>
</div>
<div class="pv-spacer"></div>
"""

_PRESENTATION_FOOTER = ""


@app.get("/aiscore/presentation", include_in_schema=False)
async def aiscore_presentation(db: AsyncSession = Depends(get_db)):
    """Public presentation page — shows the Nailster AIScore report without confidentiality markers."""
    result = await db.execute(
        select(CustomerApplication).where(CustomerApplication.id == _NAILSTER_APP_ID)
    )
    app_obj = result.scalar_one_or_none()
    if app_obj is None:
        return HTMLResponse("<h1>Report not available</h1>", status_code=404)

    html = _render_report_html(app_obj)

    # Strip confidentiality markers (order matters — longest match first)
    html = html.replace("&nbsp;·&nbsp; Fortroligt — må ikke videredeles", "")
    html = html.replace("AIScore™ · Fortroligt", "AIScore™ by AI Institute ApS")
    html = html.replace("&nbsp;·&nbsp; Fortroligt", "")
    html = html.replace("Fortroligt — MÅ IKKE VIDEREDELES", "")
    html = html.replace("FORTROLIGT — MÅ IKKE VIDEREDELES", "")
    html = html.replace("Fortroligt", "")

    # Inject topbar CSS + fixed topbar element; leave all page CSS to the template
    html = html.replace("</head>", _PRESENTATION_WRAPPER_CSS + "</head>", 1)
    html = html.replace("<body>", "<body>" + _PRESENTATION_TOPBAR, 1)

    return HTMLResponse(html)


# ── Admin: PDF preview with dummy data ────────────────────────────────────────

_DUMMY_APP = SimpleNamespace(
    firmanavn="Eksempel A/S",
    website="https://eksempel.dk",
    email="kontakt@eksempel.dk",
    telefon="+45 70 12 34 56",
    virksomhedsinfo="En dansk softwarevirksomhed der leverer SaaS-løsninger til SMV-segmentet.",
    country="Denmark",
    industry="Software & SaaS",
    detected_company_type="SaaS",
    overall_score=74,
    queries_run=36,
    rank=1,
    scoring_results={
        "openai": {
            "total_queries": 9, "mentioned_count": 7, "selected_count": 4,
            "avg_naevnt": 18.2, "avg_valgt": 9.1, "avg_valgbarhed": 22.0,
            "avg_konkurrenceposition": 12.5,
            "best_response": "Eksempel A/S er en solid dansk SaaS-løsning der passer godt til mellemstore virksomheder.",
        },
        "claude": {
            "total_queries": 9, "mentioned_count": 6, "selected_count": 3,
            "avg_naevnt": 15.4, "avg_valgt": 7.2, "avg_valgbarhed": 19.5,
            "avg_konkurrenceposition": 11.0,
            "best_response": "Eksempel A/S tilbyder effektive løsninger med god support.",
        },
        "perplexity": {
            "total_queries": 9, "mentioned_count": 8, "selected_count": 5,
            "avg_naevnt": 20.1, "avg_valgt": 11.3, "avg_valgbarhed": 25.8,
            "avg_konkurrenceposition": 14.2,
            "best_response": "En af de bedst vurderede SaaS-virksomheder i Danmark med stærk kundeservice.",
        },
        "gemini": {
            "total_queries": 9, "mentioned_count": 5, "selected_count": 2,
            "avg_naevnt": 13.7, "avg_valgt": 6.8, "avg_valgbarhed": 17.3,
            "avg_konkurrenceposition": 9.5,
            "best_response": "Eksempel A/S er et godt alternativ til større internationale løsninger.",
        },
    },
    agent_business_summary="Eksempel A/S er en dansk SaaS-virksomhed med fokus på B2B-segmentet.",
    agent_competitor_notes="Konkurrerer med Salesforce, HubSpot og Pipedrive på CRM-markedet.",
    agent_target_audience="SMV'er og mellemstore virksomheder i Skandinavien.",
    agent_products_services="CRM-platform, salgsautomatisering, kundeservice-software.",
    agent_market_context="Voksende efterspørgsel på CRM-løsninger i Norden.",
    agent_research_summary="Stærk markedsposition i Danmark, øget synlighed via AI-kanaler.",
    call_extracted_data={"competitors": ["Salesforce", "HubSpot", "Pipedrive"]},
)


@app.get("/admin/preview-reports", include_in_schema=False)
async def admin_preview_reports():
    """Serve the admin PDF preview/download page."""
    return FileResponse(str(_static_dir / "admin_preview_reports.html"))


@app.get("/admin/preview-reports/download/{design}", include_in_schema=False)
async def admin_preview_report_download(design: str):
    """Generate and stream a dummy PDF using the specified design pipeline.

    design=fpdf2  → fpdf2-based pipeline (generate_pdf_mydailychoice.py)
    design=html   → HTML→PDF pipeline (pdf_renderer.py + aiscore-report.html)
    """
    if design == "fpdf2":
        from scripts.generate_pdf_mydailychoice import build_pdf
        pdf = build_pdf()
        pdf_bytes = bytes(pdf.output())
        filename = "aiscore-design1-fpdf2-demo.pdf"
    elif design == "html":
        from src.api.apply_routes import _render_report_html
        from src.pdf_renderer import render_html_to_pdf
        html = _render_report_html(_DUMMY_APP)
        pdf_bytes = await render_html_to_pdf(html)
        filename = "aiscore-design2-html-demo.pdf"
    else:
        return JSONResponse({"detail": "Unknown design. Use 'fpdf2' or 'html'."}, status_code=400)

    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
