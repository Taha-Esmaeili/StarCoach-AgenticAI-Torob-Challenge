"""FastAPI application entrypoint for Torob Smart In-Person Shopping Assistant."""

from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.models.schemas import DatasetCounts, HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage PostgreSQL (`asyncpg`) and Redis (`redis.asyncio`) connection pools configured via .env."""
    app.state.pg_pool = None
    app.state.redis = None

    try:
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=settings.asyncpg_dsn,
            min_size=settings.postgres_pool_min_size,
            max_size=settings.postgres_pool_max_size,
            command_timeout=settings.postgres_command_timeout_seconds,
        )
    except Exception:
        # shortcut: allow app startup before docker-compose / DB ingestion runs; health endpoint reports postgres_pgvector_ready=False
        app.state.pg_pool = None

    try:
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
        )
        await redis_client.ping()
        app.state.redis = redis_client
    except Exception:
        app.state.redis = None

    yield

    if getattr(app.state, "pg_pool", None) is not None:
        await app.state.pg_pool.close()
    if getattr(app.state, "redis", None) is not None:
        await app.state.redis.aclose()


app = FastAPI(
    title="Torob Smart In-Person Shopping Assistant API (ترب‌چیت حضوری)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _probe_postgres_counts(pg_pool: Any) -> tuple[bool, DatasetCounts]:
    if pg_pool is None:
        return False, DatasetCounts()
    try:
        async with pg_pool.acquire() as conn:
            has_vector = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector');"
            )
            has_shops = await conn.fetchval("SELECT to_regclass('public.shops') IS NOT NULL;")
            if not has_shops:
                return bool(has_vector), DatasetCounts()

            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM shops) AS shops_count,
                    (SELECT COUNT(*) FROM products) AS products_count,
                    (SELECT COUNT(*) FROM offers) AS offers_count,
                    (SELECT COUNT(*) FROM shops WHERE is_real_torob_shop = TRUE) AS real_shops_count
                """
            )
            counts = DatasetCounts(
                shops=int(row["shops_count"] or 0),
                products=int(row["products_count"] or 0),
                offers=int(row["offers_count"] or 0),
                real_torob_shops=int(row["real_shops_count"] or 0),
            )
            return bool(has_vector), counts
    except Exception:
        return False, DatasetCounts()


async def _probe_redis(redis_client: Any) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False


@app.get(f"{settings.api_v1_prefix}/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Liara readiness and PostgreSQL + pgvector + Redis dataset integrity probe."""
    pg_ready, counts = await _probe_postgres_counts(getattr(request.app.state, "pg_pool", None))
    redis_ready = await _probe_redis(getattr(request.app.state, "redis", None))
    overall_status = "ok" if (pg_ready and redis_ready) else "degraded"
    return HealthResponse(
        status=overall_status,
        postgres_pgvector_ready=pg_ready,
        redis_ready=redis_ready,
        counts=counts,
        jev_engine_mode=settings.jev_engine_mode,
    )
