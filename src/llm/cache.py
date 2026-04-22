"""
Prompt cache backed by Redis.

Cache key: SHA-256(tenant_id + ":" + provider + ":" + normalized_prompt)
TTL is configurable per deployment (default 300 s).
Falls back to an in-process LRU when Redis is unavailable.
"""

import hashlib
import json
from collections import OrderedDict
from typing import Optional
import redis.asyncio as aioredis
import structlog

log = structlog.get_logger()

_LOCAL_MAX = 512  # in-process fallback capacity


def _hash(tenant_id: str, provider: str, prompt: str) -> str:
    raw = f"{tenant_id}:{provider}:{prompt.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def prompt_hash(prompt: str) -> str:
    """Standalone hash of a prompt (for DB indexing, provider-agnostic)."""
    return hashlib.sha256(prompt.strip().encode()).hexdigest()


class PromptCache:
    def __init__(self, redis_url: str, ttl_seconds: int = 300) -> None:
        self._redis_url = redis_url
        self._ttl = ttl_seconds
        self._redis: Optional[aioredis.Redis] = None
        self._local: OrderedDict[str, str] = OrderedDict()

    async def _client(self) -> Optional[aioredis.Redis]:
        if self._redis is None:
            try:
                self._redis = await aioredis.from_url(self._redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception as exc:
                log.warning("cache.redis_unavailable", error=str(exc))
                self._redis = None
        return self._redis

    async def get(self, tenant_id: str, provider: str, prompt: str) -> Optional[str]:
        key = _hash(tenant_id, provider, prompt)
        client = await self._client()
        if client:
            try:
                return await client.get(f"prompt:{key}")
            except Exception:
                self._redis = None
        # Fallback
        return self._local.get(key)

    async def set(self, tenant_id: str, provider: str, prompt: str, response: str) -> None:
        key = _hash(tenant_id, provider, prompt)
        client = await self._client()
        if client:
            try:
                await client.setex(f"prompt:{key}", self._ttl, response)
                return
            except Exception:
                self._redis = None
        # Fallback: simple LRU eviction
        if len(self._local) >= _LOCAL_MAX:
            self._local.popitem(last=False)
        self._local[key] = response
