"""Write-through persistence for `user_profiles`, category-agnostic `user_trait_memory` (`pgvector`), and `shopping_sessions`."""

from datetime import datetime, timezone
import json
import logging
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from backend.config import settings
from backend.db.normalizer import normalize_persian_text
from backend.db.redis_cache import (
    get_cached_json,
    profile_key,
    session_key,
    set_cached_json,
)

logger = logging.getLogger(__name__)

# Bounded in-memory fallback stores used when Redis/PostgreSQL are omitted in isolated unit tests
_MAX_MEMORY_CACHE_SIZE = 128
_MEMORY_PROFILES: dict[str, dict[str, Any]] = {}
_MEMORY_SESSIONS: dict[str, dict[str, Any]] = {}
_MEMORY_TRAITS: dict[str, list[dict[str, Any]]] = {}


def _put_bounded_memory(store: dict[str, Any], key: str, value: Any) -> None:
    if key in store:
        store.pop(key, None)
    elif len(store) >= _MAX_MEMORY_CACHE_SIZE:
        store.pop(next(iter(store)), None)
    store[key] = value

SESSION_CONTEXT_KEYS = (
    "title",
    "last_query",
    "product_search_query",
    "catalog_search_terms",
    "category_keywords",
    "is_accessory_request",
    "wants_used_or_stock",
    "is_ephemeral_or_gift",
    "custom_offer_criterion",
    "clarification_questions",
    "active_session_traits",
    "transferred_traits",
    "price_tier",
    "min_price_toman",
    "max_price_toman",
    "max_distance_km",
    "require_torob_pay",
    "rejected_offer_ids",
    "rejected_shop_ids",
    "rejected_product_ids",
    "category_price_span",
    "session_weights",
    "shown_store_features",
    "recommended_products",
    "active_weight_slots",
    "ui_turns",
)


def build_default_profile(user_id: str) -> dict[str, Any]:
    """Construct a fresh 5-criteria store profile + open-category price priors from `.env` defaults."""
    return {
        "user_id": user_id,
        "store_weights": dict(settings.default_store_weights),
        "price_percentiles": {},
        "interaction_count": 0,
    }


def build_default_session(
    session_id: str,
    user_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, Any]:
    """Construct a fresh shopping session with full durable context defaults."""
    return {
        "session_id": session_id,
        "user_id": user_id or settings.default_user_id,
        "user_lat": lat if lat is not None else settings.default_user_lat,
        "user_lng": lng if lng is not None else settings.default_user_lng,
        "active_category_name": None,
        "selected_product_id": None,
        "title": "",
        "last_query": "",
        "product_search_query": "",
        "catalog_search_terms": [],
        "category_keywords": [],
        "is_accessory_request": False,
        "wants_used_or_stock": False,
        "is_ephemeral_or_gift": False,
        "custom_offer_criterion": "",
        "clarification_questions": [],
        "active_session_traits": [],
        "transferred_traits": [],
        "price_tier": "mid",
        "min_price_toman": None,
        "max_price_toman": None,
        "max_distance_km": None,
        "require_torob_pay": False,
        "rejected_offer_ids": [],
        "rejected_shop_ids": [],
        "rejected_product_ids": [],
        "category_price_span": {},
        "session_weights": {},
        "shown_store_features": {},
        "recommended_products": [],
        "active_weight_slots": [],
        "ui_turns": [],
        "effective_weights": {},
        "hard_constraints": {
            "require_open_now": False,
            "require_installment": False,
            "require_warranty": False,
        },
        "clarification_count": 0,
        "dissatisfaction_triggered": False,
        "messages": [],
    }


async def load_user_profile(
    user_id: str,
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any]:
    """Load user's store weights & open-category price percentiles via Redis -> PostgreSQL."""
    r_key = profile_key(user_id)
    cached = await get_cached_json(redis_client, r_key)
    if isinstance(cached, dict) and "store_weights" in cached:
        cached.setdefault("price_percentiles", {})
        return cached

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT store_weights_json, price_percentiles_json, interaction_count FROM user_profiles WHERE user_id = $1",
                    user_id,
                )
                if row is not None:
                    raw_sw = (
                        json.loads(row["store_weights_json"])
                        if isinstance(row["store_weights_json"], str)
                        else dict(row["store_weights_json"] or {})
                    )
                    sw = dict(settings.default_store_weights)
                    for k in sw:
                        if k in raw_sw:
                            sw[k] = float(raw_sw[k])
                    raw_pp = (
                        json.loads(row["price_percentiles_json"])
                        if isinstance(row["price_percentiles_json"], str)
                        else dict(row["price_percentiles_json"] or {})
                    )
                    profile = {
                        "user_id": user_id,
                        "store_weights": sw,
                        "price_percentiles": raw_pp,
                        "interaction_count": int(row["interaction_count"] or 0),
                    }
                    await set_cached_json(redis_client, r_key, profile, settings.redis_profile_ttl_seconds)
                    return profile
        except Exception as exc:
            logger.warning("Failed to load user_profile for %s from PostgreSQL: %s", user_id, exc)

    if user_id in _MEMORY_PROFILES and "store_weights" in _MEMORY_PROFILES[user_id]:
        return _MEMORY_PROFILES[user_id]

    fresh = build_default_profile(user_id)
    await save_user_profile(fresh, pg_pool=pg_pool, redis_client=redis_client)
    return fresh


async def save_user_profile(
    profile: dict[str, Any],
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> None:
    """Write-through save of unconstrained `store_weights` and `price_percentiles` to Redis and PostgreSQL."""
    user_id = str(profile["user_id"])
    sw = dict(settings.default_store_weights)
    sw.update({k: float(v) for k, v in (profile.get("store_weights") or {}).items() if k in sw})
    pp = dict(profile.get("price_percentiles") or {})
    clean_profile = {
        "user_id": user_id,
        "store_weights": sw,
        "price_percentiles": pp,
        "interaction_count": int(profile.get("interaction_count", 0)),
    }
    _put_bounded_memory(_MEMORY_PROFILES, user_id, clean_profile)
    await set_cached_json(redis_client, profile_key(user_id), clean_profile, settings.redis_profile_ttl_seconds)

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, store_weights_json, price_percentiles_json, interaction_count, updated_at)
                    VALUES ($1, $2::jsonb, $3::jsonb, $4, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        store_weights_json = EXCLUDED.store_weights_json,
                        price_percentiles_json = EXCLUDED.price_percentiles_json,
                        interaction_count = EXCLUDED.interaction_count,
                        updated_at = NOW()
                    """,
                    user_id,
                    json.dumps(sw, ensure_ascii=False),
                    json.dumps(pp, ensure_ascii=False),
                    clean_profile["interaction_count"],
                )
        except Exception as exc:
            logger.warning("Failed to save user_profile for %s to PostgreSQL: %s", user_id, exc)


async def fetch_user_traits(
    pg_pool: asyncpg.Pool | None,
    user_id: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Retrieve top-N category-agnostic traits for `user_id` ordered by `(strength DESC, updated_at DESC)`."""
    top_n = limit or settings.recsys_max_stored_traits_per_user
    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT trait_id, source_category, aspect, preference, strength, hit_count
                    FROM user_trait_memory
                    WHERE user_id = $1
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT $2
                    """,
                    user_id,
                    top_n,
                )
                if rows:
                    return [
                        {
                            "trait_id": int(r["trait_id"]),
                            "source_category": str(r["source_category"] or ""),
                            "aspect": str(r["aspect"]),
                            "preference": str(r["preference"]),
                            "strength": float(r["strength"] or 0.5),
                            "hit_count": int(r["hit_count"] or 1),
                        }
                        for r in rows
                    ]
        except Exception as exc:
            logger.warning("Failed to fetch user_trait_memory for %s: %s", user_id, exc)

    mem_items = list(_MEMORY_TRAITS.get(user_id, []))
    if not mem_items:
        return []
    mem_items.sort(key=lambda it: (float(it.get("strength", 0.5)), int(it.get("trait_id", 0))), reverse=True)
    return [
        {
            "trait_id": int(it.get("trait_id", idx + 1)),
            "source_category": str(it.get("source_category") or ""),
            "aspect": str(it["aspect"]),
            "preference": str(it["preference"]),
            "strength": float(it.get("strength", 0.5)),
            "hit_count": int(it.get("hit_count", 1)),
        }
        for idx, it in enumerate(mem_items[:top_n])
    ]


async def find_closest_user_aspects_pgvector(
    pg_pool: asyncpg.Pool | None,
    user_id: str,
    aspect_embedding: list[float],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find closest existing `aspect` rows for `user_id` via `pgvector` cosine similarity."""
    if pg_pool is not None and len(aspect_embedding) == settings.embedding_dim:
        emb_literal = "[" + ",".join(f"{float(x):.6f}" for x in aspect_embedding) + "]"
        try:
            async with pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT trait_id, source_category, aspect, preference, strength, hit_count,
                           1.0 - (aspect_embedding <=> $2::vector) AS cos_sim
                    FROM user_trait_memory
                    WHERE user_id = $1 AND aspect_embedding IS NOT NULL
                    ORDER BY aspect_embedding <=> $2::vector ASC
                    LIMIT $3
                    """,
                    user_id,
                    emb_literal,
                    limit,
                )
                if rows:
                    return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("Failed to query closest user aspects for %s: %s", user_id, exc)

    mem_items = list(_MEMORY_TRAITS.get(user_id, []))
    if not mem_items:
        return []
    import numpy as np

    a_vec = np.asarray(aspect_embedding, dtype=np.float64)
    a_norm = float(np.linalg.norm(a_vec)) or 1.0
    scored: list[dict[str, Any]] = []
    for idx, it in enumerate(mem_items):
        emb = it.get("aspect_embedding") or []
        cos = 0.0
        if len(emb) == len(aspect_embedding):
            v = np.asarray(emb, dtype=np.float64)
            cos = float(np.dot(a_vec, v) / (a_norm * (float(np.linalg.norm(v)) or 1.0)))
        scored.append({**it, "trait_id": int(it.get("trait_id", idx + 1)), "cos_sim": cos})
    scored.sort(key=lambda x: x["cos_sim"], reverse=True)
    return scored[:limit]


async def upsert_user_trait_with_inertia(
    pg_pool: asyncpg.Pool | None,
    user_id: str,
    source_category: str,
    aspect: str,
    preference: str,
    aspect_embedding: list[float],
    alpha: float | None = None,
    matched_aspect_rows: list[dict[str, Any]] | None = None,
    same_preference_trait_id: int | None = None,
) -> dict[str, Any]:
    """Consolidate a user trait with repetition inertia (`strength`) and Top-K per-aspect retention (`K=2`).

    - Same preference on an existing aspect: `s <- 1 - (1 - s) * (1 - alpha)`, `hit_count += 1`.
    - Competing preference on the same aspect: rival rows decay `s <- rival_decay * s`; new row starts at `alpha`;
      only Top `recsys_max_preferences_per_aspect` (`2`) rows for that aspect are retained.
    """
    step_alpha = max(0.05, min(0.95, float(alpha if alpha is not None else settings.recsys_trait_soft_step)))
    rival_decay = float(settings.recsys_trait_rival_decay)
    max_per_aspect = max(1, int(settings.recsys_max_preferences_per_aspect))
    aspect_rows = list(matched_aspect_rows or [])
    canonical_aspect = str(aspect_rows[0]["aspect"]) if aspect_rows else aspect
    norm_pref = normalize_persian_text(preference)

    if same_preference_trait_id is None:
        for r in aspect_rows:
            if normalize_persian_text(str(r.get("preference") or "")) == norm_pref:
                same_preference_trait_id = int(r["trait_id"])
                break

    if user_id not in _MEMORY_TRAITS and len(_MEMORY_TRAITS) >= _MAX_MEMORY_CACHE_SIZE:
        _MEMORY_TRAITS.pop(next(iter(_MEMORY_TRAITS)), None)
    mem_list = _MEMORY_TRAITS.setdefault(user_id, [])
    aspect_ids = {int(r["trait_id"]) for r in aspect_rows if r.get("trait_id") is not None}
    for it in mem_list:
        if normalize_persian_text(str(it.get("aspect") or "")) == normalize_persian_text(canonical_aspect):
            aspect_ids.add(int(it["trait_id"]))
            if same_preference_trait_id is None and normalize_persian_text(str(it.get("preference") or "")) == norm_pref:
                same_preference_trait_id = int(it["trait_id"])

    target_record: dict[str, Any] | None = None
    for it in mem_list:
        tid = int(it["trait_id"])
        if same_preference_trait_id is not None and tid == int(same_preference_trait_id):
            old_s = float(it.get("strength", 0.50))
            it["strength"] = round(min(1.0, 1.0 - (1.0 - old_s) * (1.0 - step_alpha)), 4)
            it["preference"] = preference
            if source_category:
                it["source_category"] = source_category
            it["aspect_embedding"] = aspect_embedding
            it["hit_count"] = int(it.get("hit_count", 1)) + 1
            target_record = it
        elif tid in aspect_ids:
            it["strength"] = round(max(0.05, rival_decay * float(it.get("strength", 0.50))), 4)

    if target_record is None:
        next_id = max((int(x.get("trait_id", 0)) for x in mem_list), default=0) + 1
        target_record = {
            "trait_id": next_id,
            "user_id": user_id,
            "source_category": source_category,
            "aspect": canonical_aspect,
            "preference": preference,
            "aspect_embedding": aspect_embedding,
            "strength": round(step_alpha, 4),
            "hit_count": 1,
        }
        mem_list.append(target_record)
        aspect_ids.add(next_id)

    # Prune beyond Top-K (`recsys_max_preferences_per_aspect`) on this aspect in memory
    same_aspect_mem = [it for it in mem_list if int(it["trait_id"]) in aspect_ids]
    if len(same_aspect_mem) > max_per_aspect:
        same_aspect_mem.sort(
            key=lambda it: (float(it.get("strength", 0.0)), int(it["trait_id"]) == int(target_record["trait_id"])),
            reverse=True,
        )
        drop_ids = {int(it["trait_id"]) for it in same_aspect_mem[max_per_aspect:]}
        _MEMORY_TRAITS[user_id] = [it for it in mem_list if int(it["trait_id"]) not in drop_ids]

    if pg_pool is not None and len(aspect_embedding) == settings.embedding_dim:
        emb_literal = "[" + ",".join(f"{float(x):.6f}" for x in aspect_embedding) + "]"
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, store_weights_json, price_percentiles_json, interaction_count)
                    VALUES ($1, $2::jsonb, '{}'::jsonb, 0)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    user_id,
                    json.dumps(settings.default_store_weights, ensure_ascii=False),
                )
                db_aspect_ids = [int(r["trait_id"]) for r in aspect_rows if r.get("trait_id") is not None]
                if same_preference_trait_id is not None:
                    rival_ids = [tid for tid in db_aspect_ids if tid != int(same_preference_trait_id)]
                    if rival_ids:
                        await conn.execute(
                            """
                            UPDATE user_trait_memory
                            SET strength = GREATEST(0.05, strength * $1)
                            WHERE user_id = $2 AND trait_id = ANY($3::bigint[])
                            """,
                            rival_decay,
                            user_id,
                            rival_ids,
                        )
                    row = await conn.fetchrow(
                        """
                        UPDATE user_trait_memory
                        SET preference = $1,
                            source_category = CASE WHEN $2 <> '' THEN $2 ELSE source_category END,
                            aspect_embedding = $3::vector,
                            strength = LEAST(1.0, 1.0 - (1.0 - strength) * (1.0 - $4)),
                            hit_count = hit_count + 1,
                            updated_at = NOW()
                        WHERE trait_id = $5 AND user_id = $6
                        RETURNING trait_id, strength, hit_count
                        """,
                        preference,
                        source_category,
                        emb_literal,
                        step_alpha,
                        int(same_preference_trait_id),
                        user_id,
                    )
                    if row is not None:
                        target_record["trait_id"] = int(row["trait_id"])
                        target_record["strength"] = float(row["strength"])
                        target_record["hit_count"] = int(row["hit_count"])
                else:
                    if db_aspect_ids:
                        await conn.execute(
                            """
                            UPDATE user_trait_memory
                            SET strength = GREATEST(0.05, strength * $1)
                            WHERE user_id = $2 AND trait_id = ANY($3::bigint[])
                            """,
                            rival_decay,
                            user_id,
                            db_aspect_ids,
                        )
                    row_id = await conn.fetchval(
                        """
                        INSERT INTO user_trait_memory
                            (user_id, source_category, aspect, preference, aspect_embedding, strength, hit_count, updated_at)
                        VALUES ($1, $2, $3, $4, $5::vector, $6, 1, NOW())
                        RETURNING trait_id
                        """,
                        user_id,
                        source_category,
                        canonical_aspect,
                        preference,
                        emb_literal,
                        step_alpha,
                    )
                    if row_id is not None:
                        target_record["trait_id"] = int(row_id)
                        db_aspect_ids.append(int(row_id))

                # Enforce Top-K (`max_per_aspect`) retention on this aspect in PostgreSQL
                if len(db_aspect_ids) > max_per_aspect:
                    await conn.execute(
                        """
                        DELETE FROM user_trait_memory
                        WHERE user_id = $1
                          AND trait_id IN (
                              SELECT trait_id
                              FROM user_trait_memory
                              WHERE user_id = $1 AND trait_id = ANY($2::bigint[])
                              ORDER BY strength DESC, updated_at DESC
                              OFFSET $3
                          )
                        """,
                        user_id,
                        db_aspect_ids,
                        max_per_aspect,
                    )
        except Exception as exc:
            logger.warning("Failed to upsert user_trait_memory for %s: %s", user_id, exc)

    return target_record


async def load_shopping_session(
    session_id: str,
    user_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any]:
    """Load active shopping session from Redis (`< 2 ms`) with full PostgreSQL `session_context_json` fallback."""
    s_key = session_key(session_id)
    cached = await get_cached_json(redis_client, s_key)
    if isinstance(cached, dict) and "session_id" in cached:
        if lat is not None:
            cached["user_lat"] = lat
        if lng is not None:
            cached["user_lng"] = lng
        return cached

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM shopping_sessions WHERE session_id = $1",
                    session_id,
                )
                if row is not None:
                    sess = build_default_session(
                        session_id=session_id,
                        user_id=row["user_id"],
                        lat=lat if lat is not None else float(row["user_lat"]),
                        lng=lng if lng is not None else float(row["user_lng"]),
                    )
                    sess["active_category_name"] = row["active_category_name"]
                    sess["selected_product_id"] = row["selected_product_id"]
                    sess["effective_weights"] = (
                        json.loads(row["effective_weights_json"])
                        if isinstance(row["effective_weights_json"], str)
                        else dict(row["effective_weights_json"] or {})
                    )
                    sess["hard_constraints"] = (
                        json.loads(row["hard_constraints_json"])
                        if isinstance(row["hard_constraints_json"], str)
                        else dict(row["hard_constraints_json"] or {})
                    )
                    ctx_raw = row.get("session_context_json")
                    ctx = (
                        json.loads(ctx_raw)
                        if isinstance(ctx_raw, str)
                        else dict(ctx_raw or {})
                    )
                    for k in SESSION_CONTEXT_KEYS:
                        if k in ctx:
                            sess[k] = ctx[k]
                    sess["clarification_count"] = int(row["clarification_count"] or 0)
                    sess["dissatisfaction_triggered"] = bool(row["dissatisfaction_triggered"])
                    sess["messages"] = (
                        json.loads(row["messages_json"])
                        if isinstance(row["messages_json"], str)
                        else list(row["messages_json"] or [])
                    )
                    await set_cached_json(redis_client, s_key, sess, settings.redis_session_ttl_seconds)
                    return sess
        except Exception as exc:
            logger.warning("Failed to load shopping_session %s from PostgreSQL: %s", session_id, exc)

    if session_id in _MEMORY_SESSIONS:
        sess = _MEMORY_SESSIONS[session_id]
        if lat is not None:
            sess["user_lat"] = lat
        if lng is not None:
            sess["user_lng"] = lng
        return sess

    fresh = build_default_session(session_id, user_id=user_id, lat=lat, lng=lng)
    await save_shopping_session(fresh, pg_pool=pg_pool, redis_client=redis_client)
    return fresh


async def save_shopping_session(
    session: dict[str, Any],
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> None:
    """Persist shopping session (including full `session_context_json`) to Redis and PostgreSQL."""
    session_id = str(session["session_id"])
    _put_bounded_memory(_MEMORY_SESSIONS, session_id, session)
    await set_cached_json(redis_client, session_key(session_id), session, settings.redis_session_ttl_seconds)

    if pg_pool is not None:
        ctx_payload = {k: session.get(k) for k in SESSION_CONTEXT_KEYS if k in session}
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO shopping_sessions (
                        session_id, user_id, user_lat, user_lng, active_category_name,
                        selected_product_id, effective_weights_json, hard_constraints_json,
                        session_context_json, clarification_count, dissatisfaction_triggered,
                        messages_json, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10, $11, $12::jsonb, NOW())
                    ON CONFLICT (session_id) DO UPDATE SET
                        user_lat = EXCLUDED.user_lat,
                        user_lng = EXCLUDED.user_lng,
                        active_category_name = EXCLUDED.active_category_name,
                        selected_product_id = EXCLUDED.selected_product_id,
                        effective_weights_json = EXCLUDED.effective_weights_json,
                        hard_constraints_json = EXCLUDED.hard_constraints_json,
                        session_context_json = EXCLUDED.session_context_json,
                        clarification_count = EXCLUDED.clarification_count,
                        dissatisfaction_triggered = EXCLUDED.dissatisfaction_triggered,
                        messages_json = EXCLUDED.messages_json,
                        updated_at = NOW()
                    """,
                    session_id,
                    str(session.get("user_id") or settings.default_user_id),
                    float(session.get("user_lat") or settings.default_user_lat),
                    float(session.get("user_lng") or settings.default_user_lng),
                    session.get("active_category_name"),
                    str(session["selected_product_id"]) if session.get("selected_product_id") else None,
                    json.dumps(session.get("effective_weights", {}), ensure_ascii=False),
                    json.dumps(session.get("hard_constraints", {}), ensure_ascii=False),
                    json.dumps(ctx_payload, ensure_ascii=False),
                    int(session.get("clarification_count", 0)),
                    bool(session.get("dissatisfaction_triggered", False)),
                    json.dumps(session.get("messages", []), ensure_ascii=False),
                )
        except Exception as exc:
            logger.warning("Failed to save shopping_session %s to PostgreSQL: %s", session_id, exc)


def _derive_session_title(ctx: dict[str, Any], messages: list[dict[str, Any]], active_cat: str | None) -> str:
    title = str(ctx.get("title") or "").strip()
    if title:
        return title[:72]
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "user" and str(m.get("text") or "").strip():
            return str(m["text"]).strip()[:72]
    if str(ctx.get("last_query") or "").strip():
        return str(ctx["last_query"]).strip()[:72]
    return str(active_cat or "گفتگوی خرید حضوری")[:72]


async def list_user_shopping_sessions(
    user_id: str,
    pg_pool: asyncpg.Pool | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return non-empty saved shopping sessions for `user_id` sorted by `updated_at DESC`."""
    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT session_id, active_category_name, session_context_json, messages_json, updated_at
                    FROM shopping_sessions
                    WHERE user_id = $1
                      AND (
                          jsonb_array_length(COALESCE(messages_json, '[]'::jsonb)) > 0
                          OR jsonb_array_length(COALESCE(session_context_json->'ui_turns', '[]'::jsonb)) > 0
                      )
                    ORDER BY updated_at DESC
                    LIMIT $2
                    """,
                    user_id,
                    limit,
                )
                results: list[dict[str, Any]] = []
                for r in rows:
                    ctx = (
                        json.loads(r["session_context_json"])
                        if isinstance(r["session_context_json"], str)
                        else dict(r["session_context_json"] or {})
                    )
                    msgs = (
                        json.loads(r["messages_json"])
                        if isinstance(r["messages_json"], str)
                        else list(r["messages_json"] or [])
                    )
                    ui_turns = list(ctx.get("ui_turns") or [])
                    turn_count = max(
                        1,
                        sum(1 for t in ui_turns if isinstance(t, dict) and t.get("sender") == "user")
                        or sum(1 for m in msgs if isinstance(m, dict) and m.get("role") == "user"),
                    )
                    upd = r["updated_at"].astimezone(timezone.utc).isoformat() if r["updated_at"] else datetime.now(timezone.utc).isoformat()
                    results.append(
                        {
                            "session_id": str(r["session_id"]),
                            "title": _derive_session_title(ctx, msgs, r["active_category_name"]),
                            "active_category_name": r["active_category_name"],
                            "updated_at": upd,
                            "turn_count": turn_count,
                        }
                    )
                return results
        except Exception as exc:
            logger.warning("Failed to list shopping_sessions for %s: %s", user_id, exc)

    items: list[dict[str, Any]] = []
    for sid, sess in list(_MEMORY_SESSIONS.items()):
        if str(sess.get("user_id")) != user_id:
            continue
        msgs = list(sess.get("messages") or [])
        ui_turns = list(sess.get("ui_turns") or [])
        if not msgs and not ui_turns:
            continue
        items.append(
            {
                "session_id": sid,
                "title": _derive_session_title(sess, msgs, sess.get("active_category_name")),
                "active_category_name": sess.get("active_category_name"),
                "updated_at": str(sess.get("updated_at") or datetime.now(timezone.utc).isoformat()),
                "turn_count": max(1, sum(1 for t in ui_turns if isinstance(t, dict) and t.get("sender") == "user")),
            }
        )
    items.sort(key=lambda x: str(x["updated_at"]), reverse=True)
    return items[:limit]


async def get_user_shopping_session_detail(
    session_id: str,
    user_id: str,
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any] | None:
    """Fetch full durable UI conversation state for `(session_id, user_id)` without creating empty rows."""
    sess: dict[str, Any] | None = None
    updated_iso = datetime.now(timezone.utc).isoformat()

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM shopping_sessions WHERE session_id = $1 AND user_id = $2",
                    session_id,
                    user_id,
                )
                if row is not None:
                    updated_iso = (
                        row["updated_at"].astimezone(timezone.utc).isoformat()
                        if row["updated_at"]
                        else updated_iso
                    )
        except Exception as exc:
            logger.warning("Failed to fetch shopping_session detail %s: %s", session_id, exc)
            row = None
        if row is not None:
            sess = await load_shopping_session(
                session_id=session_id,
                user_id=user_id,
                pg_pool=pg_pool,
                redis_client=redis_client,
            )
    elif session_id in _MEMORY_SESSIONS and str(_MEMORY_SESSIONS[session_id].get("user_id")) == user_id:
        sess = _MEMORY_SESSIONS[session_id]

    if sess is None or str(sess.get("user_id")) != user_id:
        return None

    msgs = list(sess.get("messages") or [])
    ui_turns = [t for t in list(sess.get("ui_turns") or []) if isinstance(t, dict)]
    if not ui_turns and msgs:
        for idx, m in enumerate(msgs):
            if not isinstance(m, dict) or not str(m.get("text") or "").strip():
                continue
            role = "user" if m.get("role") == "user" else "assistant"
            ui_turns.append(
                {
                    "id": f"hist_{idx}",
                    "sender": role,
                    "text": str(m["text"]),
                    "created_at": updated_iso,
                }
            )

    return {
        "session_id": session_id,
        "user_id": user_id,
        "title": _derive_session_title(sess, msgs, sess.get("active_category_name")),
        "active_category_name": sess.get("active_category_name"),
        "selected_product_id": sess.get("selected_product_id"),
        "updated_at": updated_iso,
        "require_torob_pay": bool(sess.get("require_torob_pay") or False),
        "hard_constraints": dict(sess.get("hard_constraints") or {}),
        "active_weights": list(sess.get("active_weight_slots") or []),
        "ui_turns": ui_turns,
    }


async def delete_user_shopping_session(
    session_id: str,
    user_id: str,
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> bool:
    """Delete a user's shopping session from memory, Redis, and PostgreSQL."""
    deleted = False
    existing_mem = _MEMORY_SESSIONS.get(session_id)
    if existing_mem and str(existing_mem.get("user_id")) == user_id:
        _MEMORY_SESSIONS.pop(session_id, None)
        deleted = True

    if redis_client is not None:
        try:
            await redis_client.delete(session_key(session_id))
        except Exception:
            pass

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                tag = await conn.execute(
                    "DELETE FROM shopping_sessions WHERE session_id = $1 AND user_id = $2",
                    session_id,
                    user_id,
                )
                if tag and not tag.endswith(" 0"):
                    deleted = True
        except Exception as exc:
            logger.warning("Failed to delete shopping_session %s from PostgreSQL: %s", session_id, exc)
    return deleted
