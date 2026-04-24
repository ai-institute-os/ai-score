import uuid
from datetime import datetime
from typing import Optional
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db import get_db
from src.db.models import CustomerApplication, CustomerApplicationStateLog, CustomerApplicationStatus, VALID_TRANSITIONS
from src.api.schemas import (
    ApplicationCreate, ApplicationResponse, ApplicationStatusUpdate,
    GeneratePaymentLinkRequest, PaymentLinkResponse,
    QCResultSubmit, ManualCorrectionRequest,
)

log = structlog.get_logger()
router = APIRouter()

# Number of QC failures before escalation / cancellation
_QC_ESCALATION_THRESHOLD = 3


# ─────────────────────────────────────────────
# Public: submit an application
# ─────────────────────────────────────────────

@router.post("/apply", response_model=ApplicationResponse, status_code=201)
async def submit_application(body: ApplicationCreate, db: AsyncSession = Depends(get_db)):
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

    log = CustomerApplicationStateLog(
        application_id=app.id,
        from_status=None,
        to_status=CustomerApplicationStatus.APPLIED,
        changed_by="system",
        note="Application submitted",
    )
    db.add(log)
    await db.commit()
    await db.refresh(app)

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


# ─────────────────────────────────────────────
# Admin: list and manage applications
# ─────────────────────────────────────────────

@router.get("/admin/applications", response_model=list[ApplicationResponse])
async def list_applications(
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


@router.get("/admin/applications/{application_id}", response_model=ApplicationResponse)
async def get_application(application_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Admin — get a single application with full state log."""
    app = await _get_application_or_404(application_id, db)
    return app


@router.patch("/admin/applications/{application_id}/status", response_model=ApplicationResponse)
async def update_application_status(
    application_id: uuid.UUID,
    body: ApplicationStatusUpdate,
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
    app.status = new_status
    app.updated_at = datetime.utcnow()

    log = CustomerApplicationStateLog(
        application_id=app.id,
        from_status=prev_status,
        to_status=new_status,
        changed_by=body.changed_by,
        note=body.note,
    )
    db.add(log)
    await db.commit()

    result = await db.execute(
        select(CustomerApplication)
        .options(selectinload(CustomerApplication.state_logs))
        .where(CustomerApplication.id == app.id)
    )
    return result.scalar_one()


@router.patch("/admin/applications/{application_id}/notes", response_model=ApplicationResponse)
async def update_application_notes(
    application_id: uuid.UUID,
    notes: str,
    db: AsyncSession = Depends(get_db),
):
    """Admin — update internal notes on an application."""
    app = await _get_application_or_404(application_id, db)
    app.notes = notes
    app.updated_at = datetime.utcnow()
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
# Payment link generation
# ─────────────────────────────────────────────

@router.post(
    "/admin/applications/{application_id}/payment-link",
    response_model=PaymentLinkResponse,
    status_code=201,
)
async def generate_payment_link(
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
    app.updated_at = datetime.utcnow()
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
# Stripe webhook (payment confirmed)
# ─────────────────────────────────────────────

@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Stripe sends checkout.session.completed here.
    We verify the signature and advance the application to PAID.
    """
    from src.payments import construct_stripe_event
    import stripe as _stripe

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_stripe_event(payload, sig_header)
    except (_stripe.error.SignatureVerificationError, ValueError) as exc:
        log.warning("stripe_webhook.invalid_signature", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
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
            app.updated_at = datetime.utcnow()
            await _add_state_log(
                db, app,
                from_status=prev_status,
                to_status=CustomerApplicationStatus.PAID,
                changed_by="stripe",
                note=f"Payment confirmed — intent {payment_intent_id}",
            )
            await db.commit()
            log.info("stripe_webhook.payment_confirmed", application_id=application_id_str)

    return {"received": True}


# ─────────────────────────────────────────────
# QC loop — 3+3 escalation
# ─────────────────────────────────────────────

@router.post(
    "/admin/applications/{application_id}/qc-result",
    response_model=ApplicationResponse,
)
async def submit_qc_result(
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
        app.updated_at = datetime.utcnow()
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
        app.updated_at = datetime.utcnow()
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
        app.updated_at = datetime.utcnow()
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
        app.updated_at = datetime.utcnow()
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
async def submit_manual_correction(
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
    app.updated_at = datetime.utcnow()
    await _add_state_log(
        db, app,
        from_status=prev_status,
        to_status=CustomerApplicationStatus.RETRY,
        changed_by=body.changed_by or "dennis",
        note=body.note or "Manual correction applied",
    )

    # Immediately advance to IN_PRODUCTION
    app.status = CustomerApplicationStatus.IN_PRODUCTION
    app.updated_at = datetime.utcnow()
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
