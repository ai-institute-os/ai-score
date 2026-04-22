"""
Change detector — compares a new score against the rolling average for a
provider and creates a ScoreAlert when the delta exceeds the threshold.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import LLMResponse, ScoreAlert

log = structlog.get_logger()


async def detect_and_create_alert(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    provider: str,
    current_score: float,
    window_days: int = 7,
    threshold: float = 10.0,
) -> Optional[ScoreAlert]:
    """
    Queries the rolling average score for `provider` over the past `window_days`
    and creates a ScoreAlert (added to session, not yet committed) if
    abs(current_score - avg) >= threshold.

    Returns the alert object or None if no significant change detected.
    """
    cutoff = datetime.utcnow() - timedelta(days=window_days)

    result = await session.execute(
        select(func.avg(LLMResponse.score)).where(
            LLMResponse.tenant_id == tenant_id,
            LLMResponse.provider == provider,
            LLMResponse.score.is_not(None),
            LLMResponse.timestamp >= cutoff,
        )
    )
    avg_score = result.scalar_one_or_none()

    if avg_score is None:
        log.debug(
            "change_detector.no_history",
            provider=provider,
            tenant_id=str(tenant_id),
        )
        return None

    delta = current_score - float(avg_score)

    if abs(delta) < threshold:
        log.debug(
            "change_detector.below_threshold",
            provider=provider,
            delta=round(delta, 2),
            threshold=threshold,
        )
        return None

    alert = ScoreAlert(
        tenant_id=tenant_id,
        provider=provider,
        score_before=Decimal(str(round(float(avg_score), 2))),
        score_after=Decimal(str(round(current_score, 2))),
        delta=Decimal(str(round(delta, 2))),
    )
    session.add(alert)
    log.info(
        "change_detector.alert_created",
        provider=provider,
        tenant_id=str(tenant_id),
        score_before=round(float(avg_score), 2),
        score_after=round(current_score, 2),
        delta=round(delta, 2),
    )
    return alert
