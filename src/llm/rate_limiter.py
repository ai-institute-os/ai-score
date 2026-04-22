"""
Token-bucket rate limiter per provider, backed by Redis.

Each bucket allows `rpm` requests per 60-second window using a sliding
window counter stored in Redis. Falls back to an in-process dict when
Redis is unavailable so the service degrades gracefully.
"""

import asyncio
import time
from collections import defaultdict
from typing import Optional
import redis.asyncio as aioredis
import structlog

log = structlog.get_logger()


class RateLimiter:
    def __init__(self, redis_url: str, defaults: dict[str, int]) -> None:
        self._redis_url = redis_url
        self._defaults = defaults  # {provider: rpm}
        self._redis: Optional[aioredis.Redis] = None
        # In-process fallback: {provider: list[float]} of call timestamps
        self._fallback: dict[str, list[float]] = defaultdict(list)

    async def _client(self) -> Optional[aioredis.Redis]:
        if self._redis is None:
            try:
                self._redis = await aioredis.from_url(self._redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception as exc:
                log.warning("rate_limiter.redis_unavailable", error=str(exc))
                self._redis = None
        return self._redis

    async def acquire(self, provider: str, rpm: Optional[int] = None) -> None:
        """Block until a request slot is available for the given provider."""
        limit = rpm or self._defaults.get(provider, 60)
        while True:
            if not await self._try_acquire_redis(provider, limit):
                await asyncio.sleep(1)
            else:
                break

    async def _try_acquire_redis(self, provider: str, limit: int) -> bool:
        client = await self._client()
        if client is None:
            return self._try_acquire_local(provider, limit)

        key = f"ratelimit:{provider}"
        now = time.time()
        window_start = now - 60

        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, 65)
            _, count, _, _ = await pipe.execute()
            if count >= limit:
                # We added an entry speculatively; remove it
                await client.zrem(key, str(now))
                return False
            return True
        except Exception as exc:
            log.warning("rate_limiter.redis_error", error=str(exc))
            self._redis = None
            return self._try_acquire_local(provider, limit)

    def _try_acquire_local(self, provider: str, limit: int) -> bool:
        now = time.time()
        window_start = now - 60
        calls = [t for t in self._fallback[provider] if t > window_start]
        if len(calls) >= limit:
            self._fallback[provider] = calls
            return False
        calls.append(now)
        self._fallback[provider] = calls
        return True
