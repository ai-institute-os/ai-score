"""
Async prompt router — fans out to all configured providers in parallel,
applies per-provider rate limiting, and writes results to PostgreSQL.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.llm.providers import REGISTRY, ProviderConfig, LLMResult
from src.llm.cache import PromptCache, prompt_hash
from src.llm.rate_limiter import RateLimiter
from src.db.models import LLMResponse, PromptRequest, TenantProviderConfig

if TYPE_CHECKING:
    from src.scoring.calculator import AIScore

log = structlog.get_logger()


class PromptRouter:
    def __init__(self, cache: PromptCache, rate_limiter: RateLimiter) -> None:
        from src.scoring.calculator import ScoreCalculator
        self.cache = cache
        self.rate_limiter = rate_limiter
        self._scorer = ScoreCalculator()

    async def _resolve_config(
        self,
        provider_name: str,
        tenant_configs: list[TenantProviderConfig],
        fallback_settings,
    ) -> Optional[ProviderConfig]:
        """Merge tenant DB config with environment fallbacks."""
        tenant_cfg = next(
            (c for c in tenant_configs if c.provider == provider_name and c.is_active),
            None,
        )
        if tenant_cfg:
            return ProviderConfig(
                api_key=tenant_cfg.api_key or "",
                extra=dict(tenant_cfg.extra_config or {}),
            )
        # Env fallback
        fallbacks = {
            "openai": fallback_settings.openai_api_key,
            "gemini": fallback_settings.google_api_key,
            "perplexity": fallback_settings.perplexity_api_key,
            "claude": fallback_settings.anthropic_api_key,
        }
        key = fallbacks.get(provider_name, "")
        if not key:
            return None
        return ProviderConfig(api_key=key, extra={})

    async def _call_provider(
        self,
        provider_name: str,
        prompt: str,
        config: ProviderConfig,
        tenant_id: str,
        request_id: uuid.UUID,
    ) -> LLMResult:
        provider = REGISTRY[provider_name]

        # Check cache first
        cached_text = await self.cache.get(tenant_id, provider_name, prompt)
        if cached_text is not None:
            log.info("cache.hit", provider=provider_name, tenant_id=tenant_id)
            return LLMResult(
                provider=provider_name,
                model=config.extra.get("model", provider.default_model),
                prompt=prompt,
                response_text=cached_text,
                error=None,
                latency_ms=0,
                tokens_used=None,
                prompt_tokens=None,
                completion_tokens=None,
                request_id=request_id,
                cached=True,
            )

        # Rate-limit before calling
        await self.rate_limiter.acquire(provider_name)

        result = await provider.complete(prompt, config)
        result.request_id = request_id

        # Populate cache on success
        if result.response_text and not result.error:
            await self.cache.set(tenant_id, provider_name, prompt, result.response_text)

        return result

    async def _persist(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        request_id: uuid.UUID,
        result: LLMResult,
        aiscore: Optional[AIScore] = None,
    ) -> None:
        score_total = Decimal(str(round(aiscore.total, 2))) if aiscore is not None else None
        score_dims = aiscore.as_dict() if aiscore is not None else None
        row = LLMResponse(
            tenant_id=tenant_id,
            prompt=result.prompt,
            prompt_hash=prompt_hash(result.prompt),
            provider=result.provider,
            model=result.model,
            response_text=result.response_text,
            error=result.error,
            score=score_total,
            score_dimensions=score_dims,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            timestamp=datetime.utcnow(),
            request_id=request_id,
            cached=result.cached,
        )
        session.add(row)

    async def route(
        self,
        prompt: str,
        tenant_id: uuid.UUID,
        tenant_configs: list[TenantProviderConfig],
        session: AsyncSession,
        settings,
        providers: Optional[list[str]] = None,
        scoring_keyword: Optional[str] = None,
    ) -> list[LLMResult]:
        """
        Fan out prompt to all (or selected) providers in parallel.
        Returns results for all providers; errors are recorded, not raised.
        Scores each response and runs change detection when scoring_keyword is provided.
        """
        request_id = uuid.uuid4()
        active_providers = providers or list(REGISTRY.keys())

        # Create prompt request record
        pr = PromptRequest(
            tenant_id=tenant_id,
            prompt=prompt,
            prompt_hash=prompt_hash(prompt),
            status="pending",
        )
        session.add(pr)
        await session.flush()

        async def _run(name: str) -> LLMResult:
            cfg = await self._resolve_config(name, tenant_configs, settings)
            if cfg is None:
                log.info("router.provider_skipped", provider=name, reason="no_config")
                return LLMResult(
                    provider=name,
                    model="unknown",
                    prompt=prompt,
                    response_text=None,
                    error="No API key configured for this provider",
                    latency_ms=0,
                    tokens_used=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    request_id=request_id,
                )
            try:
                return await self._call_provider(name, prompt, cfg, str(tenant_id), request_id)
            except Exception as exc:
                log.error("router.provider_error", provider=name, error=str(exc))
                return LLMResult(
                    provider=name,
                    model=cfg.extra.get("model", REGISTRY[name].default_model),
                    prompt=prompt,
                    response_text=None,
                    error=str(exc),
                    latency_ms=0,
                    tokens_used=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    request_id=request_id,
                )

        results = await asyncio.gather(*[_run(p) for p in active_providers])

        from src.scoring.calculator import AIScore
        from src.scoring.aggregator import aggregate_scores
        from src.scoring.change_detector import detect_and_create_alert

        # Compute structured AIScores in-memory
        provider_aiscores: dict[str, Optional[AIScore]] = {}
        for result in results:
            aiscore = self._scorer.calculate(result, keyword=scoring_keyword)
            provider_aiscores[result.provider] = aiscore if aiscore.total > 0 else None

        # Cross-provider weighted aggregation (stored on request for downstream reporting)
        scored_map = {p: s for p, s in provider_aiscores.items() if s is not None}
        aggregated = aggregate_scores(scored_map) if scored_map else None
        if aggregated:
            log.info(
                "router.aggregated_aiscore",
                tenant_id=str(tenant_id),
                total=aggregated.total,
                naevnt=aggregated.naevnt,
                valgt=aggregated.valgt,
                valgbarhed=aggregated.valgbarhed,
                konkurrenceposition=aggregated.konkurrenceposition,
            )

        # Persist results with structured scores
        for result in results:
            await self._persist(
                session, tenant_id, request_id, result,
                aiscore=provider_aiscores[result.provider],
            )

        # Change detection — runs before commit so alerts land in the same transaction
        window_days = getattr(settings, "scoring_window_days", 7)
        threshold = getattr(settings, "scoring_alert_threshold", 10.0)
        for result in results:
            aiscore = provider_aiscores.get(result.provider)
            if aiscore is not None and aiscore.total > 0:
                await detect_and_create_alert(
                    session=session,
                    tenant_id=tenant_id,
                    provider=result.provider,
                    current_score=aiscore.total,
                    window_days=window_days,
                    threshold=threshold,
                )

        # Update request status
        errors = [r for r in results if r.error]
        pr.status = "error" if len(errors) == len(results) else (
            "partial" if errors else "complete"
        )

        await session.commit()
        return list(results)
