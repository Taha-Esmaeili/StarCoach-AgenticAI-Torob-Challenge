"""Redis caching and session state manager (100% .env-driven via `backend.config.settings`)."""

import hashlib
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from backend.config import settings

logger = logging.getLogger(__name__)


def session_key(session_id: str) -> str:
    return f"{settings.redis_key_prefix}:session:{session_id}"


def profile_key(user_id: str) -> str:
    return f"{settings.redis_key_prefix}:profile:{user_id}"


def query_cache_key(namespace: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{settings.redis_key_prefix}:qcache:{namespace}:{digest}"


async def create_redis_client() -> aioredis.Redis:
    """Create an async Redis client using `.env` settings."""
    return aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
    )


async def get_cached_json(redis_client: aioredis.Redis | None, key: str) -> dict[str, Any] | list[Any] | None:
    if redis_client is None:
        return None
    try:
        raw = await redis_client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.debug("Redis get_cached_json failed for %s: %s", key, exc)
        return None


async def set_cached_json(
    redis_client: aioredis.Redis | None,
    key: str,
    value: Any,
    ttl_seconds: int,
) -> bool:
    if redis_client is None:
        return False
    try:
        await redis_client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
        return True
    except Exception as exc:
        logger.debug("Redis set_cached_json failed for %s: %s", key, exc)
        return False


async def delete_cached_key(redis_client: aioredis.Redis | None, key: str) -> None:
    if redis_client is None:
        return
    try:
        await redis_client.delete(key)
    except Exception as exc:
        logger.debug("Redis delete_cached_key failed for %s: %s", key, exc)
        return
