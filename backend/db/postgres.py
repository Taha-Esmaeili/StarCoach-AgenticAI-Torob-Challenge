"""PostgreSQL + pgvector + pg_trgm schema DDL, idempotent migrations, and connection pool helpers."""

import json
import asyncpg
from backend.config import settings


def get_schema_ddl(embedding_dim: int | None = None) -> str:
    """Return idempotent PostgreSQL + pgvector + pg_trgm DDL parameterized by EMBEDDING_DIM."""
    dim = embedding_dim or settings.embedding_dim
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS shops (
    shop_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    location_label TEXT,
    address TEXT,
    mall_name TEXT,
    floor_label TEXT,
    unit_label TEXT,
    mall_note TEXT,
    contacts_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    primary_phone TEXT NOT NULL DEFAULT '',
    score DOUBLE PRECISION NOT NULL DEFAULT 4.5,
    votes_count INTEGER NOT NULL DEFAULT 15,
    supports_fast_delivery BOOLEAN NOT NULL DEFAULT FALSE,
    payment_options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    has_in_person_installment BOOLEAN NOT NULL DEFAULT FALSE,
    installment_providers TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    weekly_hours_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    category_names_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    website_url TEXT,
    instagram TEXT,
    is_real_torob_shop BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    persian_title TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    model_name TEXT,
    category_name TEXT NOT NULL,
    brand_name TEXT,
    image_url TEXT NOT NULL DEFAULT '',
    image_urls_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    specs_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    min_price_toman BIGINT NOT NULL DEFAULT 0,
    max_price_toman BIGINT NOT NULL DEFAULT 0,
    offer_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    price_toman BIGINT NOT NULL,
    seller_title TEXT,
    description TEXT,
    warranty_raw TEXT,
    has_official_warranty BOOLEAN NOT NULL DEFAULT FALSE,
    warranty_provider TEXT,
    warranty_months INTEGER,
    last_price_changed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    store_weights_json JSONB NOT NULL,
    price_percentiles_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_trait_memory (
    trait_id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    source_category TEXT NOT NULL DEFAULT '',
    aspect TEXT NOT NULL,
    preference TEXT NOT NULL,
    aspect_embedding vector({dim}),
    strength DOUBLE PRECISION NOT NULL DEFAULT 0.50,
    hit_count INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_trait_memory_user_strength
    ON user_trait_memory (user_id, strength DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS shopping_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_lat DOUBLE PRECISION NOT NULL,
    user_lng DOUBLE PRECISION NOT NULL,
    active_category_name TEXT,
    selected_product_id TEXT,
    effective_weights_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    hard_constraints_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    session_context_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    clarification_count INTEGER NOT NULL DEFAULT 0,
    dissatisfaction_triggered BOOLEAN NOT NULL DEFAULT FALSE,
    messages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_shops_lat_lng ON shops (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_shops_real ON shops (is_real_torob_shop);
CREATE INDEX IF NOT EXISTS idx_shops_mall_name ON shops (mall_name) WHERE mall_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shops_categories_gin ON shops USING GIN (category_names_json);

CREATE INDEX IF NOT EXISTS idx_products_norm_trgm ON products USING GIN (normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_spaceless_trgm ON products USING GIN (REPLACE(normalized_name, ' ', '') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_category ON products (category_name);
CREATE INDEX IF NOT EXISTS idx_shopping_sessions_user_updated ON shopping_sessions (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_products_offer_count ON products (offer_count DESC, min_price_toman ASC);

CREATE INDEX IF NOT EXISTS idx_offers_product_price ON offers (product_id, price_toman ASC);
CREATE INDEX IF NOT EXISTS idx_offers_shop ON offers (shop_id);
"""


async def create_pg_pool() -> asyncpg.Pool:
    """Create an asyncpg connection pool using .env settings."""
    return await asyncpg.create_pool(
        dsn=settings.asyncpg_dsn,
        min_size=settings.postgres_pool_min_size,
        max_size=settings.postgres_pool_max_size,
        command_timeout=settings.postgres_command_timeout_seconds,
    )


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Idempotently migrate legacy tables/columns and apply clean PostgreSQL + pgvector + pg_trgm DDL."""
    default_store_json = json.dumps(settings.default_store_weights, ensure_ascii=False)
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;")

        # 1. Purge dead 15-slot table & unused NULL product embedding column
        await conn.execute("DROP TABLE IF EXISTS user_dynamic_slots CASCADE;")
        if await conn.fetchval("SELECT to_regclass('public.products') IS NOT NULL"):
            await conn.execute("ALTER TABLE products DROP COLUMN IF EXISTS embedding;")

        # 2. Migrate existing user_profiles cleanly to store_weights_json + price_percentiles_json
        if await conn.fetchval("SELECT to_regclass('public.user_profiles') IS NOT NULL"):
            await conn.execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS store_weights_json JSONB;")
            await conn.execute(
                "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS price_percentiles_json JSONB NOT NULL DEFAULT '{}'::jsonb;"
            )
            has_legacy_base = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'user_profiles' AND column_name = 'base_weights_json'
                )
                """
            )
            if has_legacy_base:
                await conn.execute(
                    """
                    UPDATE user_profiles
                    SET store_weights_json = $1::jsonb || jsonb_build_object(
                        'w_price', COALESCE((base_weights_json->>'w_price')::double precision, ($1::jsonb->>'w_price')::double precision),
                        'w_distance', COALESCE((base_weights_json->>'w_distance')::double precision, ($1::jsonb->>'w_distance')::double precision),
                        'w_open_now', COALESCE((base_weights_json->>'w_open_now')::double precision, ($1::jsonb->>'w_open_now')::double precision)
                    )
                    WHERE store_weights_json IS NULL
                    """,
                    default_store_json,
                )
            else:
                await conn.execute(
                    "UPDATE user_profiles SET store_weights_json = $1::jsonb WHERE store_weights_json IS NULL;",
                    default_store_json,
                )
            await conn.execute("ALTER TABLE user_profiles ALTER COLUMN store_weights_json SET NOT NULL;")
            await conn.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS base_weights_json;")
            await conn.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS persona_weights_json;")

        # 3. Migrate existing user_trait_memory from hardcoded `domain` to open `source_category` + `strength`
        if await conn.fetchval("SELECT to_regclass('public.user_trait_memory') IS NOT NULL"):
            await conn.execute(
                "ALTER TABLE user_trait_memory ADD COLUMN IF NOT EXISTS source_category TEXT NOT NULL DEFAULT '';"
            )
            await conn.execute(
                "ALTER TABLE user_trait_memory ADD COLUMN IF NOT EXISTS strength DOUBLE PRECISION NOT NULL DEFAULT 0.50;"
            )
            has_legacy_domain = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'user_trait_memory' AND column_name = 'domain'
                )
                """
            )
            if has_legacy_domain:
                await conn.execute(
                    "UPDATE user_trait_memory SET source_category = domain WHERE source_category = '' AND domain IS NOT NULL;"
                )
                await conn.execute("DROP INDEX IF EXISTS idx_user_trait_memory_user_domain;")
                await conn.execute("ALTER TABLE user_trait_memory DROP COLUMN IF EXISTS domain;")

        # 4. Add durable session_context_json to shopping_sessions
        if await conn.fetchval("SELECT to_regclass('public.shopping_sessions') IS NOT NULL"):
            await conn.execute(
                "ALTER TABLE shopping_sessions ADD COLUMN IF NOT EXISTS session_context_json JSONB NOT NULL DEFAULT '{}'::jsonb;"
            )

        # 5. Apply full idempotent DDL & indexes
        await conn.execute(get_schema_ddl(settings.embedding_dim))
        await conn.execute(INDEX_DDL)
