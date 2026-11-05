"""PostgreSQL + pgvector + pg_trgm schema DDL and connection pool helpers."""

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
    embedding vector({dim}),
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
    base_weights_json JSONB NOT NULL,
    persona_weights_json JSONB NOT NULL,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_dynamic_slots (
    user_id TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    slot_id INTEGER NOT NULL,
    feature_key TEXT NOT NULL,
    label_fa TEXT NOT NULL,
    category_name TEXT,
    weight DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    embedding vector({dim}),
    session_hits INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, slot_id)
);

CREATE TABLE IF NOT EXISTS shopping_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_lat DOUBLE PRECISION NOT NULL,
    user_lng DOUBLE PRECISION NOT NULL,
    active_category_name TEXT,
    selected_product_id TEXT,
    effective_weights_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    hard_constraints_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
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
CREATE INDEX IF NOT EXISTS idx_products_category ON products (category_name);
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
    """Apply PostgreSQL + pgvector + pg_trgm schema DDL."""
    async with pool.acquire() as conn:
        await conn.execute(get_schema_ddl(settings.embedding_dim))
