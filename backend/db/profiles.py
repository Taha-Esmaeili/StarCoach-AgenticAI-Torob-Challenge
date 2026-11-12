"""Write-through persistence for `user_profiles`, `user_dynamic_slots` (`pgvector`), and `shopping_sessions`."""

import json
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from backend.config import settings
from backend.db.redis_cache import (
    get_cached_json,
    profile_key,
    session_key,
    set_cached_json,
)

# In-memory fallback store used when Redis/PostgreSQL are not passed in isolated unit tests
_MEMORY_PROFILES: dict[str, dict[str, Any]] = {}
_MEMORY_SESSIONS: dict[str, dict[str, Any]] = {}
_MEMORY_TRAITS: dict[tuple[str, str], list[dict[str, Any]]] = {}


def build_default_profile(user_id: str) -> dict[str, Any]:
    """Construct a fresh 15-slot unconstrained user profile from `.env` defaults."""
    return {
        "user_id": user_id,
        "base_weights": dict(settings.default_base_weights),
        "persona_weights": dict(settings.default_persona_weights),
        "dynamic_slots": [],
        "interaction_count": 0,
    }


def build_default_session(
    session_id: str,
    user_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, Any]:
    """Construct a fresh shopping session with anti-fatigue `clarification_count = 0`."""
    return {
        "session_id": session_id,
        "user_id": user_id or settings.default_user_id,
        "user_lat": lat if lat is not None else settings.default_user_lat,
        "user_lng": lng if lng is not None else settings.default_user_lng,
        "active_category_name": None,
        "selected_product_id": None,
        "last_query": "",
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
    """Load user's 15-slot profile via Redis read-through cache -> PostgreSQL (`user_profiles` + `user_dynamic_slots`)."""
    r_key = profile_key(user_id)
    cached = await get_cached_json(redis_client, r_key)
    if isinstance(cached, dict) and "base_weights" in cached:
        return cached

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT base_weights_json, persona_weights_json, interaction_count FROM user_profiles WHERE user_id = $1",
                    user_id,
                )
                if row is not None:
                    dyn_rows = await conn.fetch(
                        """
                        SELECT slot_id, feature_key, label_fa, category_name, weight, confidence, session_hits
                        FROM user_dynamic_slots
                        WHERE user_id = $1
                        ORDER BY slot_id ASC
                        """,
                        user_id,
                    )
                    profile = {
                        "user_id": user_id,
                        "base_weights": json.loads(row["base_weights_json"])
                        if isinstance(row["base_weights_json"], str)
                        else dict(row["base_weights_json"]),
                        "persona_weights": json.loads(row["persona_weights_json"])
                        if isinstance(row["persona_weights_json"], str)
                        else dict(row["persona_weights_json"]),
                        "dynamic_slots": [dict(r) for r in dyn_rows],
                        "interaction_count": int(row["interaction_count"] or 0),
                    }
                    await set_cached_json(redis_client, r_key, profile, settings.redis_profile_ttl_seconds)
                    return profile
        except Exception:
            pass

    if user_id in _MEMORY_PROFILES:
        return _MEMORY_PROFILES[user_id]

    fresh = build_default_profile(user_id)
    await save_user_profile(fresh, pg_pool=pg_pool, redis_client=redis_client)
    return fresh


async def save_user_profile(
    profile: dict[str, Any],
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> None:
    """Write-through save of unconstrained $[0,1]^{15}$ profile to Redis and PostgreSQL."""
    user_id = str(profile["user_id"])
    _MEMORY_PROFILES[user_id] = profile
    await set_cached_json(redis_client, profile_key(user_id), profile, settings.redis_profile_ttl_seconds)

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, base_weights_json, persona_weights_json, interaction_count, updated_at)
                    VALUES ($1, $2::jsonb, $3::jsonb, $4, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        base_weights_json = EXCLUDED.base_weights_json,
                        persona_weights_json = EXCLUDED.persona_weights_json,
                        interaction_count = EXCLUDED.interaction_count,
                        updated_at = NOW()
                    """,
                    user_id,
                    json.dumps(profile.get("base_weights", settings.default_base_weights), ensure_ascii=False),
                    json.dumps(profile.get("persona_weights", settings.default_persona_weights), ensure_ascii=False),
                    int(profile.get("interaction_count", 0)),
                )
                for slot in profile.get("dynamic_slots", []):
                    emb = slot.get("embedding")
                    emb_literal = (
                        "[" + ",".join(f"{float(x):.6f}" for x in emb) + "]"
                        if isinstance(emb, list) and len(emb) == settings.embedding_dim
                        else None
                    )
                    if emb_literal:
                        await conn.execute(
                            """
                            INSERT INTO user_dynamic_slots
                                (user_id, slot_id, feature_key, label_fa, category_name, weight, confidence, embedding, session_hits, updated_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, NOW())
                            ON CONFLICT (user_id, slot_id) DO UPDATE SET
                                feature_key = EXCLUDED.feature_key,
                                label_fa = EXCLUDED.label_fa,
                                category_name = EXCLUDED.category_name,
                                weight = EXCLUDED.weight,
                                confidence = EXCLUDED.confidence,
                                embedding = EXCLUDED.embedding,
                                session_hits = EXCLUDED.session_hits,
                                updated_at = NOW()
                            """,
                            user_id,
                            int(slot["slot_id"]),
                            str(slot["feature_key"]),
                            str(slot["label_fa"]),
                            slot.get("category_name"),
                            float(slot.get("weight", 0.5)),
                            float(slot.get("confidence", 0.5)),
                            emb_literal,
                            int(slot.get("session_hits", 1)),
                        )
                    else:
                        await conn.execute(
                            """
                            INSERT INTO user_dynamic_slots
                                (user_id, slot_id, feature_key, label_fa, category_name, weight, confidence, session_hits, updated_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                            ON CONFLICT (user_id, slot_id) DO UPDATE SET
                                feature_key = EXCLUDED.feature_key,
                                label_fa = EXCLUDED.label_fa,
                                category_name = EXCLUDED.category_name,
                                weight = EXCLUDED.weight,
                                confidence = EXCLUDED.confidence,
                                session_hits = EXCLUDED.session_hits,
                                updated_at = NOW()
                            """,
                            user_id,
                            int(slot["slot_id"]),
                            str(slot["feature_key"]),
                            str(slot["label_fa"]),
                            slot.get("category_name"),
                            float(slot.get("weight", 0.5)),
                            float(slot.get("confidence", 0.5)),
                            int(slot.get("session_hits", 1)),
                        )
        except Exception:
            pass


async def find_closest_dynamic_slot_pgvector(
    pg_pool: asyncpg.Pool | None,
    user_id: str,
    embedding: list[float],
) -> tuple[int | None, float]:
    """Use PostgreSQL `pgvector` `<=>` cosine distance operator to find the closest dynamic slot."""
    if pg_pool is None or len(embedding) != settings.embedding_dim:
        return None, 0.0
    emb_literal = "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"
    try:
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT slot_id, 1.0 - (embedding <=> $1::vector) AS cos_sim
                FROM user_dynamic_slots
                WHERE user_id = $2 AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector ASC
                LIMIT 1
                """,
                emb_literal,
                user_id,
            )
            if row is not None and row["cos_sim"] is not None:
                return int(row["slot_id"]), float(row["cos_sim"])
    except Exception:
        pass
    return None, 0.0


async def fetch_domain_traits_pgvector(
    pg_pool: asyncpg.Pool | None,
    user_id: str,
    domain: str,
    query_embedding: list[float] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Retrieve top-K specialized traits for `(user_id, domain)` in < 2ms via `pgvector` or memory store."""
    top_k = limit or settings.recsys_max_traits_per_query
    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                if query_embedding and len(query_embedding) == settings.embedding_dim:
                    emb_literal = "[" + ",".join(f"{float(x):.6f}" for x in query_embedding) + "]"
                    rows = await conn.fetch(
                        """
                        SELECT trait_id, domain, aspect, preference, hit_count,
                               1.0 - (aspect_embedding <=> $3::vector) AS cos_sim
                        FROM user_trait_memory
                        WHERE user_id = $1 AND domain = $2
                        ORDER BY aspect_embedding <=> $3::vector ASC, updated_at DESC
                        LIMIT $4
                        """,
                        user_id,
                        domain,
                        emb_literal,
                        top_k,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT trait_id, domain, aspect, preference, hit_count, 1.0 AS cos_sim
                        FROM user_trait_memory
                        WHERE user_id = $1 AND domain = $2
                        ORDER BY hit_count DESC, updated_at DESC
                        LIMIT $3
                        """,
                        user_id,
                        domain,
                        top_k,
                    )
                if rows:
                    return [dict(r) for r in rows]
        except Exception:
            pass

    mem_items = list(_MEMORY_TRAITS.get((user_id, domain), []))
    if not mem_items:
        return []
    if query_embedding:
        import numpy as np

        q_vec = np.asarray(query_embedding, dtype=np.float64)
        q_norm = float(np.linalg.norm(q_vec)) or 1.0

        def _score_item(item: dict[str, Any]) -> float:
            emb = item.get("aspect_embedding")
            if not emb or len(emb) != len(query_embedding):
                return 0.0
            v = np.asarray(emb, dtype=np.float64)
            denom = q_norm * (float(np.linalg.norm(v)) or 1.0)
            return float(np.dot(q_vec, v) / denom)

        mem_items.sort(key=_score_item, reverse=True)
    return [
        {
            "trait_id": it.get("trait_id", idx + 1),
            "domain": it["domain"],
            "aspect": it["aspect"],
            "preference": it["preference"],
            "hit_count": int(it.get("hit_count", 1)),
        }
        for idx, it in enumerate(mem_items[:top_k])
    ]


async def find_closest_domain_aspects_pgvector(
    pg_pool: asyncpg.Pool | None,
    user_id: str,
    domain: str,
    aspect_embedding: list[float],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Find closest existing `aspect` rows within `(user_id, domain)` for deduplication / polarity update."""
    if pg_pool is not None and len(aspect_embedding) == settings.embedding_dim:
        emb_literal = "[" + ",".join(f"{float(x):.6f}" for x in aspect_embedding) + "]"
        try:
            async with pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT trait_id, domain, aspect, preference, hit_count,
                           1.0 - (aspect_embedding <=> $3::vector) AS cos_sim
                    FROM user_trait_memory
                    WHERE user_id = $1 AND domain = $2 AND aspect_embedding IS NOT NULL
                    ORDER BY aspect_embedding <=> $3::vector ASC
                    LIMIT $4
                    """,
                    user_id,
                    domain,
                    emb_literal,
                    limit,
                )
                if rows:
                    return [dict(r) for r in rows]
        except Exception:
            pass

    mem_items = list(_MEMORY_TRAITS.get((user_id, domain), []))
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
        scored.append({**it, "trait_id": it.get("trait_id", idx + 1), "cos_sim": cos})
    scored.sort(key=lambda x: x["cos_sim"], reverse=True)
    return scored[:limit]


async def save_or_update_domain_trait(
    pg_pool: asyncpg.Pool | None,
    user_id: str,
    domain: str,
    aspect: str,
    preference: str,
    aspect_embedding: list[float],
    matched_trait_id: int | None = None,
) -> dict[str, Any]:
    """Insert a new `(user_id, domain, aspect, preference)` trait or update `preference` in-place on `matched_trait_id`."""
    mem_list = _MEMORY_TRAITS.setdefault((user_id, domain), [])
    updated_record: dict[str, Any] | None = None

    if matched_trait_id is not None:
        for item in mem_list:
            if int(item.get("trait_id", -1)) == int(matched_trait_id) or item.get("aspect") == aspect:
                item["preference"] = preference
                item["aspect_embedding"] = aspect_embedding
                item["hit_count"] = int(item.get("hit_count", 1)) + 1
                updated_record = item
                break

    if updated_record is None:
        new_id = len(mem_list) + 1
        updated_record = {
            "trait_id": new_id,
            "user_id": user_id,
            "domain": domain,
            "aspect": aspect,
            "preference": preference,
            "aspect_embedding": aspect_embedding,
            "hit_count": 1,
        }
        mem_list.append(updated_record)

    if pg_pool is not None and len(aspect_embedding) == settings.embedding_dim:
        emb_literal = "[" + ",".join(f"{float(x):.6f}" for x in aspect_embedding) + "]"
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, base_weights_json, persona_weights_json, interaction_count)
                    VALUES ($1, $2::jsonb, $3::jsonb, 0)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    user_id,
                    json.dumps(settings.default_base_weights, ensure_ascii=False),
                    json.dumps(settings.default_persona_weights, ensure_ascii=False),
                )
                if matched_trait_id is not None:
                    await conn.execute(
                        """
                        UPDATE user_trait_memory
                        SET preference = $1,
                            aspect_embedding = $2::vector,
                            hit_count = hit_count + 1,
                            updated_at = NOW()
                        WHERE trait_id = $3 AND user_id = $4 AND domain = $5
                        """,
                        preference,
                        emb_literal,
                        int(matched_trait_id),
                        user_id,
                        domain,
                    )
                else:
                    row_id = await conn.fetchval(
                        """
                        INSERT INTO user_trait_memory (user_id, domain, aspect, preference, aspect_embedding, hit_count, updated_at)
                        VALUES ($1, $2, $3, $4, $5::vector, 1, NOW())
                        RETURNING trait_id
                        """,
                        user_id,
                        domain,
                        aspect,
                        preference,
                        emb_literal,
                    )
                    if row_id is not None:
                        updated_record["trait_id"] = int(row_id)
        except Exception:
            pass

    return updated_record


async def load_shopping_session(
    session_id: str,
    user_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    pg_pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any]:
    """Load active shopping session from Redis (`< 2 ms`) with PostgreSQL fallback."""
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
                    sess = {
                        "session_id": session_id,
                        "user_id": row["user_id"],
                        "user_lat": lat if lat is not None else float(row["user_lat"]),
                        "user_lng": lng if lng is not None else float(row["user_lng"]),
                        "active_category_name": row["active_category_name"],
                        "selected_product_id": row["selected_product_id"],
                        "last_query": "",
                        "effective_weights": json.loads(row["effective_weights_json"])
                        if isinstance(row["effective_weights_json"], str)
                        else dict(row["effective_weights_json"]),
                        "hard_constraints": json.loads(row["hard_constraints_json"])
                        if isinstance(row["hard_constraints_json"], str)
                        else dict(row["hard_constraints_json"]),
                        "clarification_count": int(row["clarification_count"] or 0),
                        "dissatisfaction_triggered": bool(row["dissatisfaction_triggered"]),
                        "messages": json.loads(row["messages_json"])
                        if isinstance(row["messages_json"], str)
                        else list(row["messages_json"]),
                    }
                    await set_cached_json(redis_client, s_key, sess, settings.redis_session_ttl_seconds)
                    return sess
        except Exception:
            pass

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
    """Persist shopping session to Redis (`TTL = REDIS_SESSION_TTL_SECONDS`) and PostgreSQL."""
    session_id = str(session["session_id"])
    _MEMORY_SESSIONS[session_id] = session
    await set_cached_json(redis_client, session_key(session_id), session, settings.redis_session_ttl_seconds)

    if pg_pool is not None:
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO shopping_sessions (
                        session_id, user_id, user_lat, user_lng, active_category_name,
                        selected_product_id, effective_weights_json, hard_constraints_json,
                        clarification_count, dissatisfaction_triggered, messages_json, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11::jsonb, NOW())
                    ON CONFLICT (session_id) DO UPDATE SET
                        user_lat = EXCLUDED.user_lat,
                        user_lng = EXCLUDED.user_lng,
                        active_category_name = EXCLUDED.active_category_name,
                        selected_product_id = EXCLUDED.selected_product_id,
                        effective_weights_json = EXCLUDED.effective_weights_json,
                        hard_constraints_json = EXCLUDED.hard_constraints_json,
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
                    int(session.get("clarification_count", 0)),
                    bool(session.get("dissatisfaction_triggered", False)),
                    json.dumps(session.get("messages", []), ensure_ascii=False),
                )
        except Exception:
            pass
