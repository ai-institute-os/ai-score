import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db, Tenant, TenantProviderConfig, LLMResponse, ScoreAlert
from src.api.schemas import (
    PromptRequest, PromptResponse, LLMResultSchema,
    TenantCreate, TenantResponse,
    ProviderConfigCreate, ProviderConfigResponse,
    LLMResponseRecord,
    ProviderScore, AlertRecord, RecalculateResponse,
)
from src.llm.providers import REGISTRY
from src.scoring.calculator import ScoreCalculator

router = APIRouter()


# ─────────────────────────────────────────────
# Tenant management
# ─────────────────────────────────────────────

@router.post("/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already exists")
    tenant = Tenant(name=body.name, slug=body.slug)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await _get_tenant_or_404(tenant_id, db)
    return tenant


@router.post("/tenants/{tenant_id}/providers", response_model=ProviderConfigResponse, status_code=201)
async def upsert_provider_config(
    tenant_id: uuid.UUID,
    body: ProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    await _get_tenant_or_404(tenant_id, db)
    if body.provider not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}")

    result = await db.execute(
        select(TenantProviderConfig).where(
            TenantProviderConfig.tenant_id == tenant_id,
            TenantProviderConfig.provider == body.provider,
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.api_key = body.api_key
        cfg.extra_config = body.extra_config
        cfg.is_active = body.is_active
    else:
        cfg = TenantProviderConfig(
            tenant_id=tenant_id,
            provider=body.provider,
            api_key=body.api_key,
            extra_config=body.extra_config,
            is_active=body.is_active,
        )
        db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg


# ─────────────────────────────────────────────
# Prompt routing
# ─────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/prompt", response_model=PromptResponse)
async def route_prompt(
    tenant_id: uuid.UUID,
    body: PromptRequest,
    db: AsyncSession = Depends(get_db),
):
    from src.main import get_router  # late import to avoid circular dep

    tenant = await _get_tenant_or_404(tenant_id, db)

    configs_result = await db.execute(
        select(TenantProviderConfig).where(
            TenantProviderConfig.tenant_id == tenant_id,
            TenantProviderConfig.is_active == True,
        )
    )
    tenant_configs = list(configs_result.scalars().all())

    from src.config import get_settings
    settings = get_settings()

    prompt_router = get_router()
    results = await prompt_router.route(
        prompt=body.prompt,
        tenant_id=tenant_id,
        tenant_configs=tenant_configs,
        session=db,
        settings=settings,
        providers=body.providers,
        scoring_keyword=tenant.name,
    )

    errors = [r for r in results if r.error]
    status = "error" if len(errors) == len(results) else (
        "partial" if errors else "complete"
    )
    request_id = results[0].request_id if results else uuid.uuid4()

    return PromptResponse(
        request_id=request_id,
        tenant_id=tenant_id,
        prompt=body.prompt,
        results=[
            LLMResultSchema(
                provider=r.provider,
                model=r.model,
                response_text=r.response_text,
                error=r.error,
                latency_ms=r.latency_ms,
                tokens_used=r.tokens_used,
                prompt_tokens=r.prompt_tokens,
                completion_tokens=r.completion_tokens,
                cached=r.cached,
                request_id=r.request_id,
            )
            for r in results
        ],
        status=status,
    )


# ─────────────────────────────────────────────
# History queries
# ─────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/responses", response_model=list[LLMResponseRecord])
async def list_responses(
    tenant_id: uuid.UUID,
    provider: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    await _get_tenant_or_404(tenant_id, db)
    q = select(LLMResponse).where(LLMResponse.tenant_id == tenant_id)
    if provider:
        q = q.where(LLMResponse.provider == provider)
    q = q.order_by(LLMResponse.timestamp.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


# ─────────────────────────────────────────────
# Scoring endpoints
# ─────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/scores", response_model=list[ProviderScore])
async def get_scores(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Latest scored response per provider for this tenant."""
    await _get_tenant_or_404(tenant_id, db)

    # For each provider: get the row with the most recent timestamp where score IS NOT NULL
    subq = (
        select(
            LLMResponse.provider,
            func.max(LLMResponse.timestamp).label("latest_ts"),
        )
        .where(
            LLMResponse.tenant_id == tenant_id,
            LLMResponse.score.is_not(None),
        )
        .group_by(LLMResponse.provider)
        .subquery()
    )
    q = (
        select(LLMResponse)
        .join(
            subq,
            (LLMResponse.provider == subq.c.provider)
            & (LLMResponse.timestamp == subq.c.latest_ts),
        )
        .where(LLMResponse.tenant_id == tenant_id)
    )
    result = await db.execute(q)
    rows = list(result.scalars().all())
    return [
        ProviderScore(provider=r.provider, model=r.model, score=r.score, timestamp=r.timestamp)
        for r in rows
    ]


@router.get("/tenants/{tenant_id}/alerts", response_model=list[AlertRecord])
async def get_alerts(
    tenant_id: uuid.UUID,
    provider: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """Score-change alert history for this tenant."""
    await _get_tenant_or_404(tenant_id, db)
    q = select(ScoreAlert).where(ScoreAlert.tenant_id == tenant_id)
    if provider:
        q = q.where(ScoreAlert.provider == provider)
    q = q.order_by(ScoreAlert.triggered_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post(
    "/tenants/{tenant_id}/scores/recalculate",
    response_model=RecalculateResponse,
    status_code=202,
)
async def recalculate_scores(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Batch-score up to 500 unscored historical responses for this tenant."""
    tenant = await _get_tenant_or_404(tenant_id, db)

    q = (
        select(LLMResponse)
        .where(
            LLMResponse.tenant_id == tenant_id,
            LLMResponse.score.is_(None),
            LLMResponse.error.is_(None),
            LLMResponse.response_text.is_not(None),
        )
        .limit(500)
    )
    result = await db.execute(q)
    rows = list(result.scalars().all())

    if not rows:
        return RecalculateResponse(updated=0, message="No unscored responses found")

    from src.llm.providers.base import LLMResult as LLMResultDC
    calculator = ScoreCalculator()

    for row in rows:
        mock = LLMResultDC(
            provider=row.provider,
            model=row.model,
            prompt=row.prompt,
            response_text=row.response_text,
            error=row.error,
            latency_ms=row.latency_ms or 0,
            tokens_used=row.tokens_used,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
        )
        score = calculator.calculate(mock, keyword=tenant.name)
        if score > 0:
            row.score = Decimal(str(round(score, 2)))

    await db.commit()
    scored_count = sum(1 for r in rows if r.score is not None)
    return RecalculateResponse(
        updated=scored_count,
        message=f"Scored {scored_count} of {len(rows)} responses",
    )


# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _get_tenant_or_404(tenant_id: uuid.UUID, db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant
