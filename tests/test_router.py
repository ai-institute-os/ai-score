"""
Unit tests for the PromptRouter using stubbed providers.
No real API calls or database connections needed.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.llm.cache import PromptCache
from src.llm.rate_limiter import RateLimiter
from src.llm.router import PromptRouter
from src.llm.providers.base import LLMResult


def _make_result(provider: str, text: str = "ok") -> LLMResult:
    return LLMResult(
        provider=provider,
        model="test-model",
        prompt="test prompt",
        response_text=text,
        error=None,
        latency_ms=100,
        tokens_used=10,
        prompt_tokens=5,
        completion_tokens=5,
        request_id=uuid.uuid4(),
    )


@pytest.fixture
def cache():
    return PromptCache(redis_url="redis://localhost:19999/99", ttl_seconds=60)


@pytest.fixture
def rate_limiter():
    rl = RateLimiter(
        redis_url="redis://localhost:19999/99",
        defaults={"openai": 60, "gemini": 60, "perplexity": 20, "claude": 50},
    )
    return rl


@pytest.fixture
def router(cache, rate_limiter):
    return PromptRouter(cache=cache, rate_limiter=rate_limiter)


@pytest.mark.asyncio
async def test_router_fans_out_to_all_providers(router):
    tenant_id = uuid.uuid4()
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    # Return no DB history so change_detector exits early (no alert)
    _db_result = MagicMock()
    _db_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=_db_result)

    settings = MagicMock(
        openai_api_key="sk-test",
        google_api_key="g-test",
        perplexity_api_key="pp-test",
        anthropic_api_key="sk-ant-test",
        scoring_window_days=7,
        scoring_alert_threshold=10.0,
    )

    stub_results = {
        "openai": _make_result("openai"),
        "gemini": _make_result("gemini"),
        "perplexity": _make_result("perplexity"),
        "claude": _make_result("claude"),
    }

    async def fake_complete(prompt, config):
        return stub_results[provider_name]

    with patch("src.llm.router.REGISTRY") as mock_reg:
        for name in ["openai", "gemini", "perplexity", "claude"]:
            provider_name = name
            p = MagicMock()
            p.default_model = "test-model"
            p.complete = AsyncMock(return_value=stub_results[name])
            mock_reg.__contains__ = lambda self, k: True
            mock_reg.__iter__ = lambda self: iter(["openai", "gemini", "perplexity", "claude"])
            mock_reg.keys = MagicMock(return_value=["openai", "gemini", "perplexity", "claude"])
            mock_reg.__getitem__ = lambda self, k: p

        results = await router.route(
            prompt="test prompt",
            tenant_id=tenant_id,
            tenant_configs=[],
            session=session,
            settings=settings,
            providers=["openai", "gemini", "perplexity", "claude"],
        )

    assert len(results) == 4


@pytest.mark.asyncio
async def test_router_returns_error_result_on_provider_exception(router):
    tenant_id = uuid.uuid4()
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    settings = MagicMock(
        openai_api_key="sk-test",
        google_api_key="",
        perplexity_api_key="",
        anthropic_api_key="",
    )

    broken_provider = MagicMock()
    broken_provider.default_model = "test-model"
    broken_provider.complete = AsyncMock(side_effect=RuntimeError("Network error"))

    with patch("src.llm.router.REGISTRY", {"openai": broken_provider}):
        results = await router.route(
            prompt="test prompt",
            tenant_id=tenant_id,
            tenant_configs=[],
            session=session,
            settings=settings,
            providers=["openai"],
        )

    assert len(results) == 1
    assert results[0].error is not None
    assert results[0].response_text is None
