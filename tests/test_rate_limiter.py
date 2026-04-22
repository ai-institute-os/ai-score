import pytest
from src.llm.rate_limiter import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(
        redis_url="redis://localhost:19999/99",  # non-existent → local fallback
        defaults={"openai": 5},
    )


@pytest.mark.asyncio
async def test_rate_limiter_allows_up_to_limit(limiter):
    for _ in range(5):
        # Should acquire without waiting since limit is 5/min
        acquired = limiter._try_acquire_local("openai", 5)
        assert acquired is True


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_limit_reached(limiter):
    # Fill the bucket
    for _ in range(5):
        limiter._try_acquire_local("openai", 5)
    # 6th call should be blocked
    acquired = limiter._try_acquire_local("openai", 5)
    assert acquired is False


@pytest.mark.asyncio
async def test_rate_limiter_different_providers_independent(limiter):
    for _ in range(5):
        limiter._try_acquire_local("openai", 5)
    # gemini bucket is empty
    acquired = limiter._try_acquire_local("gemini", 5)
    assert acquired is True
