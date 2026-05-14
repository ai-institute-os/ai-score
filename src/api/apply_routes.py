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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db import get_db
from src.db.models import (
    CustomerApplication, CustomerApplicationStateLog, CustomerApplicationStatus, VALID_TRANSITIONS,
    AISelectSubscription, SubscriptionTier, SubscriptionStatus,
    PasswordResetToken,
)
from src.api.schemas import (
    ApplicationCreate, ApplicationCreatePublic, ApplicationRejectRequest,
    ApplicationResponse, ApplicationStatusUpdate,
    GeneratePaymentLinkRequest, PaymentLinkResponse,
    QCResultSubmit, ManualCorrectionRequest, ScoringDataUpdate,
    ForgotPasswordRequest, ResetPasswordRequest, PasswordResetResponse,
)
from src.api.auth import require_admin_key
from src.api.rate_limit import limiter

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


@router.post("/applications", response_model=ApplicationResponse, status_code=201)
@limiter.limit("5/minute")
async def submit_application_public(
    request: Request,
    body: ApplicationCreatePublic,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — new application flow with English field names.

    Creates the application as APPLIED, immediately transitions to UNDER_REVIEW,
    and sends an admin notification email via Resend.
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

    # Immediately move to UNDER_REVIEW
    app.status = CustomerApplicationStatus.UNDER_REVIEW
    app.updated_at = now
    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=CustomerApplicationStatus.APPLIED,
        to_status=CustomerApplicationStatus.UNDER_REVIEW,
        changed_by="system",
        note="Auto-transitioned to UNDER_REVIEW on submission",
    ))

    await db.commit()
    await db.refresh(app)

    settings = get_settings()
    admin_review_email = getattr(settings, "admin_review_email", "amministrazionemfce@gmail.com")
    app_base_url = getattr(settings, "app_base_url", "https://app.aiscore.dk")
    background_tasks.add_task(_send_admin_review_email, app, app_base_url, admin_review_email)

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


# ─────────────────────────────────────────────
# Admin: list and manage applications
# ─────────────────────────────────────────────

@router.get("/admin/applications", response_model=list[ApplicationResponse], dependencies=[Depends(require_admin_key)])
@limiter.limit("30/minute")
async def list_applications(
    request: Request,
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """Admin — list all customer applications, optionally filtered by status."""
    q = select(CustomerApplication).options(selectinload(CustomerApplication.state_logs))
    if status:
        try:
            status_enum = CustomerApplicationStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status}")
        q = q.where(CustomerApplication.status == status_enum)
    q = q.order_by(CustomerApplication.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/admin/orders", dependencies=[Depends(require_admin_key)])
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


@router.get("/admin/applications/{application_id}", response_model=ApplicationResponse, dependencies=[Depends(require_admin_key)])
@limiter.limit("30/minute")
async def get_application(request: Request, application_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Admin — get a single application with full state log."""
    app = await _get_application_or_404(application_id, db)
    return app


@router.post(
    "/admin/applications/{application_id}/approve",
    response_model=ApplicationResponse,
    dependencies=[Depends(require_admin_key)],
)
@limiter.limit("30/minute")
async def approve_application(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin_id: str = Depends(require_admin_key),
):
    """Admin — approve an application in UNDER_REVIEW → APPROVED."""
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
    app.approved_by = admin_id
    app.updated_at = now
    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.APPROVED,
        changed_by=admin_id,
        note="Application approved",
    ))
    await db.commit()

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


@router.post(
    "/admin/applications/{application_id}/reject",
    response_model=ApplicationResponse,
    dependencies=[Depends(require_admin_key)],
)
@limiter.limit("30/minute")
async def reject_application(
    request: Request,
    application_id: uuid.UUID,
    body: ApplicationRejectRequest = ApplicationRejectRequest(),
    db: AsyncSession = Depends(get_db),
    admin_id: str = Depends(require_admin_key),
):
    """Admin — reject an application (APPLIED or UNDER_REVIEW → REJECTED)."""
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
    app.rejected_by = admin_id
    app.rejection_reason = body.rejection_reason
    app.updated_at = now
    db.add(CustomerApplicationStateLog(
        application_id=app.id,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.REJECTED,
        changed_by=admin_id,
        note=body.rejection_reason or "Application rejected",
    ))
    await db.commit()

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
    db: AsyncSession = Depends(get_db),
    admin_id: str = Depends(require_admin_key),
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
    app.status = new_status
    app.updated_at = datetime.now(timezone.utc)

    log = CustomerApplicationStateLog(
        application_id=app.id,
        from_status=prev_status,
        to_status=new_status,
        changed_by=admin_id,
        note=body.note,
    )
    db.add(log)
    await db.commit()

    if new_status == CustomerApplicationStatus.READY_FOR_REVIEW_CALL:
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


@router.patch("/admin/applications/{application_id}/notes", response_model=ApplicationResponse, dependencies=[Depends(require_admin_key)])
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
    dependencies=[Depends(require_admin_key)],
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
    dependencies=[Depends(require_admin_key)],
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
    dependencies=[Depends(require_admin_key)],
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
    dependencies=[Depends(require_admin_key)],
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
    dependencies=[Depends(require_admin_key)],
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
    dependencies=[Depends(require_admin_key)],
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
    dependencies=[Depends(require_admin_key)],
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
    dependencies=[Depends(require_admin_key)],
)
@limiter.limit("30/minute")
async def generate_payment_link(
    request: Request,
    application_id: uuid.UUID,
    body: GeneratePaymentLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin — generate a Stripe checkout link for a customer and (optionally) email it to them.
    Transitions the application to AWAITING_PAYMENT.
    """
    from src.payments import create_checkout_session, send_payment_link_email

    app = await _get_application_or_404(application_id, db)

    allowed_from = {
        CustomerApplicationStatus.CALLED,
        CustomerApplicationStatus.APPROVED,
    }
    if app.status not in allowed_from:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Payment link can only be generated from CALLED or APPROVED status. "
                f"Current status: {app.status.value}"
            ),
        )

    session = await create_checkout_session(
        customer_email=app.email,
        customer_name=app.kontaktperson,
        amount_dkk=body.amount_dkk,
        application_id=application_id,
    )

    prev_status = app.status
    app.stripe_session_id = session.id
    app.payment_url = session.url
    app.status = CustomerApplicationStatus.AWAITING_PAYMENT
    app.updated_at = datetime.now(timezone.utc)
    await _add_state_log(
        db, app,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.AWAITING_PAYMENT,
        changed_by="system",
        note=f"Payment link generated — {body.amount_dkk} DKK — session {session.id}",
    )
    await db.commit()

    email_sent = False
    if body.send_email:
        try:
            await send_payment_link_email(
                customer_email=app.email,
                customer_name=app.kontaktperson,
                company_name=app.firmanavn,
                payment_url=session.url,
                amount_dkk=body.amount_dkk,
            )
            email_sent = True
        except Exception as exc:
            log.error("payment_link.email_failed", application_id=str(application_id), error=str(exc))

    return PaymentLinkResponse(
        application_id=application_id,
        payment_url=session.url,
        stripe_session_id=session.id,
        amount_dkk=body.amount_dkk,
        email_sent=email_sent,
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


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
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
                app.status = CustomerApplicationStatus.PAID
                app.stripe_payment_intent_id = payment_intent_id
                app.updated_at = datetime.now(timezone.utc)
                await _add_state_log(
                    db, app,
                    from_status=prev_status,
                    to_status=CustomerApplicationStatus.PAID,
                    changed_by="stripe",
                    note=f"Payment confirmed — intent {payment_intent_id}",
                )
                await db.commit()
                log.info("stripe_webhook.payment_confirmed", application_id=application_id_str)

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
    dependencies=[Depends(require_admin_key)],
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
    admin_id: str = Depends(require_admin_key),
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
        changed_by=admin_id,
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
    dependencies=[Depends(require_admin_key)],
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
# Admin: HTML-to-PDF report download
# ─────────────────────────────────────────────

_REPORT_TEMPLATE = (
    Path(__file__).parent.parent / "templates" / "aiscore-report.html"
)


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

    substitutions = {
        "{{COMPANY_NAME}}": app.firmanavn,
        "{{CONTACT_EMAIL}}": app.email,
        "{{ANALYSIS_DATE}}": analysis_date,
        "{{OVERALL_SCORE}}": f"{app.overall_score} / 100" if app.overall_score is not None else "–",
        "{{SYSTEMS_ANALYZED}}": "4",
        "{{QUERIES_RUN}}": str(app.queries_run) if app.queries_run is not None else "–",
        "{{RANK}}": str(app.rank) if app.rank is not None else "–",
    }
    for placeholder, value in substitutions.items():
        template = template.replace(placeholder, str(value))
    return template


@router.get(
    "/admin/applications/{application_id}/report/pdf",
    dependencies=[Depends(require_admin_key)],
    include_in_schema=True,
    summary="Admin — download AIScore rapport som PDF",
)
@limiter.limit("10/minute")
async def download_report_pdf(
    request: Request,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
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
