import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db import get_db
from src.db.models import CustomerApplication, CustomerApplicationStateLog, CustomerApplicationStatus, VALID_TRANSITIONS
from src.api.schemas import ApplicationCreate, ApplicationResponse, ApplicationStatusUpdate

router = APIRouter()


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
