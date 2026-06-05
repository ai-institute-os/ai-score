import asyncio
import hashlib
import hmac as _hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import structlog
from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db import get_db
from src.db.models import (
    CustomerApplication, CustomerApplicationStateLog, CustomerApplicationStatus, VALID_TRANSITIONS,
    BACKWARD_TRANSITIONS,
    AISelectSubscription, SubscriptionTier, SubscriptionStatus,
    PasswordResetToken,
)
from src.api.schemas import (
    ApplicationCreate, ApplicationCreatePublic, ApplicationRejectRequest,
    ApplicationListItem, ApplicationResponse, ApplicationStatusUpdate,
    GeneratePaymentLinkRequest, PaymentLinkResponse, PaymentInitResponse,
    QCResultSubmit, ManualCorrectionRequest, ScoringDataUpdate,
    BookCallRequest,
    ForgotPasswordRequest, ResetPasswordRequest, PasswordResetResponse,
)
from src.api.rate_limit import limiter
from src.api.auth import require_admin_key

log = structlog.get_logger()
router = APIRouter()

# Number of QC failures before escalation / cancellation
_QC_ESCALATION_THRESHOLD = 3


# ─────────────────────────────────────────────
# Public: submit an application
# ─────────────────────────────────────────────

async def _generate_and_store_questions(application_id: uuid.UUID, firmanavn: str, website: str, virksomhedsinfo: str) -> None:
    """Background task: detect company type and generate questions, then persist."""
    from src.config import get_settings
    from src.questions.generator import generate_questions

    settings = get_settings()
    try:
        company_type, confidence, questions = await generate_questions(
            firmanavn=firmanavn,
            website=website,
            virksomhedsinfo=virksomhedsinfo,
            openai_api_key=settings.openai_api_key,
        )
        from src.db.connection import get_session_factory
        async with get_session_factory()() as session:
            result = await session.execute(
                select(CustomerApplication).where(CustomerApplication.id == application_id)
            )
            app = result.scalar_one_or_none()
            if app:
                app.detected_company_type = company_type
                app.company_type_confidence = confidence
                app.generated_questions = questions
                app.questions_status = "pending"
                await session.commit()
                log.info(
                    "questions.stored",
                    application_id=str(application_id),
                    company_type=company_type,
                )
    except Exception as exc:
        log.error("questions.background_failed", application_id=str(application_id), error=str(exc))


@router.post("/apply", response_model=ApplicationResponse, status_code=201)
@limiter.limit("5/minute")
async def submit_application(
    request: Request,
    body: ApplicationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — customers submit their pre-qualification application here."""
    app = CustomerApplication(
        firmanavn=body.firmanavn,
        website=body.website,
        kontaktperson=body.kontaktperson,
        email=body.email,
        telefon=body.telefon,
        virksomhedsinfo=body.virksomhedsinfo,
        status=CustomerApplicationStatus.APPLIED,
    )
    db.add(app)
    await db.flush()  # get app.id before creating log entry

    state_log = CustomerApplicationStateLog(
        application_id=app.id,
        from_status=None,
        to_status=CustomerApplicationStatus.APPLIED,
        changed_by="system",
        note="Application submitted",
    )
    db.add(state_log)
    await db.commit()
    await db.refresh(app)

    # Trigger question generation in background — does not block the response
    background_tasks.add_task(
        _generate_and_store_questions,
        app.id,
        body.firmanavn,
        body.website,
        body.virksomhedsinfo,
    )

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


# ─────────────────────────────────────────────
# Public: new application flow (English fields, auto UNDER_REVIEW)
# ─────────────────────────────────────────────

async def _send_admin_review_email(app: CustomerApplication, app_base_url: str, admin_email: str) -> None:
    """Send admin notification when an application moves to UNDER_REVIEW."""
    from src.payments.emailer import send_email
    import html as _html

    review_url = f"{app_base_url.rstrip('/')}/admin/applications/{app.id}/review"

    def _esc(v: object) -> str:
        return _html.escape(str(v)) if v is not None else "—"

    fields_html = "".join(
        f"<tr><td style='padding:4px 8px;font-weight:600;white-space:nowrap'>{label}</td>"
        f"<td style='padding:4px 8px'>{_esc(value)}</td></tr>"
        for label, value in [
            ("Company", app.firmanavn),
            ("Contact", app.kontaktperson),
            ("Email", app.email),
            ("Website", app.website),
            ("Country", app.country),
            ("Industry", app.industry),
            ("Business description", app.virksomhedsinfo),
            ("Competitors", app.competitors),
            ("Application goal", app.application_goal),
        ]
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px;color:#1a1a1a">
  <h2 style="color:#111">New AIScore Application Requires Review</h2>
  <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
    {fields_html}
  </table>
  <p>
    <a href="{_esc(review_url)}" style="display:inline-block;padding:10px 20px;background:#2563eb;color:#fff;border-radius:6px;text-decoration:none">
      Review Application
    </a>
  </p>
</body>
</html>"""

    try:
        await send_email(
            to=admin_email,
            subject="New AIScore Application Requires Review",
            html_body=html_body,
        )
    except Exception as exc:
        log.error("application.review_email_failed", application_id=str(app.id), error=str(exc))


async def _send_approval_email(app: CustomerApplication, admin_review_email: str) -> None:
    from src.payments.emailer import send_email
    import html as _html

    def _esc(v: object) -> str:
        return _html.escape(str(v)) if v is not None else ""

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#111">
  <h2 style="color:#111;margin-bottom:8px;">Your AIScore application has been approved!</h2>
  <p style="color:#374151;">Hi {_esc(app.kontaktperson)},</p>
  <p style="color:#374151;">
    We are pleased to inform you that your application for <strong>{_esc(app.firmanavn)}</strong>
    has been approved.
  </p>
  <p style="color:#374151;">
    We will organize an interview to collect more information about your business.
    You will hear from us shortly with the details.
  </p>
  <p style="color:#6b7280;font-size:0.875rem;">The AIScore Team</p>
</body>
</html>"""

    try:
        await send_email(
            to=admin_review_email,
            subject="Your AIScore application has been approved",
            html_body=html_body,
        )
    except Exception as exc:
        log.error("application.approval_email_failed", application_id=str(app.id), error=str(exc))


async def _send_rejection_email(app: CustomerApplication, rejection_reason: str, admin_review_email: str) -> None:
    from src.payments.emailer import send_email
    import html as _html

    def _esc(v: object) -> str:
        return _html.escape(str(v)) if v is not None else ""

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#111">
  <h2 style="color:#111;margin-bottom:8px;">Update on your AIScore application</h2>
  <p style="color:#374151;">Hi {_esc(app.kontaktperson)},</p>
  <p style="color:#374151;">
    Your application for <strong>{_esc(app.firmanavn)}</strong> has been rejected by the administrator.
    If you want to know in detail, please reach out.
  </p>
  <p style="color:#6b7280;font-size:0.875rem;">The AIScore Team</p>
</body>
</html>"""

    try:
        await send_email(
            to=admin_review_email,
            subject="Update on your AIScore application",
            html_body=html_body,
        )
    except Exception as exc:
        log.error("application.rejection_email_failed", application_id=str(app.id), error=str(exc))


@router.post("/applications", response_model=ApplicationResponse, status_code=201)
@limiter.limit("5/minute")
async def submit_application_public(
    request: Request,
    body: ApplicationCreatePublic,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — new application flow with English field names.

    Creates the application as APPLIED and triggers background verification.
    Admin manually moves to UNDER_REVIEW via move-to-review endpoint after verification.
    """
    from src.config import get_settings
    now = datetime.now(timezone.utc)

    app = CustomerApplication(
        firmanavn=body.company_name,
        website=body.website,
        kontaktperson=body.contact_name,
        email=str(body.contact_email),
        telefon=None,
        virksomhedsinfo=body.business_description,
        country=body.country,
        industry=body.industry,
        business_description=body.business_description,
        competitors=body.competitors,
        application_goal=body.application_goal,
        submitted_at=now,
        status=CustomerApplicationStatus.APPLIED,
    )
    db.add(app)
    await db.flush()

    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=None,
        to_status=CustomerApplicationStatus.APPLIED,
        changed_by="system",
        note="Application submitted via public endpoint",
    ))

    await db.commit()
    await db.refresh(app)

    settings = get_settings()
    admin_review_email = getattr(settings, "admin_review_email", "amministrazionemfce@gmail.com")
    app_base_url = settings.app_base_url
    background_tasks.add_task(_send_admin_review_email, app, app_base_url, admin_review_email)

    # Trigger background agent research + verification — does not block submission
    saved_app_id = app.id
    background_tasks.add_task(_run_research_background, saved_app_id)
    background_tasks.add_task(_run_verification_background, saved_app_id)

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


async def _run_research_background(application_id: uuid.UUID) -> None:
    """Wrapper that runs the async research task from a background thread context."""
    try:
        from src.agent.research import run_application_research
        await run_application_research(application_id)
    except Exception as exc:
        log.error("research.trigger_failed", application_id=str(application_id), error=str(exc))


async def _run_verification_background(application_id: uuid.UUID) -> None:
    """Wrapper that runs the async verification task from a background thread context."""
    try:
        from src.agent.verification import run_application_verification
        await run_application_verification(application_id)
    except Exception as exc:
        log.error("verification.trigger_failed", application_id=str(application_id), error=str(exc))


# ─────────────────────────────────────────────
# Admin: list and manage applications
# ─────────────────────────────────────────────

@router.get("/admin/applications", response_model=list[ApplicationListItem])
@limiter.limit("30/minute")
async def list_applications(
    request: Request,
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """Admin — list applications (lightweight: only columns needed for the table view)."""
    q = select(
        CustomerApplication.id,
        CustomerApplication.firmanavn,
        CustomerApplication.website,
        CustomerApplication.kontaktperson,
        CustomerApplication.email,
        CustomerApplication.status,
        CustomerApplication.submitted_at,
        CustomerApplication.created_at,
        CustomerApplication.updated_at,
    )
    if status:
        try:
            status_enum = CustomerApplicationStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status}")
        q = q.where(CustomerApplication.status == status_enum)
    q = q.order_by(CustomerApplication.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    rows = result.mappings().all()
    return [ApplicationListItem.model_validate(dict(r)) for r in rows]


@router.get("/admin/orders")
@limiter.limit("30/minute")
async def list_orders(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin — seneste 20 betalte AIScore-rapporter med Calendly-status."""
    paid_statuses = [
        CustomerApplicationStatus.PAID,
        CustomerApplicationStatus.IN_PRODUCTION,
        CustomerApplicationStatus.QC_REVIEW,
        CustomerApplicationStatus.QC_PASSED,
        CustomerApplicationStatus.QC_FAILED,
        CustomerApplicationStatus.ESCALATED,
        CustomerApplicationStatus.RETRY,
        CustomerApplicationStatus.READY_FOR_REVIEW_CALL,
    ]
    q = (
        select(CustomerApplication)
        .where(CustomerApplication.status.in_(paid_statuses))
        .order_by(CustomerApplication.updated_at.desc())
        .limit(20)
    )
    result = await db.execute(q)
    apps = list(result.scalars().all())

    return [
        {
            "id": str(app.id),
            "firmanavn": app.firmanavn,
            "email": app.email,
            "status": app.status.value,
            "updated_at": app.updated_at.isoformat() if app.updated_at else None,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "score": None,
            "rapport_url": f"/report-status/{app.id}",
            "calendly_booked": app.calendly_event_uri is not None,
        }
        for app in apps
    ]


@router.get("/admin/applications/{application_id}", response_model=ApplicationResponse)
@limiter.limit("30/minute")
async def get_application(request: Request, application_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Admin — get a single application with full state log."""
    app = await _get_application_or_404(application_id, db)
    return app


@router.post("/admin/applications/{application_id}/retry-research", response_model=ApplicationResponse)
@limiter.limit("10/minute")
async def retry_research(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin — re-trigger agent research for an application (resets status to PENDING)."""
    app = await _get_application_or_404(application_id, db)

    app.agent_research_status = "PENDING"
    app.agent_research_error = None
    await db.commit()

    background_tasks.add_task(_run_research_background, application_id)

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == application_id)
    )
    return result.scalar_one()


@router.post("/admin/applications/{application_id}/book-meeting")
@limiter.limit("20/minute")
async def book_meeting(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Admin — create a one-time Calendly scheduling link for the applicant."""
    import httpx
    from src.config import get_settings

    settings = get_settings()
    app = await _get_application_or_404(application_id, db)

    if not settings.calendly_api_token or not settings.calendly_event_type_uri:
        missing = []
        if not settings.calendly_api_token:
            missing.append("CALENDLY_API_TOKEN")
        if not settings.calendly_event_type_uri:
            missing.append("CALENDLY_EVENT_TYPE_URI")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "calendly_not_configured",
                "message": "Calendly integration is not configured.",
                "missing_env_vars": missing,
                "how_to_get": {
                    "CALENDLY_API_TOKEN": (
                        "Go to https://calendly.com/integrations/api_webhooks → "
                        "Generate a Personal Access Token. Copy and set as CALENDLY_API_TOKEN."
                    ),
                    "CALENDLY_EVENT_TYPE_URI": (
                        "Call GET https://api.calendly.com/event_types "
                        "(Authorization: Bearer <your_token>) to list your event types. "
                        "Copy the 'uri' field of the event type you want to use for applicant calls."
                    ),
                },
            },
        )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.calendly.com/scheduling_links",
                headers={
                    "Authorization": f"Bearer {settings.calendly_api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "max_event_count": 1,
                    "owner": settings.calendly_event_type_uri,
                    "owner_type": "EventType",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            booking_url = data["resource"]["booking_url"]
    except httpx.HTTPStatusError as exc:
        log.error("calendly.api_error", status=exc.response.status_code, body=exc.response.text)
        raise HTTPException(status_code=502, detail=f"Calendly API error: {exc.response.status_code}")
    except Exception as exc:
        log.error("calendly.request_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Could not reach Calendly: {exc}")

    log.info("calendly.link_created", application_id=str(application_id), company=app.firmanavn)
    return {
        "booking_url": booking_url,
        "applicant_name": app.kontaktperson or app.firmanavn,
        "applicant_email": app.email,
    }


@router.post("/admin/applications/{application_id}/book-call", response_model=ApplicationResponse)
@limiter.limit("20/minute")
async def book_call(
    request: Request,
    application_id: uuid.UUID,
    body: BookCallRequest,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Admin — manually book a call for an APPROVED application."""
    from src.payments.emailer import send_email
    from src.config import get_settings

    settings = get_settings()
    app = await _get_application_or_404(application_id, db)

    if app.status != CustomerApplicationStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Application must be in APPROVED status to book a call.")

    now = datetime.now(timezone.utc)
    if body.interview_start_time.tzinfo is None:
        start = body.interview_start_time.replace(tzinfo=timezone.utc)
    else:
        start = body.interview_start_time.astimezone(timezone.utc)

    if start <= now:
        raise HTTPException(status_code=422, detail="Interview start time must be in the future.")

    end = start + timedelta(minutes=body.interview_duration_minutes)

    # Overlap detection: find any APPROVED or CALLED apps with a scheduled interview that overlaps
    overlap_q = select(CustomerApplication).where(
        CustomerApplication.id != application_id,
        CustomerApplication.status.in_([
            CustomerApplicationStatus.APPROVED,
            CustomerApplicationStatus.CALLED,
        ]),
        CustomerApplication.interview_start_time.isnot(None),
    )
    result = await db.execute(overlap_q)
    existing = result.scalars().all()
    for other in existing:
        o_start = other.interview_start_time
        if o_start is None:
            continue
        if o_start.tzinfo is None:
            o_start = o_start.replace(tzinfo=timezone.utc)
        o_end = o_start + timedelta(minutes=(other.interview_duration_minutes or 30))
        if start < o_end and end > o_start:
            raise HTTPException(
                status_code=409,
                detail=f"Time slot overlaps with existing booking for '{other.firmanavn}' at {o_start.isoformat()}.",
            )

    app.interviewer_email = body.interviewer_email
    app.interview_start_time = start
    app.interview_duration_minutes = body.interview_duration_minutes
    app.interview_notes = body.interview_notes
    app.status = CustomerApplicationStatus.CALLED

    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=CustomerApplicationStatus.APPROVED,
        to_status=CustomerApplicationStatus.CALLED,
        changed_by="admin",
        note=f"Call booked: {body.interview_duration_minutes} min with {body.interviewer_email}",
    ))
    await db.commit()

    # Send notification email to admin
    start_str = start.strftime("%Y-%m-%d %H:%M UTC")
    html_body = f"""
<p>A call has been booked for <strong>{app.firmanavn}</strong>.</p>
<ul>
  <li><strong>Applicant:</strong> {app.kontaktperson} ({app.email})</li>
  <li><strong>Interviewer:</strong> {body.interviewer_email}</li>
  <li><strong>Start:</strong> {start_str}</li>
  <li><strong>Duration:</strong> {body.interview_duration_minutes} minutes</li>
  {'<li><strong>Notes:</strong> ' + body.interview_notes + '</li>' if body.interview_notes else ''}
</ul>
"""
    try:
        await send_email(
            to=settings.admin_review_email,
            subject=f"Call booked: {app.firmanavn} — {start_str}",
            html_body=html_body,
        )
    except Exception:
        pass  # Don't fail the booking if email fails

    log.info("call.booked", application_id=str(application_id), company=app.firmanavn, start=start.isoformat())
    result2 = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == application_id)
    )
    return result2.scalar_one()


_TRANSCRIPT_EXTRACT_PROMPT = """You are an AI analyst reviewing a transcript from a sales/onboarding call with a potential AIScore client.

Extract the following from the transcript and return ONLY valid JSON (no prose, no markdown):

{
  "summary": "2-3 sentence summary of the call",
  "key_topics": ["topic 1", "topic 2"],
  "concerns": ["concern or objection raised by the client"],
  "fit_assessment": "STRONG_FIT | MODERATE_FIT | WEAK_FIT | UNCLEAR",
  "follow_up_actions": ["action 1", "action 2"],
  "next_steps": ["next step 1", "next step 2"]
}"""


@router.post("/admin/applications/{application_id}/upload-transcript")
@limiter.limit("10/minute")
async def upload_transcript(
    request: Request,
    application_id: uuid.UUID,
    file: Optional[UploadFile] = File(None),
    transcript_text: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Admin — transcribe a call recording (Whisper) and extract key information (LLM)."""
    import httpx
    import json as _json
    from src.config import get_settings

    settings = get_settings()
    await _get_application_or_404(application_id, db)

    raw_transcript: str = transcript_text or ""

    # If a file is provided and it's audio/video, transcribe with Whisper
    if file and file.filename:
        content_type = file.content_type or ""
        is_text = content_type.startswith("text/") or file.filename.endswith(".txt")
        if is_text:
            raw_transcript = (await file.read()).decode("utf-8", errors="replace")
        else:
            if not settings.openai_api_key:
                raise HTTPException(
                    status_code=400,
                    detail="Audio transcription requires OPENAI_API_KEY. Paste the transcript as text instead.",
                )
            file_bytes = await file.read()
            _WHISPER_MAX_BYTES = 25 * 1024 * 1024  # 25 MB — OpenAI hard limit
            if len(file_bytes) > _WHISPER_MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Audio file is too large ({len(file_bytes) // (1024*1024)} MB). "
                        "Whisper's limit is 25 MB. Compress or trim the recording and try again, "
                        "or paste the transcript as text."
                    ),
                )
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    files={"file": (file.filename, file_bytes, content_type)},
                    data={"model": "whisper-1"},
                )
                if not resp.is_success:
                    err_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    err_msg = err_body.get("error", {}).get("message") or f"HTTP {resp.status_code}"
                    raise HTTPException(status_code=502, detail=f"Whisper transcription failed: {err_msg}")
                raw_transcript = resp.json().get("text", "")

    if not raw_transcript.strip():
        raise HTTPException(status_code=400, detail="No transcript content provided.")

    # Extract structured information with LLM
    providers = []
    if settings.openai_api_key:
        providers.append(("openai", settings.openai_api_key))
    if settings.google_api_key:
        providers.append(("gemini", settings.google_api_key))
    if settings.anthropic_api_key:
        providers.append(("anthropic", settings.anthropic_api_key))

    extracted: dict = {}
    for name, key in providers:
        try:
            if name == "openai":
                from openai import AsyncOpenAI
                c = AsyncOpenAI(api_key=key)
                r = await c.chat.completions.create(
                    model="gpt-4o-mini", max_tokens=1024,
                    messages=[
                        {"role": "system", "content": _TRANSCRIPT_EXTRACT_PROMPT},
                        {"role": "user", "content": raw_transcript[:12000]},
                    ],
                )
                await c.close()
                extracted = _json.loads(r.choices[0].message.content or "{}")
            elif name == "gemini":
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}",
                        json={"contents": [{"parts": [{"text": f"{_TRANSCRIPT_EXTRACT_PROMPT}\n\n{raw_transcript[:12000]}"}]}],
                              "generationConfig": {"maxOutputTokens": 1024}},
                    )
                    r.raise_for_status()
                    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if raw.startswith("```"): raw = raw.split("```",2)[1]; raw = raw[4:] if raw.startswith("json") else raw; raw = raw.rsplit("```",1)[0].strip()
                    extracted = _json.loads(raw)
            elif name == "anthropic":
                import anthropic as _ant
                c = _ant.AsyncAnthropic(api_key=key)
                r = await c.messages.create(
                    model="claude-sonnet-4-6", max_tokens=1024,
                    system=_TRANSCRIPT_EXTRACT_PROMPT,
                    messages=[{"role": "user", "content": raw_transcript[:12000]}],
                )
                await c.close()
                extracted = _json.loads(r.content[0].text if r.content else "{}")
            break
        except Exception as exc:
            log.warning("transcript.llm_failed", provider=name, error=str(exc))

    # Persist transcript and extraction result to the application record
    app_record = await _get_application_or_404(application_id, db)
    app_record.call_transcript = raw_transcript
    app_record.call_extracted_data = extracted or {}
    await db.commit()

    log.info("transcript.processed", application_id=str(application_id), chars=len(raw_transcript))
    return {"transcript": raw_transcript, "extracted": extracted}


@router.post("/admin/applications/{application_id}/verify", response_model=ApplicationResponse)
@limiter.limit("10/minute")
async def verify_application(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Admin — trigger per-field AI verification for an application.

    Runs as a background task. Sets agent_verification_status to IN_PROGRESS
    immediately, then COMPLETED (no ERROR fields) or FAILED after the LLM call.
    """
    app = await _get_application_or_404(application_id, db)

    app.agent_verification_status = "PENDING"
    app.agent_verification_results = None
    app.agent_verified_at = None
    await db.commit()

    background_tasks.add_task(_run_verification_background, application_id)

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == application_id)
    )
    return result.scalar_one()


@router.post(
    "/admin/applications/{application_id}/approve",
    response_model=ApplicationResponse,
)
@limiter.limit("30/minute")
async def approve_application(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin — approve an application in UNDER_REVIEW → APPROVED."""
    from src.config import get_settings
    app = await _get_application_or_404(application_id, db)

    if app.status != CustomerApplicationStatus.UNDER_REVIEW:
        raise HTTPException(
            status_code=422,
            detail=f"Only UNDER_REVIEW applications can be approved. Current: {app.status.value}",
        )

    now = datetime.now(timezone.utc)
    prev_status = app.status
    app.status = CustomerApplicationStatus.APPROVED
    app.approved_at = now
    app.approved_by = "admin"
    app.updated_at = now
    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.APPROVED,
        changed_by="admin",
        note="Application approved",
    ))
    await db.commit()

    settings = get_settings()
    background_tasks.add_task(_send_approval_email, app, settings.admin_review_email)

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


@router.post(
    "/admin/applications/{application_id}/reject",
    response_model=ApplicationResponse,
)
@limiter.limit("30/minute")
async def reject_application(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: ApplicationRejectRequest = ApplicationRejectRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Admin — reject an application (APPLIED or UNDER_REVIEW → REJECTED)."""
    from src.config import get_settings
    app = await _get_application_or_404(application_id, db)

    allowed_from = {CustomerApplicationStatus.APPLIED, CustomerApplicationStatus.UNDER_REVIEW}
    if app.status not in allowed_from:
        raise HTTPException(
            status_code=422,
            detail=f"Only APPLIED or UNDER_REVIEW applications can be rejected. Current: {app.status.value}",
        )

    now = datetime.now(timezone.utc)
    prev_status = app.status
    app.status = CustomerApplicationStatus.REJECTED
    app.rejected_at = now
    app.rejected_by = "admin"
    app.rejection_reason = body.rejection_reason
    app.updated_at = now
    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.REJECTED,
        changed_by="admin",
        note=body.rejection_reason or "Application rejected",
    ))
    await db.commit()

    settings = get_settings()
    background_tasks.add_task(_send_rejection_email, app, body.rejection_reason or "", settings.admin_review_email)

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


@router.patch("/admin/applications/{application_id}/status", response_model=ApplicationResponse)
@limiter.limit("30/minute")
async def update_application_status(
    request: Request,
    application_id: uuid.UUID,
    body: ApplicationStatusUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin — advance the application through the CRM state machine."""
    app = await _get_application_or_404(application_id, db)

    try:
        new_status = CustomerApplicationStatus(body.status.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown status: {body.status}")

    allowed = VALID_TRANSITIONS.get(app.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Transition from {app.status.value} to {new_status.value} is not allowed. "
                f"Valid next states: {[s.value for s in allowed] or 'none (terminal state)'}"
            ),
        )

    prev_status = app.status
    is_backward = (prev_status, new_status) in BACKWARD_TRANSITIONS

    app.status = new_status
    app.updated_at = datetime.now(timezone.utc)

    note_text = body.note or ""
    if is_backward:
        prefix = "[Manual backward move]"
        note_text = f"{prefix} {note_text}".strip() if note_text else prefix

    state_log = CustomerApplicationStateLog(
        application_id=app.id,
        from_status=prev_status,
        to_status=new_status,
        changed_by="admin",
        note=note_text or None,
    )
    db.add(state_log)
    await db.commit()

    if new_status == CustomerApplicationStatus.IN_PRODUCTION and not is_backward:
        app.report_questions_status = "generating"
        await db.commit()
        background_tasks.add_task(_generate_and_store_report_questions, application_id)
        log.info("admin.pipeline_triggered", application_id=str(application_id))

    if new_status == CustomerApplicationStatus.READY_FOR_REVIEW_CALL and not is_backward:
        from src.payments.emailer import send_aiselect_crosssell_email
        from src.config import get_settings as _gs
        _settings = _gs()
        aiselect_url = getattr(_settings, "aiselect_checkout_url", _settings.aiselect_base_url)
        await send_aiselect_crosssell_email(
            customer_email=app.email,
            customer_name=app.kontaktperson,
            company_name=app.firmanavn,
            aiselect_url=aiselect_url,
        )
        await _call_aiselect_invite(
            customer_email=app.email,
            customer_name=app.kontaktperson,
            company_name=app.firmanavn,
            application_id=str(application_id),
        )

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


@router.patch("/admin/applications/{application_id}/notes", response_model=ApplicationResponse)
@limiter.limit("30/minute")
async def update_application_notes(
    request: Request,
    application_id: uuid.UUID,
    notes: str,
    db: AsyncSession = Depends(get_db),
):
    """Admin — update internal notes on an application."""
    app = await _get_application_or_404(application_id, db)
    app.notes = notes
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


# ─────────────────────────────────────────────
# Admin: move APPLIED → UNDER_REVIEW
# ─────────────────────────────────────────────

@router.post("/admin/applications/{application_id}/move-to-review", response_model=ApplicationResponse)
@limiter.limit("30/minute")
async def move_to_review(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_key),
):
    """Admin — manually transition APPLIED → UNDER_REVIEW after verification."""
    app = await _get_application_or_404(application_id, db)

    if app.status != CustomerApplicationStatus.APPLIED:
        raise HTTPException(
            status_code=422,
            detail=f"Only APPLIED applications can be moved to review. Current: {app.status.value}",
        )

    if app.agent_verification_status != "COMPLETED":
        raise HTTPException(
            status_code=422,
            detail="Verification must complete before moving to review.",
        )

    if app.agent_verification_results:
        has_errors = any(
            isinstance(v, dict) and v.get("status", "").upper() == "ERROR"
            for v in app.agent_verification_results.values()
        )
        if has_errors:
            raise HTTPException(
                status_code=422,
                detail="Verification has ERROR fields — urge applicant to update first.",
            )

    now = datetime.now(timezone.utc)
    app.status = CustomerApplicationStatus.UNDER_REVIEW
    app.updated_at = now
    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=CustomerApplicationStatus.APPLIED,
        to_status=CustomerApplicationStatus.UNDER_REVIEW,
        changed_by="admin",
        note="Manually moved to Under Review after verification",
    ))
    await db.commit()

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


# ─────────────────────────────────────────────
# Admin: urge applicant to update their data
# ─────────────────────────────────────────────

@router.post("/admin/applications/{application_id}/urge-update")
@limiter.limit("10/minute")
async def urge_applicant_update(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_key),
):
    """Admin — send email to applicant with link to update their application data."""
    from src.payments.emailer import send_email
    import html as _html

    app = await _get_application_or_404(application_id, db)

    # Keep verification results so the email can list the failed fields
    prior_verification_results = app.agent_verification_results

    now = datetime.now(timezone.utc)

    # If the application was auto-rejected, re-open it to APPLIED so the
    # applicant can resubmit and the admin can retry verification.
    if app.status == CustomerApplicationStatus.REJECTED:
        prev_status = app.status
        app.status = CustomerApplicationStatus.APPLIED
        app.rejected_at = None
        app.rejected_by = None
        app.rejection_reason = None
        db.add(CustomerApplicationStateLog(
            application_id=app.id,
            from_status=prev_status,
            to_status=CustomerApplicationStatus.APPLIED,
            changed_by="admin-urge-update",
            note="Application re-opened: admin sent update request email after auto-rejection",
        ))

    app.verification_substage = "UPDATE_REQUEST_EMAIL_SENT"
    app.update_request_email_sent_at = now
    app.updated_at = now
    await db.commit()

    from src.config import get_settings
    settings = get_settings()
    app_base_url = settings.app_base_url
    update_url = f"{app_base_url.rstrip('/')}/update-application/{app.id}"

    def _esc(v: object) -> str:
        return _html.escape(str(v)) if v is not None else ""

    verification_notes = ""
    if prior_verification_results:
        _problem_statuses = {"error", "failed", "warning"}
        failed_fields = []
        for k, v in prior_verification_results.items():
            if not isinstance(v, dict):
                continue
            if v.get("status", "").lower() not in _problem_statuses:
                continue
            note = (v.get("note") or "").strip()
            if not note:
                continue
            label = k.replace("_", " ").capitalize()
            failed_fields.append(f"<li><strong>{_esc(label)}:</strong> {_esc(note)}</li>")
        if failed_fields:
            verification_notes = (
                "<p style='color:#374151;margin:0 0 8px;'>Our review found the following items need attention:</p>"
                "<ul style='margin:0 0 16px;padding-left:20px;color:#374151;'>"
                + "".join(failed_fields)
                + "</ul>"
            )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#111">
  <h2 style="color:#111;margin-bottom:8px;">Action required: Update your AIScore application</h2>
  <p style="color:#374151;">Hi {_esc(app.kontaktperson)},</p>
  <p style="color:#374151;">Thank you for applying to AIScore. We've reviewed your application
  and would like you to update a few details before we proceed.</p>
  {verification_notes}
  <p>
    <a href="{_esc(update_url)}"
       style="display:inline-block;padding:12px 24px;background:#f97316;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">
      Update my application
    </a>
  </p>
  <p style="color:#6b7280;font-size:0.875rem;">
    Or copy this link: {_esc(update_url)}
  </p>
</body>
</html>"""

    # Temporary: send to admin email until applicant auth is implemented
    recipient = settings.admin_review_email or app.email
    try:
        await send_email(
            to=recipient,
            subject="Action required: Update your AIScore application",
            html_body=html_body,
        )
    except Exception as exc:
        log.error("urge_update.email_failed", application_id=str(application_id), error=str(exc))
        raise HTTPException(status_code=502, detail=f"Email send failed: {exc}")

    return {"sent": True, "to": recipient, "update_url": update_url}


# ─────────────────────────────────────────────
# Public: pre-fill data for update page
# ─────────────────────────────────────────────

@router.get("/applications/{application_id}/update-data")
@limiter.limit("30/minute")
async def get_update_data(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Public — returns current application data + verification results for the update form.

    UUID acts as unguessable token; no auth required.
    """
    result = await db.execute(
        select(CustomerApplication).where(CustomerApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")

    return {
        "id": str(app.id),
        "company_name": app.firmanavn,
        "website": app.website,
        "country": app.country,
        "industry": app.industry,
        "business_description": app.virksomhedsinfo or app.business_description,
        "competitors": app.competitors,
        "contact_name": app.kontaktperson,
        "contact_email": app.email,
        "application_goal": app.application_goal,
        "status": app.status.value if hasattr(app.status, "value") else str(app.status),
        "verification_results": app.agent_verification_results,
        "verification_status": app.agent_verification_status,
    }


class ApplicationUpdatePublic(BaseModel):
    company_name: Optional[str] = None
    website: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    business_description: Optional[str] = None
    competitors: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    application_goal: Optional[str] = None


@router.patch("/applications/{application_id}/update", response_model=dict)
@limiter.limit("10/minute")
async def update_application_public(
    request: Request,
    application_id: uuid.UUID,
    body: ApplicationUpdatePublic,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Public — applicant updates their data. Resets verification so admin runs it again."""
    result = await db.execute(
        select(CustomerApplication).where(CustomerApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")

    now = datetime.now(timezone.utc)
    if body.company_name is not None:
        app.firmanavn = body.company_name
    if body.website is not None:
        app.website = body.website
    if body.country is not None:
        app.country = body.country
    if body.industry is not None:
        app.industry = body.industry
    if body.business_description is not None:
        app.virksomhedsinfo = body.business_description
        app.business_description = body.business_description
    if body.competitors is not None:
        app.competitors = body.competitors
    if body.contact_name is not None:
        app.kontaktperson = body.contact_name
    if body.contact_email is not None:
        app.email = body.contact_email
    if body.application_goal is not None:
        app.application_goal = body.application_goal

    # Reset verification; mark as RESUBMITTED so admin sees the applicant responded.
    # If the application was auto-rejected, restore status to APPLIED so the
    # admin can see the RESUBMITTED substage panel and retry verification.
    if app.status == CustomerApplicationStatus.REJECTED:
        prev_status = app.status
        app.status = CustomerApplicationStatus.APPLIED
        app.rejected_at = None
        app.rejected_by = None
        app.rejection_reason = None
        db.add(CustomerApplicationStateLog(
            application_id=app.id,
            from_status=prev_status,
            to_status=CustomerApplicationStatus.APPLIED,
            changed_by="applicant-resubmit",
            note="Application re-opened after auto-rejection: applicant submitted updated data",
        ))

    app.agent_verification_status = "PENDING"
    app.agent_verification_results = None
    app.verification_substage = "RESUBMITTED"
    app.resubmitted_at = now
    app.updated_at = now

    await db.commit()

    # Trigger verification in background
    background_tasks.add_task(_run_verification_background, application_id)

    return {"updated": True, "id": str(application_id)}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _call_aiselect_invite(
    customer_email: str,
    customer_name: str,
    company_name: str,
    application_id: str,
) -> None:
    """
    POST {aiselect_base_url}/api/invite to create an AISelect invitation.
    Fire-and-forget: logs errors but never raises, so downstream failures
    cannot break the status transition.
    """
    import httpx
    from src.config import get_settings as _gs

    settings = _gs()
    if not settings.aiselect_admin_secret:
        log.warning("aiselect_invite.admin_secret_not_configured", application_id=application_id)
        return

    invite_url = f"{settings.aiselect_base_url.rstrip('/')}/api/invite"
    payload = {
        "contactEmail": customer_email,
        "contactName": customer_name,
        "companyName": company_name,
        "planId": "starter",
    }
    headers = {"x-admin-secret": settings.aiselect_admin_secret}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(invite_url, json=payload, headers=headers)
        if resp.status_code == 200:
            log.info(
                "aiselect_invite.sent",
                application_id=application_id,
                email=customer_email,
            )
        else:
            log.error(
                "aiselect_invite.unexpected_status",
                application_id=application_id,
                status_code=resp.status_code,
                body=resp.text[:500],
            )
    except Exception as exc:
        log.error("aiselect_invite.failed", application_id=application_id, error=str(exc))


async def _get_application_or_404(application_id: uuid.UUID, db: AsyncSession) -> CustomerApplication:
    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


async def _add_state_log(
    db: AsyncSession,
    app: CustomerApplication,
    from_status: CustomerApplicationStatus,
    to_status: CustomerApplicationStatus,
    changed_by: Optional[str],
    note: Optional[str],
) -> None:
    entry = CustomerApplicationStateLog(
        application_id=app.id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        note=note,
    )
    db.add(entry)


# ─────────────────────────────────────────────
# Admin: question review
# ─────────────────────────────────────────────

@router.get(
    "/admin/applications/{application_id}/questions",
)
@limiter.limit("30/minute")
async def get_application_questions(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Admin — fetch auto-generated questions for an application (pending admin review)."""
    app = await _get_application_or_404(application_id, db)
    return {
        "application_id": str(application_id),
        "firmanavn": app.firmanavn,
        "detected_company_type": app.detected_company_type,
        "company_type_confidence": app.company_type_confidence,
        "questions_status": app.questions_status,
        "generated_questions": app.generated_questions or [],
    }


@router.post(
    "/admin/applications/{application_id}/questions/approve",
)
@limiter.limit("30/minute")
async def approve_application_questions(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Admin — approve generated questions so they become visible on the customer's profile."""
    app = await _get_application_or_404(application_id, db)
    if not app.generated_questions:
        raise HTTPException(status_code=422, detail="No generated questions to approve.")
    app.questions_status = "approved"
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"application_id": str(application_id), "questions_status": "approved"}


@router.post(
    "/admin/applications/{application_id}/questions/reject",
)
@limiter.limit("30/minute")
async def reject_application_questions(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Admin — reject generated questions (triggers regeneration on next admin action)."""
    app = await _get_application_or_404(application_id, db)
    app.questions_status = "rejected"
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"application_id": str(application_id), "questions_status": "rejected"}


@router.post(
    "/admin/applications/{application_id}/questions/regenerate",
)
@limiter.limit("10/minute")
async def regenerate_application_questions(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin — manually trigger question re-generation for an application."""
    app = await _get_application_or_404(application_id, db)
    app.questions_status = "pending"
    app.generated_questions = None
    app.detected_company_type = None
    app.company_type_confidence = None
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        _generate_and_store_questions,
        app.id,
        app.firmanavn,
        app.website,
        app.virksomhedsinfo,
    )
    return {"application_id": str(application_id), "questions_status": "pending", "message": "Regeneration started."}


# ─────────────────────────────────────────────
# Report questions (scoring criteria from answered interview)
# ─────────────────────────────────────────────

def _all_answered(questions: list) -> bool:
    return bool(questions) and all(
        isinstance(q, dict) and q.get("answer", "").strip()
        for q in questions
    )


async def _generate_and_store_report_questions(application_id: uuid.UUID) -> None:
    """Background task: generate report scoring criteria from answered interview + company data."""
    from src.config import get_settings
    from src.questions.report_generator import generate_report_questions
    from src.db.connection import get_session_factory

    settings = get_settings()
    async with get_session_factory()() as session:
        result = await session.execute(
            select(CustomerApplication).where(CustomerApplication.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            log.error("report_questions.app_not_found", application_id=str(application_id))
            return

        try:
            questions = await generate_report_questions(
                firmanavn=app.firmanavn,
                website=app.website,
                virksomhedsinfo=app.virksomhedsinfo,
                company_type=app.detected_company_type or "andet",
                answered_questions=app.generated_questions or [],
                openai_api_key=settings.openai_api_key,
                perplexity_api_key=getattr(settings, "perplexity_api_key", ""),
            )
            app.report_questions = questions
            app.report_questions_status = "done"
            log.info(
                "report_questions.stored",
                application_id=str(application_id),
                count=len(questions),
            )
        except Exception as exc:
            log.error("report_questions.failed", application_id=str(application_id), error=str(exc))
            app.report_questions_status = "error"

        await session.commit()


@router.post(
    "/admin/applications/{application_id}/report-questions/generate",
)
@limiter.limit("10/minute")
async def generate_report_questions_endpoint(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin — trigger async generation of report scoring criteria from answered interview."""
    app = await _get_application_or_404(application_id, db)

    if app.report_questions_status == "generating":
        return {
            "application_id": str(application_id),
            "report_questions_status": "generating",
            "message": "Generering er allerede i gang.",
        }

    app.report_questions_status = "generating"
    app.report_questions = None
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(_generate_and_store_report_questions, application_id)

    return {
        "application_id": str(application_id),
        "report_questions_status": "generating",
        "message": "Rapport-spørgsmål genereres i baggrunden.",
    }


@router.get(
    "/admin/applications/{application_id}/report-questions",
)
@limiter.limit("60/minute")
async def get_report_questions(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Admin — fetch status and generated report scoring criteria for an application."""
    app = await _get_application_or_404(application_id, db)
    return {
        "application_id": str(application_id),
        "firmanavn": app.firmanavn,
        "detected_company_type": app.detected_company_type,
        "report_questions_status": app.report_questions_status,
        "report_questions": app.report_questions or [],
    }


@router.patch(
    "/admin/applications/{application_id}/questions/answers",
)
@limiter.limit("30/minute")
async def save_question_answers(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin — save interview answers for generated questions.

    Expects JSON body: list of {id, answer} objects.
    Auto-triggers report-questions generation when all questions are answered
    and report_questions_status is not_started or error.
    """
    try:
        body = await request.json()
        if not isinstance(body, list):
            raise ValueError("Expected a JSON array")
        answers: list[dict] = body
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be a JSON array of {id, answer} objects.")

    app = await _get_application_or_404(application_id, db)

    if not app.generated_questions:
        raise HTTPException(status_code=422, detail="No generated questions to answer.")

    answer_map = {
        str(a.get("id", "")): str(a.get("answer", "")).strip()
        for a in answers
        if isinstance(a, dict) and a.get("id")
    }

    updated = []
    for q in app.generated_questions:
        qcopy = dict(q)
        qid = str(q.get("id", ""))
        if qid in answer_map:
            qcopy["answer"] = answer_map[qid]
        updated.append(qcopy)

    app.generated_questions = updated
    app.updated_at = datetime.now(timezone.utc)

    should_trigger = (
        _all_answered(updated)
        and app.report_questions_status in ("not_started", "error")
    )
    if should_trigger:
        app.report_questions_status = "generating"
        app.report_questions = None
        background_tasks.add_task(_generate_and_store_report_questions, application_id)
        log.info(
            "report_questions.auto_triggered",
            application_id=str(application_id),
        )

    await db.commit()

    return {
        "application_id": str(application_id),
        "generated_questions": updated,
        "report_questions_status": app.report_questions_status,
        "auto_triggered": should_trigger,
    }


# ─────────────────────────────────────────────
# Payment link generation
# ─────────────────────────────────────────────

@router.post(
    "/admin/applications/{application_id}/payment-link",
    response_model=PaymentLinkResponse,
    status_code=201,
)
@limiter.limit("30/minute")
async def generate_payment_link(
    request: Request,
    application_id: uuid.UUID,
    body: GeneratePaymentLinkRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_key),
):
    """
    Admin — generate a Stripe Payment Intent + custom checkout link for a customer.
    Transitions the application to AWAITING_PAYMENT.
    """
    from src.payments import create_payment_intent, send_payment_link_email
    from src.config import get_settings

    settings = get_settings()
    app = await _get_application_or_404(application_id, db)

    allowed_from = {
        CustomerApplicationStatus.CALLED,
        CustomerApplicationStatus.APPROVED,
        CustomerApplicationStatus.AWAITING_PAYMENT,
    }
    if app.status not in allowed_from:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Payment link can only be generated from CALLED, APPROVED, or AWAITING_PAYMENT status. "
                f"Current status: {app.status.value}"
            ),
        )

    intent = await create_payment_intent(
        customer_email=app.email,
        customer_name=app.kontaktperson,
        amount_dkk=body.amount_dkk,
        application_id=application_id,
    )

    # Secure token: customer presents this to /api/v1/payment/init to get client_secret
    payment_token = secrets.token_urlsafe(32)
    checkout_url = (
        settings.app_base_url.rstrip("/")
        + f"/payment/checkout?token={payment_token}"
    )

    prev_status = app.status
    app.stripe_payment_intent_id = intent.id
    app.payment_token = payment_token
    app.payment_url = checkout_url
    app.stripe_session_id = None
    app.status = CustomerApplicationStatus.AWAITING_PAYMENT
    app.updated_at = datetime.now(timezone.utc)
    await _add_state_log(
        db, app,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.AWAITING_PAYMENT,
        changed_by="system",
        note=f"Payment link generated — {body.amount_dkk} DKK — intent {intent.id}",
    )
    await db.commit()

    email_sent = False
    if body.send_email:
        try:
            await send_payment_link_email(
                customer_email=app.email,
                customer_name=app.kontaktperson,
                company_name=app.firmanavn,
                payment_url=checkout_url,
                amount_dkk=body.amount_dkk,
            )
            email_sent = True
        except Exception as exc:
            log.error("payment_link.email_failed", application_id=str(application_id), error=str(exc))

    return PaymentLinkResponse(
        application_id=application_id,
        payment_url=checkout_url,
        stripe_payment_intent_id=intent.id,
        amount_dkk=body.amount_dkk,
        email_sent=email_sent,
    )


@router.post(
    "/admin/applications/{application_id}/payment-link/expire",
    summary="Clear the stored Stripe payment link from an application",
)
async def expire_payment_link(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_key),
) -> dict:
    app = await _get_application_or_404(application_id, db)
    app.stripe_session_id = None
    app.payment_url = None
    app.payment_token = None
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"expired": True, "application_id": str(application_id)}


@router.get("/payment/config", include_in_schema=False)
async def payment_config():
    """Return Stripe publishable key for the custom checkout page (public, no auth required)."""
    from src.config import get_settings
    settings = get_settings()
    return {"publishable_key": settings.stripe_publishable_key}


@router.get(
    "/payment/init",
    response_model=PaymentInitResponse,
    summary="Get Payment Intent client_secret for the custom checkout page",
)
@limiter.limit("30/minute")
async def payment_init(
    request: Request,
    token: str = Query(..., description="Secure payment token from the checkout URL"),
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint for the custom checkout page.
    Looks up the application by payment_token, retrieves the Stripe Payment Intent,
    and returns the client_secret so the frontend can render Stripe Elements.
    """
    from src.payments import retrieve_payment_intent

    result = await db.execute(
        select(CustomerApplication).where(CustomerApplication.payment_token == token)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail="Payment session not found")

    if app.status != CustomerApplicationStatus.AWAITING_PAYMENT:
        raise HTTPException(status_code=410, detail="Payment session is no longer active")

    if not app.stripe_payment_intent_id:
        raise HTTPException(status_code=500, detail="Payment intent not initialised")

    try:
        intent = await retrieve_payment_intent(app.stripe_payment_intent_id)
    except Exception as exc:
        log.error("payment_init.stripe_retrieve_failed", error=str(exc), application_id=str(app.id))
        raise HTTPException(status_code=502, detail="Could not retrieve payment details")

    # Extract amount_dkk from intent (stored in øre)
    amount_dkk = (intent.get("amount") or 0) // 100

    return PaymentInitResponse(
        client_secret=intent["client_secret"],
        product_name="AIScore Rapport",
        amount_dkk=amount_dkk,
        customer_email=app.email,
        customer_name=app.kontaktperson,
        order_id=str(app.id),
    )


# ─────────────────────────────────────────────
# Stripe webhook (payment confirmed + subscriptions)
# ─────────────────────────────────────────────

def _tier_from_price_id(price_id: str) -> SubscriptionTier:
    """Map a Stripe price ID to a SubscriptionTier. Falls back to STARTER for unknown IDs."""
    from src.config import get_settings
    settings = get_settings()
    mapping = {
        settings.aiselect_price_starter: SubscriptionTier.STARTER,
        settings.aiselect_price_pro: SubscriptionTier.PRO,
        settings.aiselect_price_enterprise: SubscriptionTier.ENTERPRISE,
    }
    return mapping.get(price_id, SubscriptionTier.STARTER)


def _subscription_status_from_stripe(stripe_status: str) -> SubscriptionStatus:
    """Map a Stripe subscription status string to our SubscriptionStatus enum."""
    return {
        "active": SubscriptionStatus.ACTIVE,
        "trialing": SubscriptionStatus.TRIALING,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELLED,
        "cancelled": SubscriptionStatus.CANCELLED,
        "incomplete": SubscriptionStatus.INCOMPLETE,
        "incomplete_expired": SubscriptionStatus.INCOMPLETE_EXPIRED,
    }.get(stripe_status, SubscriptionStatus.INCOMPLETE)


async def _upsert_subscription(
    db: AsyncSession,
    stripe_subscription_id: str,
    stripe_customer_id: str,
    customer_email: str,
    company_name: str,
    tier: SubscriptionTier,
    status: SubscriptionStatus,
    current_period_start: Optional[datetime],
    current_period_end: Optional[datetime],
    cancelled_at: Optional[datetime] = None,
) -> AISelectSubscription:
    """Create or update an AISelectSubscription row."""
    result = await db.execute(
        select(AISelectSubscription).where(
            AISelectSubscription.stripe_subscription_id == stripe_subscription_id
        )
    )
    sub = result.scalar_one_or_none()

    if sub is None:
        sub = AISelectSubscription(
            customer_email=customer_email,
            company_name=company_name,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
        )
        db.add(sub)

    sub.tier = tier
    sub.status = status
    sub.current_period_start = current_period_start
    sub.current_period_end = current_period_end
    sub.cancelled_at = cancelled_at
    sub.updated_at = datetime.now(timezone.utc)
    return sub


@router.post("/verify-payment")
@limiter.limit("30/minute")
async def verify_payment(
    request: Request,
    order_id: uuid.UUID,
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Called from the payment success page. Retrieves the Stripe session directly
    and transitions the application AWAITING_PAYMENT → PAID if payment_status == paid.
    Idempotent — safe to call even if the webhook already handled the transition.
    """
    from src.payments import retrieve_checkout_session

    try:
        stripe_session = await retrieve_checkout_session(session_id)
    except Exception as exc:
        log.error("verify_payment.stripe_error", order_id=str(order_id), error=str(exc))
        raise HTTPException(status_code=502, detail="Could not verify payment with Stripe")

    if stripe_session.get("payment_status") != "paid":
        raise HTTPException(status_code=402, detail="Payment not yet confirmed")

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == order_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if app.status == CustomerApplicationStatus.AWAITING_PAYMENT:
        payment_intent_id = stripe_session.get("payment_intent")
        prev_status = app.status
        app.status = CustomerApplicationStatus.PAID
        app.stripe_payment_intent_id = payment_intent_id
        app.updated_at = datetime.now(timezone.utc)
        await _add_state_log(
            db, app,
            from_status=prev_status,
            to_status=CustomerApplicationStatus.PAID,
            changed_by="stripe_verify",
            note=f"Payment verified via success page — session {session_id}",
        )
        await db.commit()
        log.info("verify_payment.confirmed", application_id=str(order_id))

        amount_total = stripe_session.get("amount_total")
        amount_dkk_val = (amount_total // 100) if amount_total is not None else None
        try:
            from src.payments.emailer import send_admin_payment_notification_email
            await send_admin_payment_notification_email(
                company_name=app.firmanavn,
                kontaktperson=app.kontaktperson,
                customer_email=app.email,
                amount_dkk=amount_dkk_val,
                payment_intent_id=payment_intent_id,
            )
        except Exception as exc:
            log.error("verify_payment.admin_notification_failed", application_id=str(order_id), error=str(exc))

    return {"status": "paid", "application_id": str(order_id)}


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Unified Stripe webhook endpoint.

    Handles:
    - checkout.session.completed  — one-time payment (AIScore) or new subscription (AISelect)
    - customer.subscription.updated — tier/status change on existing subscription
    - customer.subscription.deleted — subscription cancelled by customer or Stripe
    - invoice.payment_failed        — payment failed; flags subscription as past_due
    """
    from src.payments import construct_stripe_event
    from src.payments.emailer import (
        send_payment_confirmation_email,
        send_subscription_confirmation_email,
        send_subscription_updated_email,
        send_subscription_cancelled_email,
        send_payment_failed_email,
    )
    from src.config import get_settings
    import stripe as _stripe

    settings = get_settings()
    if not settings.stripe_webhook_secret:
        log.error("stripe_webhook.secret_not_configured")
        raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_stripe_event(payload, sig_header)
    except (_stripe.error.SignatureVerificationError, ValueError) as exc:
        log.warning("stripe_webhook.invalid_signature", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event_type: str = event["type"]
    log.info("stripe_webhook.received", event_type=event_type, event_id=event.get("id"))

    # ── checkout.session.completed ──────────────────────────────────────────
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        mode = session.get("mode")

        if mode == "payment":
            # AIScore one-time payment
            application_id_str = session.get("metadata", {}).get("order_id")
            payment_intent_id = session.get("payment_intent")

            if not application_id_str:
                log.warning("stripe_webhook.missing_order_id", session_id=session.get("id"))
                return {"received": True}

            try:
                application_id = uuid.UUID(application_id_str)
            except ValueError:
                log.warning("stripe_webhook.invalid_order_id", order_id=application_id_str)
                return {"received": True}

            result = await db.execute(
                select(CustomerApplication)
                .options(selectinload(CustomerApplication.state_logs))
                .where(CustomerApplication.id == application_id)
            )
            app = result.scalar_one_or_none()
            if not app:
                log.warning("stripe_webhook.application_not_found", application_id=application_id_str)
                return {"received": True}

            if app.status == CustomerApplicationStatus.AWAITING_PAYMENT:
                prev_status = app.status
                now = datetime.now(timezone.utc)

                # AWAITING_PAYMENT → PAID (admin will manually advance to IN_PRODUCTION)
                app.status = CustomerApplicationStatus.PAID
                app.stripe_payment_intent_id = payment_intent_id
                app.updated_at = now
                await _add_state_log(
                    db, app,
                    from_status=prev_status,
                    to_status=CustomerApplicationStatus.PAID,
                    changed_by="stripe",
                    note=f"Payment confirmed — intent {payment_intent_id}",
                )
                await db.commit()
                log.info(
                    "stripe_webhook.payment_confirmed",
                    application_id=application_id_str,
                )

                amount_total = session.get("amount_total")
                amount_dkk = (amount_total // 100) if amount_total is not None else None
                try:
                    await send_payment_confirmation_email(
                        customer_email=app.email,
                        customer_name=app.kontaktperson,
                        company_name=app.firmanavn,
                        amount_dkk=amount_dkk,
                        payment_intent_id=payment_intent_id,
                    )
                except Exception as exc:
                    log.error(
                        "stripe_webhook.payment_confirmation_email_failed",
                        application_id=application_id_str,
                        error=str(exc),
                    )
                try:
                    from src.payments.emailer import send_admin_payment_notification_email
                    await send_admin_payment_notification_email(
                        company_name=app.firmanavn,
                        kontaktperson=app.kontaktperson,
                        customer_email=app.email,
                        amount_dkk=amount_dkk,
                        payment_intent_id=payment_intent_id,
                    )
                except Exception as exc:
                    log.error("stripe_webhook.admin_notification_failed", application_id=application_id_str, error=str(exc))

        elif mode == "subscription":
            # AISelect new subscription checkout completed
            subscription_id = session.get("subscription")
            stripe_customer_id = session.get("customer")
            customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email", "")
            metadata = session.get("metadata", {})
            company_name = metadata.get("company_name", "")
            customer_name = metadata.get("customer_name", customer_email)
            tier_str = metadata.get("tier", "")

            if not subscription_id:
                log.warning("stripe_webhook.subscription.missing_subscription_id", session_id=session.get("id"))
                return {"received": True}

            # Fetch subscription details from Stripe to get price ID and period
            def _retrieve_sub(sub_id: str) -> Optional[dict]:
                from src.config import get_settings as _gs
                _stripe.api_key = _gs().stripe_secret_key
                return _stripe.Subscription.retrieve(sub_id)

            try:
                stripe_sub = await asyncio.to_thread(_retrieve_sub, subscription_id)
            except Exception as exc:
                log.error("stripe_webhook.subscription.retrieve_failed", error=str(exc))
                stripe_sub = None

            # Derive tier: prefer metadata, fall back to price ID mapping
            if tier_str and tier_str in SubscriptionTier._value2member_map_:
                tier = SubscriptionTier(tier_str)
            elif stripe_sub and stripe_sub.get("items", {}).get("data"):
                price_id = stripe_sub["items"]["data"][0].get("price", {}).get("id", "")
                tier = _tier_from_price_id(price_id)
            else:
                tier = SubscriptionTier.STARTER

            period_start = (
                datetime.utcfromtimestamp(stripe_sub["current_period_start"])
                if stripe_sub and stripe_sub.get("current_period_start") else None
            )
            period_end = (
                datetime.utcfromtimestamp(stripe_sub["current_period_end"])
                if stripe_sub and stripe_sub.get("current_period_end") else None
            )

            await _upsert_subscription(
                db,
                stripe_subscription_id=subscription_id,
                stripe_customer_id=stripe_customer_id or "",
                customer_email=customer_email,
                company_name=company_name,
                tier=tier,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=period_start,
                current_period_end=period_end,
            )
            await db.commit()
            log.info(
                "stripe_webhook.subscription.activated",
                subscription_id=subscription_id,
                tier=tier,
                customer_email=customer_email,
            )

            if customer_email:
                period_end_str = period_end.strftime("%d.%m.%Y") if period_end else None
                await send_subscription_confirmation_email(
                    customer_email=customer_email,
                    customer_name=customer_name,
                    company_name=company_name,
                    tier=tier.value,
                    period_end=period_end_str,
                )

    # ── customer.subscription.updated ──────────────────────────────────────
    elif event_type == "customer.subscription.updated":
        sub_obj = event["data"]["object"]
        subscription_id = sub_obj.get("id")
        stripe_customer_id = sub_obj.get("customer", "")
        stripe_status = sub_obj.get("status", "")
        items_data = sub_obj.get("items", {}).get("data", [])
        price_id = items_data[0].get("price", {}).get("id", "") if items_data else ""

        new_tier = _tier_from_price_id(price_id)
        new_status = _subscription_status_from_stripe(stripe_status)
        period_start = (
            datetime.utcfromtimestamp(sub_obj["current_period_start"])
            if sub_obj.get("current_period_start") else None
        )
        period_end = (
            datetime.utcfromtimestamp(sub_obj["current_period_end"])
            if sub_obj.get("current_period_end") else None
        )

        # Look up existing subscription record to detect tier change
        existing_result = await db.execute(
            select(AISelectSubscription).where(
                AISelectSubscription.stripe_subscription_id == subscription_id
            )
        )
        existing = existing_result.scalar_one_or_none()
        old_tier = existing.tier if existing else None
        customer_email = existing.customer_email if existing else ""
        company_name = existing.company_name if existing else ""

        await _upsert_subscription(
            db,
            stripe_subscription_id=subscription_id,
            stripe_customer_id=stripe_customer_id,
            customer_email=customer_email,
            company_name=company_name,
            tier=new_tier,
            status=new_status,
            current_period_start=period_start,
            current_period_end=period_end,
        )
        await db.commit()
        log.info(
            "stripe_webhook.subscription.updated",
            subscription_id=subscription_id,
            tier=new_tier,
            status=new_status,
        )

        # Send tier-change email only when tier actually changed
        if customer_email and old_tier is not None and old_tier != new_tier:
            await send_subscription_updated_email(
                customer_email=customer_email,
                customer_name=customer_email,
                company_name=company_name,
                old_tier=old_tier.value,
                new_tier=new_tier.value,
            )

    # ── customer.subscription.deleted ──────────────────────────────────────
    elif event_type == "customer.subscription.deleted":
        sub_obj = event["data"]["object"]
        subscription_id = sub_obj.get("id")
        stripe_customer_id = sub_obj.get("customer", "")
        cancelled_at_ts = sub_obj.get("canceled_at")
        cancelled_at = datetime.utcfromtimestamp(cancelled_at_ts) if cancelled_at_ts else datetime.now(timezone.utc)
        period_end = (
            datetime.utcfromtimestamp(sub_obj["current_period_end"])
            if sub_obj.get("current_period_end") else None
        )

        existing_result = await db.execute(
            select(AISelectSubscription).where(
                AISelectSubscription.stripe_subscription_id == subscription_id
            )
        )
        existing = existing_result.scalar_one_or_none()
        customer_email = existing.customer_email if existing else ""
        company_name = existing.company_name if existing else ""
        tier = existing.tier if existing else SubscriptionTier.STARTER

        await _upsert_subscription(
            db,
            stripe_subscription_id=subscription_id,
            stripe_customer_id=stripe_customer_id,
            customer_email=customer_email,
            company_name=company_name,
            tier=tier,
            status=SubscriptionStatus.CANCELLED,
            current_period_start=existing.current_period_start if existing else None,
            current_period_end=period_end,
            cancelled_at=cancelled_at,
        )
        await db.commit()
        log.info(
            "stripe_webhook.subscription.deleted",
            subscription_id=subscription_id,
            customer_email=customer_email,
        )

        if customer_email:
            period_end_str = period_end.strftime("%d.%m.%Y") if period_end else None
            await send_subscription_cancelled_email(
                customer_email=customer_email,
                customer_name=customer_email,
                company_name=company_name,
                tier=tier.value,
                period_end=period_end_str,
            )

    # ── invoice.payment_failed ──────────────────────────────────────────────
    elif event_type == "invoice.payment_failed":
        invoice = event["data"]["object"]
        subscription_id = invoice.get("subscription")
        amount_due = invoice.get("amount_due")  # in øre (smallest currency unit)
        amount_dkk = (amount_due // 100) if amount_due is not None else None

        if not subscription_id:
            log.warning("stripe_webhook.invoice.no_subscription", invoice_id=invoice.get("id"))
            return {"received": True}

        existing_result = await db.execute(
            select(AISelectSubscription).where(
                AISelectSubscription.stripe_subscription_id == subscription_id
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            existing.status = SubscriptionStatus.PAST_DUE
            existing.updated_at = datetime.now(timezone.utc)
            await db.commit()
            log.info(
                "stripe_webhook.invoice.payment_failed",
                subscription_id=subscription_id,
                customer_email=existing.customer_email,
            )

            await send_payment_failed_email(
                customer_email=existing.customer_email,
                customer_name=existing.customer_email,
                company_name=existing.company_name,
                tier=existing.tier.value,
                amount_dkk=amount_dkk,
            )
        else:
            log.warning(
                "stripe_webhook.invoice.subscription_not_found",
                subscription_id=subscription_id,
            )

    # ── payment_intent.succeeded (custom checkout page — AIScore one-time) ───
    elif event_type == "payment_intent.succeeded":
        pi = event["data"]["object"]
        pi_id = pi.get("id")
        order_id_str = (pi.get("metadata") or {}).get("order_id")

        if not order_id_str:
            log.warning("stripe_webhook.payment_intent.succeeded.missing_order_id", pi_id=pi_id)
            return {"received": True}

        try:
            application_id = uuid.UUID(order_id_str)
        except ValueError:
            log.warning("stripe_webhook.payment_intent.succeeded.invalid_order_id", order_id=order_id_str)
            return {"received": True}

        result = await db.execute(
            select(CustomerApplication)
            .options(selectinload(CustomerApplication.state_logs))
            .where(CustomerApplication.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            log.warning("stripe_webhook.payment_intent.succeeded.app_not_found", application_id=order_id_str)
            return {"received": True}

        if app.status == CustomerApplicationStatus.AWAITING_PAYMENT:
            from src.payments.emailer import (
                send_payment_confirmation_email,
                send_admin_payment_notification_email,
            )
            prev_status = app.status
            now = datetime.now(timezone.utc)

            app.status = CustomerApplicationStatus.PAID
            app.stripe_payment_intent_id = pi_id
            app.payment_token = None  # invalidate after successful payment
            app.updated_at = now
            await _add_state_log(
                db, app,
                from_status=prev_status,
                to_status=CustomerApplicationStatus.PAID,
                changed_by="stripe",
                note=f"Payment confirmed — intent {pi_id}",
            )
            await db.commit()
            log.info("stripe_webhook.payment_intent.succeeded", application_id=order_id_str)

            amount_dkk = ((pi.get("amount") or 0) // 100) or None
            try:
                await send_payment_confirmation_email(
                    customer_email=app.email,
                    customer_name=app.kontaktperson,
                    company_name=app.firmanavn,
                    amount_dkk=amount_dkk,
                    payment_intent_id=pi_id,
                )
            except Exception as exc:
                log.error("stripe_webhook.payment_intent.succeeded.email_failed", error=str(exc))
            try:
                await send_admin_payment_notification_email(
                    company_name=app.firmanavn,
                    kontaktperson=app.kontaktperson,
                    customer_email=app.email,
                    amount_dkk=amount_dkk,
                    payment_intent_id=pi_id,
                )
            except Exception as exc:
                log.error("stripe_webhook.payment_intent.succeeded.admin_notify_failed", error=str(exc))
        else:
            log.info(
                "stripe_webhook.payment_intent.succeeded.ignored",
                application_id=order_id_str,
                status=app.status.value,
            )

    # ── payment_intent.payment_failed (one-time AIScore payment) ───────────
    elif event_type == "payment_intent.payment_failed":
        pi = event["data"]["object"]
        pi_id = pi.get("id")
        last_error = pi.get("last_payment_error") or {}
        reason = last_error.get("message") or last_error.get("code") or "Payment failed"

        result = await db.execute(
            select(CustomerApplication).where(
                CustomerApplication.stripe_payment_intent_id == pi_id
            )
        )
        app = result.scalar_one_or_none()
        if app and app.status == CustomerApplicationStatus.AWAITING_PAYMENT:
            app.payment_failure_reason = reason
            app.payment_failed_at = datetime.now(timezone.utc)
            await db.commit()
            log.info(
                "stripe_webhook.payment_intent.failed",
                application_id=str(app.id),
                reason=reason,
            )

    else:
        log.debug("stripe_webhook.ignored_event_type", event_type=event_type)

    return {"received": True}


# ─────────────────────────────────────────────
# Calendly webhook (meeting booked / cancelled)
# ─────────────────────────────────────────────

def _verify_calendly_signature(payload: bytes, header: str, secret: str) -> bool:
    """
    Calendly signs webhooks with HMAC-SHA256.
    Header format: t=<timestamp>,v1=<hex_digest>
    Signed message: <timestamp>.<raw_body>
    Rejects payloads older than 5 minutes to prevent replay attacks.
    """
    import hashlib
    import hmac
    import time

    parts: dict[str, str] = {}
    for part in header.split(","):
        k, _, v = part.partition("=")
        parts[k.strip()] = v.strip()

    timestamp = parts.get("t", "")
    v1 = parts.get("v1", "")
    if not timestamp or not v1:
        return False

    try:
        if abs(int(time.time()) - int(timestamp)) > 300:
            return False
    except ValueError:
        return False

    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


@router.post("/webhooks/calendly", include_in_schema=False)
async def calendly_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receives Calendly invitee.created and invitee.canceled events.

    invitee.created  → if application is APPROVED, advance to CALLED and store event URI.
    invitee.canceled → if application is CALLED, revert to APPROVED and clear event URI.

    Email and invitee.email are used to match the application.
    """
    from src.config import get_settings
    from src.payments.emailer import send_calendly_booking_email

    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("calendly-webhook-signature", "")

    if not settings.calendly_webhook_secret:
        log.error("calendly_webhook.secret_not_configured")
        raise HTTPException(status_code=500, detail="Webhook signing secret not configured")

    if not _verify_calendly_signature(payload, sig_header, settings.calendly_webhook_secret):
        log.warning("calendly_webhook.invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid Calendly signature")

    try:
        import json as _json
        event = _json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("event", "")
    payload_data = event.get("payload", {})

    invitee = payload_data.get("invitee", {})
    invitee_email: str = invitee.get("email", "").lower().strip()
    event_uri: str = payload_data.get("event", {}).get("uri", "") if isinstance(payload_data.get("event"), dict) else ""
    scheduled_at: str = payload_data.get("event", {}).get("start_time", "") if isinstance(payload_data.get("event"), dict) else ""

    if not invitee_email:
        log.warning("calendly_webhook.missing_invitee_email", event_type=event_type)
        return {"received": True}

    # Find matching application by email (most-recent non-terminal match)
    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.email == invitee_email)
        .order_by(CustomerApplication.created_at.desc())
        .limit(1)
    )
    app = result.scalar_one_or_none()

    if not app:
        log.warning("calendly_webhook.application_not_found", email=invitee_email, event_type=event_type)
        return {"received": True}

    if event_type == "invitee.created":
        if app.status == CustomerApplicationStatus.APPROVED:
            prev_status = app.status
            app.status = CustomerApplicationStatus.CALLED
            app.calendly_event_uri = event_uri or None
            app.updated_at = datetime.now(timezone.utc)
            await _add_state_log(
                db, app,
                from_status=prev_status,
                to_status=CustomerApplicationStatus.CALLED,
                changed_by="calendly",
                note=f"Calendly møde booket — {scheduled_at or 'tidspunkt ukendt'}",
            )
            await db.commit()
            log.info("calendly_webhook.booking_created", application_id=str(app.id), email=invitee_email)

            try:
                await send_calendly_booking_email(
                    company_name=app.firmanavn,
                    kontaktperson=app.kontaktperson,
                    customer_email=app.email,
                    event_uri=event_uri,
                    scheduled_at=scheduled_at or None,
                    canceled=False,
                )
            except Exception as exc:
                log.error("calendly_webhook.email_failed", application_id=str(app.id), error=str(exc))
        else:
            log.info(
                "calendly_webhook.booking_skipped_wrong_status",
                application_id=str(app.id),
                status=app.status.value,
            )

    elif event_type == "invitee.canceled":
        if app.status == CustomerApplicationStatus.CALLED:
            prev_status = app.status
            stored_event_uri = app.calendly_event_uri or ""
            app.status = CustomerApplicationStatus.APPROVED
            app.calendly_event_uri = None
            app.updated_at = datetime.now(timezone.utc)
            await _add_state_log(
                db, app,
                from_status=prev_status,
                to_status=CustomerApplicationStatus.APPROVED,
                changed_by="calendly",
                note="Calendly møde aflyst — tilbage til APPROVED",
            )
            await db.commit()
            log.info("calendly_webhook.booking_canceled", application_id=str(app.id), email=invitee_email)

            try:
                await send_calendly_booking_email(
                    company_name=app.firmanavn,
                    kontaktperson=app.kontaktperson,
                    customer_email=app.email,
                    event_uri=event_uri or stored_event_uri,
                    scheduled_at=None,
                    canceled=True,
                )
            except Exception as exc:
                log.error("calendly_webhook.cancel_email_failed", application_id=str(app.id), error=str(exc))
        else:
            log.info(
                "calendly_webhook.cancel_skipped_wrong_status",
                application_id=str(app.id),
                status=app.status.value,
            )

    return {"received": True}


# ─────────────────────────────────────────────
# QC loop — 3+3 escalation
# ─────────────────────────────────────────────

@router.post(
    "/admin/applications/{application_id}/qc-result",
    response_model=ApplicationResponse,
)
@limiter.limit("30/minute")
async def submit_qc_result(
    request: Request,
    application_id: uuid.UUID,
    body: QCResultSubmit,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a QC result for a report in QC_REVIEW.

    Passing → QC_PASSED.
    Failing → increments qc_failure_count and drives the 3+3 escalation:
      - Failures 1-2 (pre-escalation): auto-retry → back to IN_PRODUCTION
      - Failure 3 (pre-escalation):    alert to research + Dennis → ESCALATED
      - Failures 1-2 (post-escalation): auto-retry → back to IN_PRODUCTION
      - Failure 3 (post-escalation):   final alert → CANCELLED
    """
    from src.payments.emailer import send_qc_escalation_email

    app = await _get_application_or_404(application_id, db)

    if app.status != CustomerApplicationStatus.QC_REVIEW:
        raise HTTPException(
            status_code=422,
            detail=f"Application must be in QC_REVIEW to submit a result. Current: {app.status.value}",
        )

    prev_status = app.status

    if body.passed:
        app.status = CustomerApplicationStatus.QC_PASSED
        app.updated_at = datetime.now(timezone.utc)
        await _add_state_log(
            db, app,
            from_status=prev_status,
            to_status=CustomerApplicationStatus.QC_PASSED,
            changed_by="qc",
            note=body.notes or "QC passed",
        )
        await db.commit()
        result = await db.execute(
            select(CustomerApplication)
            .options(selectinload(CustomerApplication.state_logs))
            .where(CustomerApplication.id == application_id)
        )
        return result.scalar_one()

    # QC failed
    app.qc_failure_count += 1
    failure_count = app.qc_failure_count
    note_prefix = f"QC failure #{failure_count}"

    if failure_count < _QC_ESCALATION_THRESHOLD:
        # Auto-retry: back to IN_PRODUCTION
        app.status = CustomerApplicationStatus.IN_PRODUCTION
        app.updated_at = datetime.now(timezone.utc)
        await _add_state_log(
            db, app,
            from_status=prev_status,
            to_status=CustomerApplicationStatus.IN_PRODUCTION,
            changed_by="system",
            note=f"{note_prefix} — auto-retry. Notes: {body.notes or 'none'}",
        )
        log.info(
            "qc.auto_retry",
            application_id=str(application_id),
            failure_count=failure_count,
            escalated=app.has_been_escalated,
        )

    elif not app.has_been_escalated:
        # 3rd pre-escalation failure → alert + ESCALATED
        app.status = CustomerApplicationStatus.ESCALATED
        app.updated_at = datetime.now(timezone.utc)
        await _add_state_log(
            db, app,
            from_status=prev_status,
            to_status=CustomerApplicationStatus.ESCALATED,
            changed_by="system",
            note=f"{note_prefix} — escalating to manual review. Notes: {body.notes or 'none'}",
        )
        try:
            await send_qc_escalation_email(
                company_name=app.firmanavn,
                application_id=str(application_id),
                failure_count=failure_count,
                is_final_escalation=False,
                admin_note=body.notes,
            )
        except Exception as exc:
            log.error("qc.escalation_email_failed", application_id=str(application_id), error=str(exc))

    else:
        # 3rd post-escalation failure → final alert + CANCELLED
        app.status = CustomerApplicationStatus.CANCELLED
        app.updated_at = datetime.now(timezone.utc)
        await _add_state_log(
            db, app,
            from_status=prev_status,
            to_status=CustomerApplicationStatus.CANCELLED,
            changed_by="system",
            note=f"{note_prefix} (post-escalation) — report cancelled. Notes: {body.notes or 'none'}",
        )
        try:
            await send_qc_escalation_email(
                company_name=app.firmanavn,
                application_id=str(application_id),
                failure_count=failure_count,
                is_final_escalation=True,
                admin_note=body.notes,
            )
        except Exception as exc:
            log.error("qc.cancellation_email_failed", application_id=str(application_id), error=str(exc))

    await db.commit()
    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == application_id)
    )
    return result.scalar_one()


@router.post(
    "/admin/applications/{application_id}/manual-correction",
    response_model=ApplicationResponse,
)
@limiter.limit("30/minute")
async def submit_manual_correction(
    request: Request,
    application_id: uuid.UUID,
    body: ManualCorrectionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Dennis submits a manual correction for an ESCALATED application.
    Resets qc_failure_count, marks has_been_escalated=True, moves to IN_PRODUCTION via RETRY.
    """
    app = await _get_application_or_404(application_id, db)

    if app.status != CustomerApplicationStatus.ESCALATED:
        raise HTTPException(
            status_code=422,
            detail=f"Application must be in ESCALATED status for manual correction. Current: {app.status.value}",
        )

    prev_status = app.status

    # Transition: ESCALATED → RETRY → IN_PRODUCTION (two log entries, one commit)
    app.status = CustomerApplicationStatus.RETRY
    app.has_been_escalated = True
    app.qc_failure_count = 0  # reset for the post-escalation cycle
    app.updated_at = datetime.now(timezone.utc)
    await _add_state_log(
        db, app,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.RETRY,
        changed_by="admin",
        note=body.note or "Manual correction applied",
    )

    # Immediately advance to IN_PRODUCTION
    app.status = CustomerApplicationStatus.IN_PRODUCTION
    app.updated_at = datetime.now(timezone.utc)
    await _add_state_log(
        db, app,
        from_status=CustomerApplicationStatus.RETRY,
        to_status=CustomerApplicationStatus.IN_PRODUCTION,
        changed_by="system",
        note="Back in production after manual correction",
    )

    await db.commit()
    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == application_id)
    )
    return result.scalar_one()


# ─────────────────────────────────────────────
# AISelect: password reset flow
# ─────────────────────────────────────────────

_RESET_TOKEN_TTL_HOURS = 1


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random salt. Returns 'salt_hex:key_hex'."""
    salt = secrets.token_bytes(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + key.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, key_hex = stored.split(":", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return _hmac.compare_digest(key.hex(), key_hex)


@router.post(
    "/aiselect/auth/forgot-password",
    response_model=PasswordResetResponse,
    summary="Request a password reset email",
)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> PasswordResetResponse:
    """
    Send a password reset link to the given email if it belongs to an AISelect subscriber.
    Always returns 200 so the caller cannot enumerate valid emails.
    """
    email = body.email.lower().strip()

    sub_result = await db.execute(
        select(AISelectSubscription)
        .where(AISelectSubscription.customer_email == email)
        .limit(1)
    )
    sub = sub_result.scalar_one_or_none()

    if sub is not None:
        from src.config import get_settings
        from src.payments.emailer import send_password_reset_email

        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=_RESET_TOKEN_TTL_HOURS)

        await db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.email == email,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(timezone.utc),
            )
            .values(used_at=datetime.now(timezone.utc))
        )

        reset_token_row = PasswordResetToken(
            email=email,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(reset_token_row)
        await db.commit()

        settings = get_settings()
        reset_url = f"{settings.aiselect_base_url}/reset-password?token={raw_token}"

        try:
            await send_password_reset_email(customer_email=email, reset_url=reset_url)
            log.info("password_reset.email_sent", email=email)
        except Exception as exc:
            log.error("password_reset.email_failed", email=email, error=str(exc))

    return PasswordResetResponse(
        message="Hvis e-mailadressen er registreret, er der sendt et nulstillingslink."
    )


@router.post(
    "/aiselect/auth/reset-password",
    response_model=PasswordResetResponse,
    summary="Set a new password using a reset token",
)
@limiter.limit("10/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> PasswordResetResponse:
    """
    Validate the reset token and set the new password on the matching AISelect subscription.
    """
    token_hash = _hash_token(body.token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .limit(1)
    )
    reset_token_row = result.scalar_one_or_none()

    if reset_token_row is None:
        raise HTTPException(
            status_code=400,
            detail="Ugyldigt eller udløbet nulstillingslink. Anmod venligst om et nyt.",
        )

    sub_result = await db.execute(
        select(AISelectSubscription)
        .where(AISelectSubscription.customer_email == reset_token_row.email)
        .limit(1)
    )
    sub = sub_result.scalar_one_or_none()

    if sub is None:
        raise HTTPException(status_code=400, detail="Ingen konto fundet for dette nulstillingslink.")

    sub.password_hash = _hash_password(body.new_password)
    sub.updated_at = datetime.now(timezone.utc)
    reset_token_row.used_at = now
    await db.commit()

    log.info("password_reset.completed", email=reset_token_row.email)

    return PasswordResetResponse(
        message="Din adgangskode er nu opdateret. Du kan logge ind med din nye adgangskode."
    )


# ─────────────────────────────────────────────
# Public: rapport generation status (customer polling)
# ─────────────────────────────────────────────

# Statuses where scoring is actively running (maps to UI "generating" phase)
_GENERATING_STATUSES = {
    CustomerApplicationStatus.PAID,
    CustomerApplicationStatus.IN_PRODUCTION,
}

# Statuses where scoring is done but QC/review is ongoing
_REVIEWING_STATUSES = {
    CustomerApplicationStatus.QC_REVIEW,
    CustomerApplicationStatus.QC_FAILED,
    CustomerApplicationStatus.RETRY,
    CustomerApplicationStatus.ESCALATED,
    CustomerApplicationStatus.QC_PASSED,
}

# Terminal success statuses — rapport is ready
_DONE_STATUSES = {
    CustomerApplicationStatus.READY_FOR_REVIEW_CALL,
}

# Providers in the order they are displayed in the UI
_PROVIDERS = ["openai", "claude", "gemini", "perplexity"]


def _providers_done_for_status(status: CustomerApplicationStatus) -> int:
    """Return how many of the 4 provider steps to show as done for a given status."""
    if status in _DONE_STATUSES or status in _REVIEWING_STATUSES:
        return 4
    if status == CustomerApplicationStatus.IN_PRODUCTION:
        return 2
    return 0


@router.get("/applications/{application_id}/status")
@limiter.limit("30/minute")
async def get_application_status(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Public — returns current status of an application by UUID (the UUID is the secret)."""
    result = await db.execute(
        select(CustomerApplication).where(CustomerApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")

    STATUS_LABELS: dict[CustomerApplicationStatus, str] = {
        CustomerApplicationStatus.APPLIED:              "Modtaget",
        CustomerApplicationStatus.UNDER_REVIEW:         "Under behandling",
        CustomerApplicationStatus.APPROVED:             "Godkendt",
        CustomerApplicationStatus.REJECTED:             "Afvist",
        CustomerApplicationStatus.CALLED:               "Møde booket",
        CustomerApplicationStatus.AWAITING_PAYMENT:     "Afventer betaling",
        CustomerApplicationStatus.PAID:                 "Betaling bekræftet",
        CustomerApplicationStatus.IN_PRODUCTION:        "Analyserer",
        CustomerApplicationStatus.QC_REVIEW:            "Kvalitetssikring",
        CustomerApplicationStatus.QC_PASSED:            "Analyse klar",
        CustomerApplicationStatus.QC_FAILED:            "Analyserer",
        CustomerApplicationStatus.ESCALATED:            "Analyserer",
        CustomerApplicationStatus.RETRY:                "Analyserer",
        CustomerApplicationStatus.READY_FOR_REVIEW_CALL: "I produktion",
        CustomerApplicationStatus.CANCELLED:            "Annulleret",
    }

    return {
        "application_id": str(application_id),
        "company_name":   app.firmanavn,
        "status":         app.status.value,
        "status_label":   STATUS_LABELS.get(app.status, app.status.value),
        "submitted_at":   app.submitted_at.isoformat() if app.submitted_at else None,
    }


@router.get("/report-status/{order_id}")
@limiter.limit("30/minute")
async def get_report_status(
    request: Request,
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Public polling endpoint — customers call this every 5 s from the status page.
    Returns phase, providers_done count and an optional download_url when ready.
    """
    result = await db.execute(
        select(CustomerApplication).where(CustomerApplication.id == order_id)
    )
    app = result.scalar_one_or_none()

    if app is None:
        raise HTTPException(status_code=404, detail="Ordre ikke fundet")

    status = app.status

    if status in (CustomerApplicationStatus.CANCELLED, CustomerApplicationStatus.REJECTED):
        return {
            "order_id": str(order_id),
            "status": status.value,
            "phase": "error",
            "providers_done": 0,
            "providers_total": len(_PROVIDERS),
            "message": "Din ordre er blevet annulleret. Kontakt venligst support@aiinstitute.dk.",
            "download_url": None,
        }

    if status in _DONE_STATUSES:
        return {
            "order_id": str(order_id),
            "status": status.value,
            "phase": "done",
            "providers_done": 4,
            "providers_total": len(_PROVIDERS),
            "message": "Rapport klar",
            "download_url": None,
        }

    if status in _REVIEWING_STATUSES:
        return {
            "order_id": str(order_id),
            "status": status.value,
            "phase": "reviewing",
            "providers_done": 4,
            "providers_total": len(_PROVIDERS),
            "message": "Scorer modtaget — kvalitetssikring pågår",
            "download_url": None,
        }

    if status in _GENERATING_STATUSES:
        return {
            "order_id": str(order_id),
            "status": status.value,
            "phase": "generating",
            "providers_done": _providers_done_for_status(status),
            "providers_total": len(_PROVIDERS),
            "message": "Analyserer jeres virksomhed",
            "download_url": None,
        }

    # Early funnel statuses (APPLIED, UNDER_REVIEW, APPROVED, CALLED, AWAITING_PAYMENT)
    return {
        "order_id": str(order_id),
        "status": status.value,
        "phase": "waiting",
        "providers_done": 0,
        "providers_total": len(_PROVIDERS),
        "message": "Betaling bekræftet — analyse starter snart",
        "download_url": None,
    }


# ─────────────────────────────────────────────
# Admin: set scoring data for PDF report
# ─────────────────────────────────────────────

@router.patch(
    "/admin/applications/{application_id}/scoring",
    response_model=ApplicationResponse,
    summary="Admin — sæt OVERALL_SCORE, QUERIES_RUN og RANK på en ansøgning",
)
@limiter.limit("30/minute")
async def set_scoring_data(
    request: Request,
    application_id: uuid.UUID,
    body: ScoringDataUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Persist scoring fields on a CustomerApplication so the PDF report can display real values."""
    app = await _get_application_or_404(application_id, db)

    app.overall_score = body.overall_score
    app.queries_run = body.queries_run
    app.rank = body.rank
    if body.industry is not None:
        app.industry = body.industry
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "scoring_data.updated",
        application_id=str(application_id),
        overall_score=body.overall_score,
        queries_run=body.queries_run,
        rank=body.rank,
    )

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == application_id)
    )
    return result.scalar_one()


# ─────────────────────────────────────────────
# Admin: Production scoring pipeline
# ─────────────────────────────────────────────

async def _generate_questions_then_score(application_id: uuid.UUID) -> None:
    """Background task: generate report_questions if missing, then run scoring pipeline."""
    from src.db.connection import get_session_factory

    await _generate_and_store_report_questions(application_id)

    # Check if generation succeeded before scoring
    async with get_session_factory()() as session:
        result = await session.execute(
            select(CustomerApplication).where(CustomerApplication.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app or not app.report_questions:
            log.error("generate_questions_then_score.no_questions_after_generate", application_id=str(application_id))
            if app:
                app.scoring_status = "error"
                app.scoring_results = {"error": "Rapport-spørgsmål generering fejlede — scoring afbrudt."}
                await session.commit()
            return

    await _run_scoring_pipeline(application_id)


async def _run_scoring_pipeline(application_id: uuid.UUID) -> None:
    """Background task: run report_questions against all 4 LLM providers and store results."""
    from src.config import get_settings
    from src.db.connection import get_session_factory
    from src.llm.providers import REGISTRY
    from src.llm.providers.base import ProviderConfig
    from src.scoring.calculator import AIScore, ScoreCalculator
    from src.scoring.aggregator import aggregate_scores

    settings = get_settings()
    calculator = ScoreCalculator()

    async with get_session_factory()() as session:
        result = await session.execute(
            select(CustomerApplication).where(CustomerApplication.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            log.error("scoring_pipeline.app_not_found", application_id=str(application_id))
            return

        questions = app.report_questions or []
        if not questions:
            app.scoring_status = "error"
            app.scoring_results = {"error": "Ingen report_questions fundet — generer dem først."}
            await session.commit()
            return

        keyword = app.firmanavn
        provider_configs = {
            "openai": ProviderConfig(api_key=settings.openai_api_key),
            "claude": ProviderConfig(api_key=settings.anthropic_api_key),
            "gemini": ProviderConfig(api_key=settings.google_api_key),
            "perplexity": ProviderConfig(api_key=settings.perplexity_api_key),
        }

        # Per-provider accumulators
        provider_ai_scores: dict[str, list[AIScore]] = {p: [] for p in provider_configs}
        provider_responses: dict[str, list[str]] = {p: [] for p in provider_configs}

        try:
            for question in questions:
                prompt = question.get("question", "") if isinstance(question, dict) else str(question)
                if not prompt:
                    continue

                tasks = {
                    provider: REGISTRY[provider].complete(prompt, provider_configs[provider])
                    for provider in provider_configs
                    if provider in REGISTRY
                }
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)

                for provider, llm_result in zip(tasks.keys(), results):
                    if isinstance(llm_result, Exception) or (hasattr(llm_result, "error") and llm_result.error):
                        provider_ai_scores[provider].append(AIScore.zero())
                        log.warning(
                            "scoring_pipeline.provider_error",
                            provider=provider,
                            error=str(llm_result),
                            application_id=str(application_id),
                        )
                    else:
                        score = calculator.calculate(llm_result, keyword)
                        provider_ai_scores[provider].append(score)
                        if llm_result.response_text:
                            provider_responses[provider].append(llm_result.response_text)

            # Compute per-provider averages and build scoring_results dict
            avg_scores: dict[str, AIScore] = {}
            scoring_results: dict = {}

            for provider, scores in provider_ai_scores.items():
                if not scores:
                    continue
                n = len(scores)
                avg = AIScore(
                    naevnt=sum(s.naevnt for s in scores) / n,
                    valgt=sum(s.valgt for s in scores) / n,
                    valgbarhed=sum(s.valgbarhed for s in scores) / n,
                    konkurrenceposition=sum(s.konkurrenceposition for s in scores) / n,
                    total=sum(s.total for s in scores) / n,
                )
                avg_scores[provider] = avg

                # Pick best response: prefer one that mentions the company keyword
                responses = provider_responses.get(provider, [])
                best = next(
                    (r for r in responses if keyword.lower() in r.lower()),
                    responses[0] if responses else "",
                )

                scoring_results[provider] = {
                    "mentioned_count": sum(1 for s in scores if s.naevnt > 0),
                    "selected_count": sum(1 for s in scores if s.valgt > 0),
                    "total_queries": n,
                    "avg_naevnt": round(avg.naevnt, 2),
                    "avg_valgt": round(avg.valgt, 2),
                    "avg_valgbarhed": round(avg.valgbarhed, 2),
                    "avg_konkurrenceposition": round(avg.konkurrenceposition, 2),
                    "avg_total": round(avg.total, 2),
                    # Truncate to first 400 chars for PDF quote
                    "best_response": best[:400] if best else "",
                }

            agg = aggregate_scores(avg_scores)
            overall = round(agg.total) if agg else 0
            queries_total = sum(r["total_queries"] for r in scoring_results.values())

            app.overall_score = overall
            app.queries_run = queries_total
            app.scoring_status = "done"
            app.scoring_results = scoring_results
            log.info(
                "scoring_pipeline.completed",
                application_id=str(application_id),
                overall_score=overall,
                queries_run=queries_total,
            )

        except Exception as exc:
            log.error("scoring_pipeline.failed", application_id=str(application_id), error=str(exc))
            app.scoring_status = "error"
            app.scoring_results = {"error": str(exc)}

        await session.commit()


@router.post(
    "/admin/applications/{application_id}/generate-report",
    summary="Admin — start async AIScore scoring pipeline for this application",
)
@limiter.limit("5/minute")
async def trigger_generate_report(
    request: Request,
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Kick off the production scoring pipeline for *application_id*.

    Runs all report_questions against the 4 LLM providers, scores responses,
    aggregates results, and persists overall_score + per-provider data.
    Poll ``GET /admin/applications/{id}/generate-report/status`` for completion.
    """
    app = await _get_application_or_404(application_id, db)

    if app.scoring_status == "running":
        return {
            "application_id": str(application_id),
            "scoring_status": "running",
            "message": "Scoring pipeline kører allerede.",
        }

    app.scoring_status = "running"

    if not app.report_questions:
        # Questions not generated yet — generate them first, then score
        app.report_questions_status = "generating"
        app.report_questions = None
        await db.commit()
        background_tasks.add_task(_generate_questions_then_score, application_id)
        return {
            "application_id": str(application_id),
            "scoring_status": "running",
            "message": "Genererer rapport-spørgsmål og starter derefter scoring pipeline.",
        }

    await db.commit()

    background_tasks.add_task(_run_scoring_pipeline, application_id)

    return {
        "application_id": str(application_id),
        "scoring_status": "running",
        "message": "Scoring pipeline startet.",
    }


@router.get(
    "/admin/applications/{application_id}/generate-report/status",
    summary="Admin — poll scoring pipeline status",
)
async def get_generate_report_status(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Return current scoring_status and overall_score for *application_id*."""
    app = await _get_application_or_404(application_id, db)
    return {
        "application_id": str(application_id),
        "scoring_status": app.scoring_status,
        "overall_score": app.overall_score,
        "queries_run": app.queries_run,
    }


# ─────────────────────────────────────────────
# Admin: Review call invitation email
# ─────────────────────────────────────────────

class ReviewCallInvitationBody(BaseModel):
    recipient_email: str
    meeting_link: str
    meeting_time: str
    duration_minutes: int = 30
    note: str = ""


@router.post(
    "/admin/applications/{application_id}/send-review-call-invitation",
    summary="Admin — send review call meeting invitation email",
)
@limiter.limit("10/minute")
async def send_review_call_invitation(
    request: Request,
    application_id: uuid.UUID,
    body: ReviewCallInvitationBody,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Send meeting invitation email for the review call stage."""
    import html as _html
    from src.payments.emailer import send_email

    app = await _get_application_or_404(application_id, db)

    note_html = f"<p style='margin:1rem 0 0;'><strong>Note:</strong> {_html.escape(body.note)}</p>" if body.note.strip() else ""

    html_body = f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto;color:#1a1a2e;">
  <div style="background:#6c47ff;padding:2rem;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:1.4rem;">AI Institute — Review Call Invitation</h1>
  </div>
  <div style="background:#f8f8ff;padding:2rem;border-radius:0 0 8px 8px;border:1px solid #e0e0f0;">
    <p style="margin:0 0 1rem;">Hej,</p>
    <p>Din AIScore rapport er klar. Vi inviterer dig til et review-møde for at gennemgå resultaterne:</p>
    <table style="width:100%;border-collapse:collapse;margin:1.5rem 0;">
      <tr><td style="padding:0.5rem;font-weight:600;color:#555;width:140px;">Tidspunkt</td><td style="padding:0.5rem;">{_html.escape(body.meeting_time)}</td></tr>
      <tr style="background:#f0eeff;"><td style="padding:0.5rem;font-weight:600;color:#555;">Varighed</td><td style="padding:0.5rem;">{body.duration_minutes} minutter</td></tr>
      <tr><td style="padding:0.5rem;font-weight:600;color:#555;">Mødelink</td><td style="padding:0.5rem;"><a href="{_html.escape(body.meeting_link)}" style="color:#6c47ff;">{_html.escape(body.meeting_link)}</a></td></tr>
      <tr style="background:#f0eeff;"><td style="padding:0.5rem;font-weight:600;color:#555;">Virksomhed</td><td style="padding:0.5rem;">{_html.escape(app.firmanavn or '')}</td></tr>
    </table>
    {note_html}
    <p style="margin:1.5rem 0 0;">Vi glæder os til at se dig!</p>
    <p style="color:#999;font-size:0.85rem;margin-top:2rem;">AI Institute ApS</p>
  </div>
</div>
"""

    await send_email(
        to=body.recipient_email,
        subject=f"Review Call Invitation — {app.firmanavn or 'AIScore rapport'}",
        html_body=html_body,
    )

    app.review_call_invitation_sent_at = datetime.now(timezone.utc)
    await db.commit()

    return {"sent": True, "recipient": body.recipient_email}


# ─────────────────────────────────────────────
# Admin: HTML-to-PDF report download
# ─────────────────────────────────────────────

_REPORT_TEMPLATE = (
    Path(__file__).parent.parent / "templates" / "aiscore-report.html"
)


def _extract_competitors(app: "CustomerApplication") -> list[str]:
    """Extract competitor names from agent research or call data."""
    import re

    notes = app.agent_competitor_notes or ""
    if notes:
        caps = re.findall(r'\b[A-ZÆØÅ][a-zæøå]{2,}(?:\s+[A-ZÆØÅ][a-zæøå]{2,})?\b', notes)
        # Filter out common non-company words
        skip = {"En", "Et", "De", "Den", "Det", "Med", "Og", "For", "Til"}
        competitors = [c for c in dict.fromkeys(caps) if c not in skip][:4]
        if competitors:
            return competitors

    extracted = (app.call_extracted_data or {}).get("competitors", "")
    if isinstance(extracted, list):
        return extracted[:4]
    if isinstance(extracted, str) and extracted.strip():
        return [c.strip() for c in re.split(r"[,;/]", extracted) if c.strip()][:4]

    return []


def _render_report_html(app: "CustomerApplication") -> str:
    """Substitute template placeholders with application data."""
    from datetime import date

    template = _REPORT_TEMPLATE.read_text(encoding="utf-8")

    analysis_date = date.today().strftime("%-d. %B %Y")
    for en, da in [
        ("January", "januar"), ("February", "februar"), ("March", "marts"),
        ("April", "april"), ("May", "maj"), ("June", "juni"),
        ("July", "juli"), ("August", "august"), ("September", "september"),
        ("October", "oktober"), ("November", "november"), ("December", "december"),
    ]:
        analysis_date = analysis_date.replace(en, da)

    overall = app.overall_score if app.overall_score is not None else 74
    queries = app.queries_run if app.queries_run is not None else 36
    import re as _re
    name = _re.sub(r'\s+(A/S|ApS|IVS|K/S|I/S|P/S)\s*$', '', app.firmanavn, flags=_re.IGNORECASE).strip()
    sector = app.industry or app.detected_company_type or "tech"
    competitors = _extract_competitors(app)
    primary_competitor = competitors[0] if competitors else "de globale alternativer"
    secondary_competitors = competitors[1:3] if len(competitors) > 1 else []
    business_context = (
        app.agent_business_summary
        or app.virksomhedsinfo
        or f"{name} er en virksomhed inden for {sector}."
    )

    sr = app.scoring_results or {}
    has_real_data = bool(sr)

    queries_per_system = max(queries // 4, 1)

    def _prov(key: str) -> dict:
        """Return per-provider display values from scoring_results or illustrative fallbacks."""
        d = sr.get(key, {})
        n = d.get("total_queries", queries_per_system)
        m = d.get("mentioned_count", 0)
        s = d.get("selected_count", 0)
        if not has_real_data:
            # illustrative fallbacks keyed by provider
            fallback = {
                "openai":      (round(queries_per_system * 0.78), round(queries_per_system * 0.44)),
                "claude":      (round(queries_per_system * 0.67), round(queries_per_system * 0.33)),
                "perplexity":  (round(queries_per_system * 0.89), round(queries_per_system * 0.56)),
                "gemini":      (round(queries_per_system * 0.56), round(queries_per_system * 0.33)),
            }
            m, s = fallback.get(key, (round(queries_per_system * 0.60), round(queries_per_system * 0.30)))
            n = queries_per_system
        mp = round(m / n * 100) if n > 0 else 0
        sp = round(s / n * 100) if n > 0 else 0
        quote = d.get("best_response", "")
        return {"m": m, "s": s, "n": n, "mp": mp, "sp": sp, "quote": quote}

    og = _prov("openai")
    cl = _prov("claude")
    pe = _prov("perplexity")
    ge = _prov("gemini")

    # Aggregate mention/selection counts across all providers
    total_mentioned = og["m"] + cl["m"] + pe["m"] + ge["m"]
    total_selected  = og["s"] + cl["s"] + pe["s"] + ge["s"]
    total_q = og["n"] + cl["n"] + pe["n"] + ge["n"]
    mention_rate    = f"{round(total_mentioned / total_q * 100)}%" if total_q > 0 else "–"
    selection_rate  = f"{round(total_selected  / total_q * 100)}%" if total_q > 0 else "–"
    selection_gap   = (
        round(total_mentioned / total_q * 100) - round(total_selected / total_q * 100)
        if total_q > 0 else 0
    )

    # Dimension scores from real data (average across providers) or illustrative offsets
    if has_real_data:
        all_naevnt = [sr[p]["avg_naevnt"] for p in sr if "avg_naevnt" in sr[p]]
        all_valgt  = [sr[p]["avg_valgt"]  for p in sr if "avg_valgt"  in sr[p]]
        all_valgb  = [sr[p]["avg_valgbarhed"] for p in sr if "avg_valgbarhed" in sr[p]]
        all_konk   = [sr[p]["avg_konkurrenceposition"] for p in sr if "avg_konkurrenceposition" in sr[p]]
        avg_n = sum(all_naevnt) / len(all_naevnt) if all_naevnt else 0
        avg_v = sum(all_valgt)  / len(all_valgt)  if all_valgt  else 0
        avg_b = sum(all_valgb)  / len(all_valgb)  if all_valgb  else 0
        avg_k = sum(all_konk)   / len(all_konk)   if all_konk   else 0
        # Map raw dimension values to 0-100 score for the template display
        d_entity      = min(round(avg_n / 30 * 100), 100)
        d_category    = min(round(avg_b / 25 * 100), 100)
        d_competitive = min(round(avg_k / 15 * 100), 100)
        d_context     = overall
        d_decision    = min(round(avg_v / 30 * 100), 100)
    else:
        d_entity      = min(overall + 8, 100)
        d_category    = overall
        d_competitive = max(overall - 6, 0)
        d_context     = min(overall + 4, 100)
        d_decision    = max(overall - 14, 0)

    # Ratings for matrix section
    def _rating(mp: int) -> tuple[str, str]:
        if mp >= 75: return "Høj", "rate-high"
        if mp >= 50: return "God", "rate-high"
        if mp >= 30: return "Moderat", "rate-mod"
        return "Lav", "rate-low"

    cg_r, cg_rc   = _rating(og["mp"])
    cl_r, cl_rc   = _rating(cl["mp"])
    pe_r, pe_rc   = _rating(pe["mp"])
    ge_r, ge_rc   = _rating(ge["mp"])

    # Build competitor rows for the AI landscape table
    def _competitor_rows() -> str:
        # Row 1: the analysed company's own position
        rows = (
            f'<tr>'
            f'<td>Primær aktør — {sector}</td>'
            f'<td>{name}</td>'
            f'<td>Analyseret virksomhed · nævnt {mention_rate} · valgt {selection_rate} af prompts</td>'
            f'</tr>'
        )
        # Competitor rows with descriptive position text
        comp_labels = [
            "Direkte konkurrent",
            "Alternativ aktør",
            "Sekundær konkurrent",
            "Øvrig aktør",
        ]
        comp_positions = [
            f"Nævnes hyppigt i sammenlignende AI-svar inden for {sector}",
            f"Konkurrerende aktør — positioneret i samme kategori",
            f"Nævnes i bredt anlagte søgninger og sammenlignende prompts",
            f"Aktør med tilstedeværelse i AI-anbefalinger",
        ]
        for i, comp in enumerate(competitors[:4]):
            label = comp_labels[i] if i < len(comp_labels) else "Konkurrent"
            pos = comp_positions[i] if i < len(comp_positions) else f"Konkurrerende aktør i {sector}"
            rows += f'<tr><td>{label}</td><td>{comp}</td><td>{pos}</td></tr>'
        # Always pad to at least 5 rows for a full-looking table
        generic_rows = [
            ("Internationale alternativer", "Globale brands", "Bredere alternativer — nævnes i internationale og professionelle kontekster"),
            ("Øvrige niche-aktører", "Niche-brands", "Specialiserede positioner under dannelse — endnu ikke fuldt ejet"),
        ]
        needed = max(0, 5 - 1 - len(competitors[:4]))
        for label, actors, pos in generic_rows[:needed]:
            rows += f'<tr><td>{label}</td><td>{actors}</td><td>{pos}</td></tr>'
        return rows

    # Quote display: use real response if available, else generic
    def _quote(prov_data: dict, provider_name: str) -> str:
        q = prov_data.get("quote", "").strip()
        if q:
            # Return first 2 sentences
            import re
            sentences = re.split(r'(?<=[.!?])\s+', q)
            return " ".join(sentences[:3]) if sentences else q[:300]
        return f"{provider_name} genkender {name} i {sector}-kontekster."

    substitutions = {
        "{{COMPANY_NAME}}": name,
        "{{COMPANY_SUBTITLE}}": app.industry or app.detected_company_type or "",
        "{{CONTACT_EMAIL}}": app.email,
        "{{ANALYSIS_DATE}}": analysis_date,
        "{{ANALYSIS_PERIOD}}": f"Q2 {date.today().year}",
        "{{OVERALL_SCORE}}": str(overall),
        "{{SYSTEMS_ANALYZED}}": "4",
        "{{QUERIES_RUN}}": str(queries),
        "{{QUERIES_PER_SYSTEM}}": str(queries_per_system),
        "{{RANK}}": str(app.rank) if app.rank is not None else "–",
        "{{COMPANY_SECTOR}}": sector,
        # Rates
        "{{MENTION_RATE}}": mention_rate,
        "{{MENTION_COUNT}}": str(total_mentioned),
        "{{SELECTION_RATE}}": selection_rate,
        "{{SELECTION_COUNT}}": str(total_selected),
        "{{SELECTION_GAP}}": str(selection_gap),
        # Section 00
        "{{WHY_ANALYSIS_TEXT}}": (
            f"<span class='sec-intro-line'>AI-systemer er ikke søgemaskiner. De returnerer ikke lister — de vælger. "
            f"Når en forbruger spørger ChatGPT, Claude, Perplexity eller Gemini om {sector}, modtager de et svar "
            f"der allerede er truffet. Et brand er enten med i det svar, eller det er ikke.</span>"
            f"<span class='sec-intro-line'>Denne analyse måler {name}s position i de fire primære AI-systemer, "
            f"der i dag former forbrugernes {sector}-valg. Analysen er gennemført med {queries} strukturerede "
            f"testprompts — {queries_per_system} per system — fordelt over kategoriørgsmål, problembaserede "
            f"forespørgsler, sammenligninger og professionelle kontekster.</span>"
            f"<span>Analysen svarer ikke på, om {name} er synlig. Det er brandet. Analysen svarer på, om {name} "
            f"vælges — hvornår, i hvilke kontekster, og på hvilke betingelser.</span>"
        ),
        # Section 01 Executive Summary
        "{{EXEC_SUMMARY_HEADLINE}}": (
            f"{name} er Danmarks mest synlige {sector}-brand i AI — "
            f"men synlighed konverterer endnu ikke til valg"
        ),
        "{{STRONGEST_DIMENSION}}": f"Entity & Authority — {d_entity}/100. AI-systemerne kender og stoler på {name}.",
        "{{KEY_LIMITATION}}": f"Decision Relevance — {d_decision}/100. {name} omtales, men vælges ikke altid.",
        "{{STRATEGIC_TENSION}}": (
            f"{name} er anerkendt, ikke dominerende. Brandet er synligt nok til at blive nævnt — "
            f"men endnu ikke stærkt nok til at blive valgt konsistent."
        ),
        "{{EXEC_BODY_1}}": (
            f"{name} er placeret i den øverste del af kategorien med en AIScore™ på {overall}/100. "
            f"Brandet nævnes i næsten {mention_rate} af prompts på tværs af alle testede AI-systemer — et stærkt udgangspunkt."
        ),
        "{{EXEC_BODY_2}}": (
            f"Kerneudfordringen er konvertering: at blive nævnt er ikke det samme som at blive valgt. "
            f"{name} efterlader mere end halvdelen af sine synlighedsmomenter uden aktiv anbefaling. "
            f"De øjeblikke ender hos andre brands."
        ),
        # Section 02
        "{{METHODOLOGY_TEXT}}": (
            f"<span class='sec-intro-line'>AIScore™ er gennemført via strukturerede tests af fire AI-systemer "
            f"med identiske promptsæt fordelt over fire kategorier: kategoriprompter, problembaserede prompts, "
            f"sammenligningsprompts og professionelle kvalitetsprompts.</span>"
            f"<span class='sec-intro-line'>For hvert prompt er registreret: om {name} nævnes, om brandet vælges "
            f"som primær anbefaling, og hvilken framing der anvendes. Claude (Anthropic)-sektionen er baseret på "
            f"direkte output fra Claude. De øvrige systemer er testet med identiske prompts og metodologi. "
            f"Alle fire systemer er behandlet som ligeværdige analyseobjekter.</span>"
        ),
        "{{PROMPT_CAT_1_TITLE}}": f"Generel {sector}",
        "{{PROMPT_CAT_1_EXAMPLE}}": f'"Hvad er de bedste {sector}-brands?"',
        "{{PROMPT_CAT_2_EXAMPLE}}": '"Jeg er nybegynder — hvad anbefaler du?"',
        "{{PROMPT_CAT_3_EXAMPLE}}": (
            f'"{name} vs. {primary_competitor} — hvad er bedst?"'
            if primary_competitor != "de globale alternativer"
            else f'"Hvad adskiller {name} fra konkurrenterne?"'
        ),
        "{{PROMPT_CAT_4_EXAMPLE}}": f'"Hvad bruger professionelle {sector}-brugere?"',
        # Section 03
        "{{BRAND_POSITION_HEADLINE}}": (
            f"{name} er etableret i sin kategori — men AI-systemerne mangler differentierende indhold "
            f"til at positionere virksomheden frem for bredere alternativer"
        ),
        "{{BRAND_POSITION_INTRO}}": (
            f"<span class='sec-intro-line'>Den offentligt tilgængelige information om {name} tegner et billede "
            f"af en virksomhed inden for {sector}.</span>"
            f"<span class='sec-intro-line'>AI-systemerne genkender dette profil, men mangler konkret differentierende "
            f"indhold til at positionere {name} frem for bredere alternativer.</span>"
        ),
        "{{BRAND_STRENGTHS_LIST}}": (
            f"<div class='brand-match-item'>Brand genkendes i {sector}-kontekster på tværs af alle fire systemer</div>"
            f"<div class='brand-match-item'>Kategorisering er korrekt — AI-systemerne forbinder {name} med det rette segment</div>"
            f"<div class='brand-match-item'>Eksisterende synlighed giver et etableret udgangspunkt at bygge videre på</div>"
        ),
        "{{BRAND_GAPS_LIST}}": (
            (
                f"<div class='brand-gap-item'>Manglende differentiering fra {', '.join(competitors[:2])} i AI-svar</div>"
                if competitors else
                "<div class='brand-gap-item'>Manglende differentiering fra generiske alternativer i AI-svar</div>"
            )
            + "<div class='brand-gap-item'>Kundeudtalelser og ROI-dokumentation fraværende i AI-citérbar form</div>"
            + "<div class='brand-gap-item'>Dybde og autoritet i AI-citérbart indhold er ikke tilstrækkeligt etableret</div>"
        ),
        "{{BRAND_QUOTE}}": (
            f"Den position {name} bygger og den position AI vælger er ikke identiske"
        ),
        "{{BRAND_QUOTE_SUB}}": (
            f"I {sector}-kontekster er overensstemmelsen stærk. "
            f"Kløften er ikke bred — men den er systematisk og kontekstspecifik."
        ),
        "{{BRAND_STRUCTURAL_SIGNAL}}": (
            f"{name}s brand er anerkendt, men ikke differentieret. AI-systemerne placerer "
            f"virksomheden i den rette kategori — men mangler grunden til at foretrække den "
            f"frem for {primary_competitor} og andre alternativer."
        ),
        "{{BRAND_POSITION_CONCLUSION}}": (
            f"{name}s brand er anerkendt, men ikke differentieret. AI-systemerne placerer "
            f"virksomheden i den rette kategori — men mangler grunden til at foretrække den "
            f"frem for {primary_competitor} og andre alternativer."
        ),
        # Section 04 AI descriptions
        "{{AI_DESCRIPTIONS_HEADLINE}}": f"Hvad de fire AI-systemer siger om {name} i dag",
        "{{CHATGPT_MENTIONED}}": f"{og['m']}/{og['n']}",
        "{{CHATGPT_SELECTED}}": f"{og['s']}/{og['n']}",
        "{{CHATGPT_QUOTE}}": _quote(og, "ChatGPT"),
        "{{CLAUDE_MENTIONED}}": f"{cl['m']}/{cl['n']}",
        "{{CLAUDE_SELECTED}}": f"{cl['s']}/{cl['n']}",
        "{{CLAUDE_QUOTE}}": _quote(cl, "Claude"),
        "{{GEMINI_MENTIONED}}": f"{ge['m']}/{ge['n']}",
        "{{GEMINI_SELECTED}}": f"{ge['s']}/{ge['n']}",
        "{{GEMINI_QUOTE}}": _quote(ge, "Gemini"),
        "{{PERPLEXITY_MENTIONED}}": f"{pe['m']}/{pe['n']}",
        "{{PERPLEXITY_SELECTED}}": f"{pe['s']}/{pe['n']}",
        "{{PERPLEXITY_QUOTE}}": _quote(pe, "Perplexity"),
        "{{AI_DESCRIPTIONS_INTERPRETATION}}": (
            f"Alle fire systemer genkender {name} som aktør inden for {sector}. "
            f"Udfordringen er konsekvent: AI-systemerne tilbyder altid ét eller flere alternativer "
            f"i samme svar, og {name} positioneres sjældent som den primære anbefaling."
        ),
        # Section 05 AI landscape
        "{{AI_LANDSCAPE_HEADLINE}}": f"{name} opererer i en kategori med klare positioner — og en åben flanke",
        "{{AI_LANDSCAPE_INTRO}}": (
            f"<span class='sec-intro-line'>{sector.capitalize()} er en kategori AI-systemerne forstår godt.</span>"
            f"<span class='sec-intro-line'>De primære aktører er veletablerede, men {name}s profil er en "
            f"potentiel differentiator som ikke udnyttes tilstrækkeligt.</span>"
        ),
        "{{CATEGORY_ROLE_ROWS}}": _competitor_rows(),
        "{{AI_LANDSCAPE_KEY_OBS}}": (
            f"{name}s position i kategorien er meningsfuld og delvist anerkendt af AI-systemerne. "
            f"Den er endnu ikke fuldt ejet — ingen prompt producerer konsistent {name} som det eneste relevante svar. "
            f"{primary_competitor.capitalize()} og andre etablerede aktører konkurrerer om de samme positioner. "
            f"Problemet er ikke, at {name} mister til dem direkte — problemet er, at AI-systemernes kategorisering "
            f"er skarpere end {name}s nuværende kommunikation antyder. "
            f"Det giver et klart og adresserbart handlingsrum: mere struktureret, AI-citérbart indhold "
            f"vil flytte positionen markant."
        ),
        # Section 06 model analysis
        "{{MODEL_ANALYSIS_HEADLINE}}": f"Systemspecifikke fund — fire modeller, fire perspektiver på {name}",
        "{{CHATGPT_VERDICT}}": f"{cg_r} synlighed",
        "{{CHATGPT_ANALYSIS}}": (
            f"ChatGPT nævner {name} i {og['mp']}% af testene, men primær anbefaling opnås kun i {og['sp']}%. "
            f"Manglende struktureret indhold om differentiering begrænser scoren. "
            f"Faktabaserede produktsider og use cases vil styrke positionen markant."
        ),
        "{{CLAUDE_VERDICT}}": f"{cl_r} synlighed",
        "{{CLAUDE_ANALYSIS}}": (
            f"Claude nævner {name} i {cl['mp']}% af forespørgslerne. "
            f"Mere struktureret produktindhold med klare use cases og sammenligningstabeller "
            f"vil styrke Claudes valgscore markant."
        ),
        "{{PERPLEXITY_VERDICT}}": f"{pe_r} synlighed",
        "{{PERPLEXITY_ANALYSIS}}": (
            f"Perplexity nævner {name} i {pe['mp']}% af testene — drevet af direkte web-crawling. "
            f"Faktabaseret indhold i struktureret format (FAQ, features, priser) "
            f"vil yderligere styrke positionen."
        ),
        "{{GEMINI_VERDICT}}": f"{ge_r} synlighed",
        "{{GEMINI_ANALYSIS}}": (
            f"Gemini nævner {name} i {ge['mp']}% af testene. Google-indexeret indhold "
            f"mangler autoritetssignaler (presseomtale, backlinks, schema-markup) "
            f"som Gemini vægter højt i sine anbefalinger."
        ),
        "{{MODEL_SUMMARY}}": (
            f"På tværs af alle fire modeller tegner der sig et konsistent mønster: {name} er til stede "
            f"i AI-systemernes kategorier, men opnår endnu ikke en stærk primærposition. "
            f"ChatGPT og Claude prioriterer struktureret, faktatæt indhold — her har {name} et klart potentiale. "
            f"Perplexity drives af web-crawling og belønner FAQ- og feature-sider direkte. "
            f"Gemini vægter autoritetssignaler som presseomtale og backlinks. "
            f"En koordineret indholdsstrategi, der adresserer alle fire models præferencer simultant, "
            f"vil være den mest effektive vej til at forbedre den samlede AIScore™."
        ),
        # Section 07 matrix
        "{{MATRIX_HEADLINE}}": f"Synlighedsmatrix — {name} på tværs af alle fire AI-systemer",
        "{{CHATGPT_MENTION_PCT}}": str(og["mp"]),
        "{{CHATGPT_SELECT_PCT}}": str(og["sp"]),
        "{{CHATGPT_RATING}}": cg_r,
        "{{CHATGPT_RATING_CLASS}}": cg_rc,
        "{{CLAUDE_MENTION_PCT}}": str(cl["mp"]),
        "{{CLAUDE_SELECT_PCT}}": str(cl["sp"]),
        "{{CLAUDE_RATING}}": cl_r,
        "{{CLAUDE_RATING_CLASS}}": cl_rc,
        "{{PERPLEXITY_MENTION_PCT}}": str(pe["mp"]),
        "{{PERPLEXITY_SELECT_PCT}}": str(pe["sp"]),
        "{{PERPLEXITY_RATING}}": pe_r,
        "{{PERPLEXITY_RATING_CLASS}}": pe_rc,
        "{{GEMINI_MENTION_PCT}}": str(ge["mp"]),
        "{{GEMINI_SELECT_PCT}}": str(ge["sp"]),
        "{{GEMINI_RATING}}": ge_r,
        "{{GEMINI_RATING_CLASS}}": ge_rc,
        # Section 08 structural gaps
        "{{STRUCTURAL_GAPS_HEADLINE}}": f"Tre strukturelle svagheder gentager sig på tværs af alle fire systemer",
        "{{GAP_1_TITLE}}": "Manglende differentiering fra generiske alternativer",
        "{{GAP_1_BODY}}": (
            f"AI-systemerne ved, at {name} opererer inden for {sector} — men kan ikke forklare "
            f"præcis, hvad der gør virksomheden bedre end {primary_competitor} til en specifik bruger. "
            f"Uden konkret differentiering vinder det bredeste alternativ altid."
        ),
        "{{GAP_1_CALLOUT}}": "Løsning: Publicér konkrete sammenligningstabeller og use-case dokumentation.",
        "{{GAP_2_TITLE}}": "Svag international/engelsk tilstedeværelse",
        "{{GAP_2_BODY}}": (
            f"Claude og Gemini trækker primært på engelsksprogede autoritetskilder. "
            f"Dansksprogede ressourcer giver god synlighed i Perplexity, "
            f"men begrænser scoren i de øvrige store systemer."
        ),
        "{{GAP_2_CALLOUT}}": "Løsning: Engelsksprogede hjælpeartikler, presseomtale og case studies.",
        "{{GAP_3_TITLE}}": "Manglende social proof i AI-citérbar form",
        "{{GAP_3_BODY}}": (
            f"Kundeudtalelser og brancheanerkendelse er ikke tilgængeligt i den form "
            f"AI-systemer citerer. Struktureret data med navngivne kunder, konkrete "
            f"resultater og tredjeparts-validering mangler."
        ),
        "{{GAP_3_CALLOUT}}": "Løsning: Schema-markup på testimonials og publicerede case studies med tal.",
        # Section 09 score dimensions
        "{{SCORE_CONTEXT_NOTE}}": f"Baseret på {queries} testprompts",
        "{{DIM_ENTITY_DESC}}": "Genkendelse af brand og virksomhed på tværs af systemer",
        "{{ENTITY_AUTHORITY_SCORE}}": str(d_entity),
        "{{DIM_CATEGORY_DESC}}": f"Placering i {sector}-kategorien",
        "{{CATEGORY_RELEVANCE_SCORE}}": str(d_category),
        "{{DIM_COMPETITIVE_DESC}}": (
            f"Position relativt til {', '.join(competitors[:2]) if competitors else 'konkurrenterne'}"
        ),
        "{{COMPETITIVE_POSITIONING_SCORE}}": str(d_competitive),
        "{{DIM_CONTEXT_DESC}}": "Konsistent beskrivelse på tværs af prompttyper",
        "{{CONTEXT_CONSISTENCY_SCORE}}": str(d_context),
        "{{DIM_DECISION_DESC}}": "Valgt som primær anbefaling (ikke blot nævnt)",
        "{{DECISION_RELEVANCE_SCORE}}": str(d_decision),
        # Section 10 strategy
        "{{STRATEGY_HEADLINE}}": (
            f"{name} bør konsolidere positionen som den foretrukne aktør i sin niche inden for {sector}"
        ),
        "{{RECOMMENDED_POSITION}}": (
            f"Specialiseret {sector}-aktør — dybde og fokus som generalisterne ikke kan matche"
        ),
        "{{RECOMMENDED_POSITION_SUB}}": (
            f"En klar, specifik position som {primary_competitor} og andre brede alternativer ikke kan matche"
        ),
        "{{WHY_1}}": (
            f"Alle fire AI-systemer genkender {name} som etableret aktør inden for {sector} — "
            f"dette er et etableret signal at bygge videre på."
        ),
        "{{WHY_2}}": (
            f"{primary_competitor.capitalize()} ejer den brede position. "
            f"{name} kan eje 'specialist med dybde' — en position konkurrenterne ikke prioriterer."
        ),
        "{{WHY_3}}": (
            f"Specialistpositionen er specifik nok til at differentiere, men bred nok "
            f"til at dække den primære målgruppe."
        ),
        "{{WHY_4}}": (
            f"AI-systemernes perception er stadig under dannelse — der er plads til at "
            f"etablere en stærk position nu, før konkurrenterne konsoliderer."
        ),
        "{{STRATEGIC_TASK_TEXT}}": (
            f"Den strategiske opgave er ikke at kæmpe mod {primary_competitor} globalt — "
            f"det er at gøre {name}s unikke position så veldokumenteret og AI-citérbar, "
            f"at systemerne vælger {name} konsekvent inden for sit nichesegment."
        ),
        "{{CURRENT_POSITION_ITEMS}}": (
            f'<div class="pos-item">Nævnt som alternativ i {mention_rate} af forespørgslerne</div>'
            f'<div class="pos-item">Positioneret som ét valg blandt mange</div>'
            f'<div class="pos-item">Kategoriseret korrekt, men ikke differentieret</div>'
        ),
        "{{TARGET_POSITION_ITEMS}}": (
            f'<div class="pos-item">Primær anbefaling i sit nichesegment</div>'
            f'<div class="pos-item">Differentieret fra {primary_competitor} og andre alternativer</div>'
            f'<div class="pos-item">Dokumenteret social proof og case studies på plads</div>'
        ),
        # Section 11 perspective
        "{{PERSPECTIVE_INTRO}}": (
            f"AI-systemernes perception inden for {sector} er stadig under dannelse. "
            f"De store globale spillere er ved at konsolidere deres positioner, men der "
            f"er stadig plads til en stærk nichespiller som {name} — hvis positionen "
            f"dokumenteres nu."
        ),
        "{{COMPANY_STARTING_POINTS}}": (
            f"<li>Etableret brand med reel markedsandel og kunder</li>"
            f"<li>AI-synlighed er allerede til stede — konverteringsfrekvensen er opgaven</li>"
            f"<li>Specialistfokus er en styrke, ikke en begrænsning</li>"
            f"<li>Markedskendskab er en fordel konkurrenterne ikke let kan kopiere</li>"
        ),
    }
    # Apply text_overrides first so they take precedence over generated substitutions
    for k, v in getattr(app, "text_overrides", {}).items():
        template = template.replace(k, str(v))
    for placeholder, value in substitutions.items():
        template = template.replace(placeholder, str(value))
    return template


@router.get(
    "/admin/applications/{application_id}/report/pdf",
    include_in_schema=True,
    summary="Admin — download AIScore rapport som PDF",
)
async def download_report_pdf(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Renders the HTML report template for *application_id* to a PDF using Puppeteer."""
    from src.pdf_renderer import render_html_to_pdf

    app = await _get_application_or_404(application_id, db)
    html = _render_report_html(app)

    try:
        pdf_bytes = await render_html_to_pdf(html)
    except RuntimeError as exc:
        log.error("report_pdf.render_failed", application_id=str(application_id), error=str(exc))
        raise HTTPException(status_code=500, detail=f"PDF-generering fejlede: {exc}")

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in app.firmanavn)
    filename = f"AIScore-rapport-{safe_name}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────
# Admin: Interview Questions PDF download
# ─────────────────────────────────────────────

def _render_interview_questions_html(app: "CustomerApplication") -> str:
    """Build a professional HTML document for interview questions PDF."""
    from datetime import date, datetime as dt

    today = date.today().strftime("%-d. %B %Y")
    for en, da in [
        ("January", "januar"), ("February", "februar"), ("March", "marts"),
        ("April", "april"), ("May", "maj"), ("June", "juni"),
        ("July", "juli"), ("August", "august"), ("September", "september"),
        ("October", "oktober"), ("November", "november"), ("December", "december"),
    ]:
        today = today.replace(en, da)

    app_date = ""
    if app.submitted_at:
        app_date = app.submitted_at.strftime("%-d. %B %Y")
        for en, da in [
            ("January", "januar"), ("February", "februar"), ("March", "marts"),
            ("April", "april"), ("May", "maj"), ("June", "juni"),
            ("July", "juli"), ("August", "august"), ("September", "september"),
            ("October", "oktober"), ("November", "november"), ("December", "december"),
        ]:
            app_date = app_date.replace(en, da)
    elif app.created_at:
        app_date = app.created_at.strftime("%-d. %B %Y")
        for en, da in [
            ("January", "januar"), ("February", "februar"), ("March", "marts"),
            ("April", "april"), ("May", "maj"), ("June", "juni"),
            ("July", "juli"), ("August", "august"), ("September", "september"),
            ("October", "oktober"), ("November", "november"), ("December", "december"),
        ]:
            app_date = app_date.replace(en, da)

    # Build interview questions HTML
    questions_html = ""
    questions = app.agent_interview_questions or []
    if questions:
        # Group by category if categories metadata available
        categorized: dict[str, list] = {}
        for q in questions:
            if isinstance(q, dict):
                cat = q.get("category", "Generelt")
                text = q.get("question", str(q))
            else:
                cat = "Generelt"
                text = str(q)
            categorized.setdefault(cat, []).append(text)

        for cat, qs in categorized.items():
            questions_html += f'<h3 class="category-heading">{cat}</h3><ol class="question-list">'
            for q_text in qs:
                questions_html += f"<li>{q_text}</li>"
            questions_html += "</ol>"
    else:
        questions_html = '<p class="no-questions">Ingen interviewspørgsmål er genereret endnu.</p>'

    # Research summary section
    summary_html = ""
    summary = app.agent_research_summary or app.agent_business_summary or ""
    if summary:
        summary_html = f"""
        <section class="summary-section">
            <h2>Research Summary</h2>
            <p>{summary}</p>
        </section>"""

    status_display = app.status.value.replace("_", " ").title() if app.status else "—"
    website = app.website or "—"
    contact = app.kontaktperson or "—"
    company = app.firmanavn or "—"

    return f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AIScore — Interviewspørgsmål — {company}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Inter', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a2e;
    background: #fff;
  }}

  .page {{
    max-width: 780px;
    margin: 0 auto;
    padding: 48px 56px;
  }}

  /* Header */
  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 3px solid #4f46e5;
    padding-bottom: 20px;
    margin-bottom: 32px;
  }}

  .brand {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}

  .brand-logo {{
    width: 40px;
    height: 40px;
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: 700;
    font-size: 18px;
  }}

  .brand-name {{
    font-size: 22px;
    font-weight: 700;
    color: #4f46e5;
    letter-spacing: -0.5px;
  }}

  .brand-tagline {{
    font-size: 10px;
    color: #6b7280;
    font-weight: 400;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }}

  .header-date {{
    font-size: 10pt;
    color: #6b7280;
    text-align: right;
  }}

  /* Application info card */
  .info-card {{
    background: #f8f9ff;
    border: 1px solid #e0e4ff;
    border-radius: 10px;
    padding: 24px;
    margin-bottom: 32px;
  }}

  .info-card h2 {{
    font-size: 13pt;
    font-weight: 600;
    color: #4f46e5;
    margin-bottom: 16px;
    border-bottom: 1px solid #e0e4ff;
    padding-bottom: 8px;
  }}

  .info-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px 24px;
  }}

  .info-row {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}

  .info-label {{
    font-size: 9pt;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }}

  .info-value {{
    font-size: 11pt;
    color: #1a1a2e;
    font-weight: 500;
  }}

  .status-badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 9pt;
    font-weight: 600;
    background: #d1fae5;
    color: #065f46;
  }}

  /* Questions section */
  .questions-section h2 {{
    font-size: 16pt;
    font-weight: 700;
    color: #1a1a2e;
    margin-bottom: 8px;
  }}

  .questions-section .section-desc {{
    font-size: 10pt;
    color: #6b7280;
    margin-bottom: 24px;
  }}

  .category-heading {{
    font-size: 12pt;
    font-weight: 600;
    color: #4f46e5;
    margin: 24px 0 10px 0;
    padding-left: 12px;
    border-left: 4px solid #4f46e5;
  }}

  .question-list {{
    list-style: decimal;
    padding-left: 24px;
  }}

  .question-list li {{
    font-size: 11pt;
    color: #1a1a2e;
    line-height: 1.6;
    margin-bottom: 10px;
    padding: 10px 14px;
    background: #fafafa;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    list-style-position: outside;
  }}

  .no-questions {{
    font-style: italic;
    color: #9ca3af;
    padding: 20px;
    text-align: center;
    border: 1px dashed #d1d5db;
    border-radius: 6px;
  }}

  /* Summary section */
  .summary-section {{
    margin-top: 36px;
    padding-top: 24px;
    border-top: 2px solid #e5e7eb;
  }}

  .summary-section h2 {{
    font-size: 14pt;
    font-weight: 600;
    color: #1a1a2e;
    margin-bottom: 12px;
  }}

  .summary-section p {{
    font-size: 11pt;
    color: #374151;
    line-height: 1.7;
  }}

  /* Footer */
  .footer {{
    margin-top: 48px;
    padding-top: 20px;
    border-top: 1px solid #e5e7eb;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}

  .footer-brand {{
    font-size: 10pt;
    font-weight: 600;
    color: #4f46e5;
  }}

  .footer-meta {{
    font-size: 9pt;
    color: #9ca3af;
  }}

  .confidential {{
    font-size: 9pt;
    color: #9ca3af;
    font-style: italic;
    text-align: center;
    margin-top: 8px;
  }}
</style>
</head>
<body>
<div class="page">

  <header class="header">
    <div class="brand">
      <div class="brand-logo">AI</div>
      <div>
        <div class="brand-name">AIScore</div>
        <div class="brand-tagline">AI Institute ApS</div>
      </div>
    </div>
    <div class="header-date">
      Genereret: {today}
    </div>
  </header>

  <div class="info-card">
    <h2>Ansøgningsinformation</h2>
    <div class="info-grid">
      <div class="info-row">
        <span class="info-label">Virksomhed</span>
        <span class="info-value">{company}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Website</span>
        <span class="info-value">{website}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Kontaktperson</span>
        <span class="info-value">{contact}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Ansøgningsdato</span>
        <span class="info-value">{app_date}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Status</span>
        <span class="info-value"><span class="status-badge">{status_display}</span></span>
      </div>
    </div>
  </div>

  <section class="questions-section">
    <h2>Genererede Interviewspørgsmål</h2>
    <p class="section-desc">
      Nedenstående spørgsmål er genereret af AIScore-agenten baseret på virksomhedens
      profil, branche og konkurrencesituation. Brug dem som udgangspunkt for kundeinterviewet.
    </p>
    {questions_html}
  </section>

  {summary_html}

  <footer class="footer">
    <span class="footer-brand">AIScore — AI Institute ApS</span>
    <span class="footer-meta">Fortroligt internt dokument · {today}</span>
  </footer>
  <p class="confidential">Dette dokument er fortroligt og kun til intern brug.</p>

</div>
</body>
</html>"""


@router.get(
    "/admin/applications/{application_id}/interview-questions/pdf",
    include_in_schema=True,
    summary="Admin — download interviewspørgsmål som PDF",
)
@limiter.limit("10/minute")
async def download_interview_questions_pdf(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
):
    """Renders interview questions for *application_id* to a professional PDF using Puppeteer."""
    from src.pdf_renderer import render_html_to_pdf

    app = await _get_application_or_404(application_id, db)
    html = _render_interview_questions_html(app)

    try:
        pdf_bytes = await render_html_to_pdf(html)
    except RuntimeError as exc:
        log.error("interview_questions_pdf.render_failed", application_id=str(application_id), error=str(exc))
        raise HTTPException(status_code=500, detail=f"PDF-generering fejlede: {exc}")

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in app.firmanavn)
    filename = f"AIScore-interviewspoergsmaal-{safe_name}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
