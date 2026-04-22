import pytest
from src.llm.cache import PromptCache, prompt_hash


@pytest.fixture
def cache():
    # Use a non-existent Redis URL so it falls back to in-process cache
    return PromptCache(redis_url="redis://localhost:19999/99", ttl_seconds=60)


@pytest.mark.asyncio
async def test_cache_miss_returns_none(cache):
    result = await cache.get("tenant-1", "openai", "Hello?")
    assert result is None


@pytest.mark.asyncio
async def test_cache_set_and_get(cache):
    await cache.set("tenant-1", "openai", "Hello?", "World!")
    result = await cache.get("tenant-1", "openai", "Hello?")
    assert result == "World!"


@pytest.mark.asyncio
async def test_cache_is_provider_scoped(cache):
    await cache.set("tenant-1", "openai", "Hello?", "OpenAI response")
    result = await cache.get("tenant-1", "gemini", "Hello?")
    assert result is None


@pytest.mark.asyncio
async def test_cache_is_tenant_scoped(cache):
    await cache.set("tenant-1", "openai", "Hello?", "T1 response")
    result = await cache.get("tenant-2", "openai", "Hello?")
    assert result is None


def test_prompt_hash_is_deterministic():
    h1 = prompt_hash("  Hello world  ")
    h2 = prompt_hash("  Hello world  ")
    assert h1 == h2


def test_prompt_hash_strips_whitespace():
    h1 = prompt_hash("Hello world")
    h2 = prompt_hash("  Hello world  ")
    assert h1 == h2
