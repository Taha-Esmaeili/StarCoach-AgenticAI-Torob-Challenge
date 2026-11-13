"""Sub-second PostgreSQL (`pg_trgm` + `pgvector` + Haversine) & Redis cached queries for products and stores.

Enforces strict separation of `offers.csv` (verified stocked products) vs.
`shops.category_names` (labeled category fallback when 0 direct offers exist).
"""

import json
import math
import re
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from backend.config import settings
from backend.db.normalizer import (
    evaluate_weekly_hours,
    format_freshness_badge,
    normalize_persian_text,
)
from backend.db.redis_cache import get_cached_json, query_cache_key, set_cached_json

# Generic Persian grammatical particles only (never product or intent keywords)
_PARTICLES_FA = {
    "یه",
    "یک",
    "من",
    "می",
    "خوام",
    "خواهم",
    "میخوام",
    "میخواهم",
    "بخرم",
    "خرید",
    "حضوری",
    "برای",
    "با",
    "در",
    "از",
    "تا",
    "رو",
    "را",
    "که",
    "یا",
    "هم",
}

_ACCESSORY_CATEGORY_REGEX = (
    r"(لوازم جانبی|قطعات|باتری|کیف و کاور|محافظ صفحه|گلس|شارژر|کابل و مبدل|پایه نگهدارنده|تاچ و ال سی دی|فلت و برد|ابزار تعمیر)"
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two coordinates in Tehran."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def estimate_travel_minutes(distance_km: float) -> tuple[int, int]:
    """Estimate `(driving_minutes, walking_minutes)` in Tehran urban traffic."""
    driving_mins = max(2, int(round(distance_km * 3.2 + 2.0)))
    walking_mins = max(2, int(round(distance_km * 12.5)))
    return driving_mins, walking_mins


def extract_search_tokens(query: str) -> list[str]:
    """Extract normalized search tokens without grammatical particles."""
    norm = normalize_persian_text(query)
    tokens = [t for t in norm.split() if len(t) >= 2 and t not in _PARTICLES_FA and not t.isdigit()]
    return tokens[:6]


def rerank_products_with_domain_traits(
    raw_products: list[dict[str, Any]],
    domain_traits: list[dict[str, Any]] | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    """Annotate candidate products with matched domain traits (`user_trait_memory`) for UI card display.

    Actual candidate scoring and ranking is performed by `score_candidate_products_with_decision_model` (`gemini-decision-1`).
    """
    if not raw_products:
        return []
    traits = domain_traits or []
    annotated: list[dict[str, Any]] = []
    for prod in raw_products:
        item = dict(prod)
        specs_dict = item.get("specs") or {}
        blob = normalize_persian_text(
            f"{item.get('title', '')} {item.get('english_title', '')} "
            + " ".join(f"{k} {v}" for k, v in specs_dict.items())
        )
        matched_prefs: list[str] = []
        for t in traits:
            pref = str(t.get("preference") or "").strip()
            aspect = str(t.get("aspect") or "").strip()
            pref_tokens = [tok for tok in normalize_persian_text(pref).split() if len(tok) >= 2]
            aspect_tokens = [tok for tok in normalize_persian_text(aspect).split() if len(tok) >= 2]
            if any(tok in blob for tok in pref_tokens) or any(tok in blob for tok in aspect_tokens):
                matched_prefs.append(pref)
        if not matched_prefs and traits:
            matched_prefs.append(str(traits[0].get("preference") or "").strip())
        item["matched_traits"] = [m for m in matched_prefs if m][:2]
        annotated.append(item)
    return annotated


async def fetch_candidate_categories(
    pg_pool: asyncpg.Pool | None,
    query: str,
    limit: int = 10,
) -> list[str]:
    """Retrieve top candidate `category_name`s from PostgreSQL matching any token in `query` (`< 5 ms`).

    These candidate categories are passed directly to `gemini-decision-1` (`choice`) so the Decision Model
    selects the exact product category without any hardcoded category rules.
    """
    if pg_pool is None:
        return []
    tokens = extract_search_tokens(query)
    if not tokens:
        return []
    sql = """
        WITH tok_cats AS (
            SELECT
                tok,
                category_name,
                word_similarity(tok, category_name) AS w_sim,
                SUM(offer_count) AS total_offers,
                ROW_NUMBER() OVER (
                    PARTITION BY tok
                    ORDER BY ROUND(word_similarity(tok, category_name)::numeric, 1) DESC, SUM(offer_count) DESC
                ) AS rn
            FROM products
            CROSS JOIN unnest($1::text[]) AS tok
            WHERE offer_count > 0
              AND min_price_toman > 0
              AND word_similarity(tok, category_name) >= 0.45
            GROUP BY tok, category_name
        ),
        title_cats AS (
            SELECT
                category_name,
                0.85 AS w_sim,
                SUM(offer_count) AS total_offers
            FROM products
            CROSS JOIN unnest($1::text[]) AS tok
            WHERE offer_count > 0
              AND min_price_toman > 0
              AND normalized_name LIKE '%' || tok || '%'
            GROUP BY category_name
            ORDER BY SUM(offer_count) DESC
            LIMIT 4
        ),
        combined AS (
            SELECT category_name, w_sim, total_offers FROM tok_cats WHERE rn <= 3
            UNION ALL
            SELECT category_name, w_sim, total_offers FROM title_cats
        )
        SELECT category_name, MAX(w_sim) AS sim, MAX(total_offers) AS offers
        FROM combined
        GROUP BY category_name
        ORDER BY sim DESC, offers DESC
        LIMIT $2
    """
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(sql, tokens, limit)
    return [str(r["category_name"]) for r in rows if r["category_name"]]


async def _resolve_dynamic_categories_sql(
    conn: asyncpg.Connection,
    norm_query: str,
    category_keywords: list[str] | None = None,
    is_accessory_request: bool = False,
) -> list[str]:
    """Dynamically resolve the best matching `category_name`s in `products`."""
    probe_terms = [
        normalize_persian_text(k)
        for k in (category_keywords or [])
        if k and len(normalize_persian_text(k)) >= 2
    ]
    if norm_query and norm_query not in probe_terms:
        probe_terms.append(norm_query)
    if not probe_terms:
        return []

    # 1. Exact category match if `gemini-decision-1` selected an exact category_name from the database
    if category_keywords:
        exact_rows = await conn.fetch(
            """
            SELECT DISTINCT category_name
            FROM products
            WHERE category_name = ANY($1::text[])
              AND offer_count > 0
            LIMIT 1
            """,
            category_keywords,
        )
        if exact_rows:
            return [str(exact_rows[0]["category_name"])]

    accessory_filter = (
        ""
        if is_accessory_request
        else f"AND NOT (category_name ~* '{_ACCESSORY_CATEGORY_REGEX}')"
    )
    sql = f"""
        SELECT
            category_name,
            MAX(similarity(kw, category_name)) AS cat_sim,
            SUM(offer_count) AS total_offers
        FROM products
        CROSS JOIN unnest($1::text[]) AS kw
        WHERE offer_count > 0
          AND min_price_toman > 0
          AND word_similarity(kw, category_name) >= 0.45
          {accessory_filter}
        GROUP BY category_name
        ORDER BY MAX(similarity(kw, category_name)) DESC, total_offers DESC
        LIMIT 1
    """
    rows = await conn.fetch(sql, probe_terms)
    if not rows:
        return []
    return [str(rows[0]["category_name"])]


async def search_products(
    pg_pool: asyncpg.Pool,
    query: str,
    max_price_toman: int | None = None,
    limit: int = 6,
    query_embedding: list[float] | None = None,
    redis_client: aioredis.Redis | None = None,
    min_price_toman: int | None = None,
    price_tier: str = "mid",
    category_keywords: list[str] | None = None,
    is_accessory_request: bool = False,
) -> list[dict[str, Any]]:
    """Search stocked products via dynamic SQL category resolution + `price_tier` from `gemini-decision-1`."""
    raw_norm = normalize_persian_text(query)
    tokens = extract_search_tokens(raw_norm)
    norm_q = " ".join(tokens) if tokens else raw_norm
    norm_cat_kw = [normalize_persian_text(k) for k in (category_keywords or []) if k]

    cache_key = query_cache_key(
        "products_v6",
        {
            "q": norm_q,
            "cat_kw": norm_cat_kw,
            "acc": is_accessory_request,
            "tier": price_tier,
            "min_p": min_price_toman,
            "max_p": max_price_toman,
            "limit": limit,
        },
    )
    cached = await get_cached_json(redis_client, cache_key)
    if isinstance(cached, list) and cached:
        return cached

    if price_tier == "budget":
        order_clause = "min_price_toman ASC, offer_count DESC"
    elif price_tier == "flagship":
        order_clause = "min_price_toman DESC, offer_count DESC"
    elif min_price_toman is not None and min_price_toman > 0:
        order_clause = "offer_count DESC, min_price_toman DESC"
    else:
        order_clause = "offer_count DESC, min_price_toman ASC"

    fetch_limit = max(limit * 2, 12)
    accessory_guard = (
        ""
        if is_accessory_request
        else f"AND NOT (category_name ~* '{_ACCESSORY_CATEGORY_REGEX}')"
    )

    async with pg_pool.acquire() as conn:
        rows: list[Any] = []
        matched_cats = await _resolve_dynamic_categories_sql(
            conn,
            norm_query=norm_q,
            category_keywords=norm_cat_kw,
            is_accessory_request=is_accessory_request,
        )

        # 1. Search inside dynamically matched categories first
        if matched_cats:
            cat_word_set = {
                w
                for c in matched_cats
                for w in normalize_persian_text(c).split()
                if len(w) >= 2
            } | {
                w
                for kw in norm_cat_kw
                for w in kw.split()
                if len(w) >= 2
            }
            specific_tokens = [t for t in tokens if t not in cat_word_set]

            params: list[Any] = [norm_q, matched_cats]
            token_clause = ""
            if specific_tokens:
                like_parts = []
                for t in specific_tokens[:3]:
                    params.append(f"%{t}%")
                    like_parts.append(f"normalized_name LIKE ${len(params)}")
                token_clause = f" AND ({' AND '.join(like_parts)})"

            price_clause = ""
            if min_price_toman is not None and min_price_toman > 0:
                params.append(min_price_toman)
                price_clause += f" AND min_price_toman >= ${len(params)}"
            if max_price_toman is not None and max_price_toman > 0:
                params.append(max_price_toman)
                price_clause += f" AND min_price_toman <= ${len(params)}"
            params.append(fetch_limit)

            sql_cat = f"""
                SELECT
                    product_id, persian_title, model_name, category_name, brand_name,
                    image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                    GREATEST(word_similarity($1, normalized_name), 0.72) AS trgm_sim
                FROM products
                WHERE offer_count > 0
                  AND min_price_toman > 0
                  AND persian_title NOT LIKE '%حذف%'
                  AND category_name = ANY($2::text[])
                  {token_clause}
                  {price_clause}
                ORDER BY {order_clause}
                LIMIT ${len(params)}
            """
            rows = await conn.fetch(sql_cat, *params)

            # Relax specific_tokens / min_price inside the matched categories if strict match yielded 0 rows
            if not rows:
                params_relaxed: list[Any] = [norm_q, matched_cats]
                price_clause_rel = ""
                if max_price_toman is not None and max_price_toman > 0:
                    params_relaxed.append(max_price_toman)
                    price_clause_rel = f" AND min_price_toman <= ${len(params_relaxed)}"
                params_relaxed.append(fetch_limit)
                sql_cat_rel = f"""
                    SELECT
                        product_id, persian_title, model_name, category_name, brand_name,
                        image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                        GREATEST(word_similarity($1, normalized_name), 0.70) AS trgm_sim
                    FROM products
                    WHERE offer_count > 0
                      AND min_price_toman > 0
                      AND persian_title NOT LIKE '%حذف%'
                      AND category_name = ANY($2::text[])
                      {price_clause_rel}
                    ORDER BY {order_clause}
                    LIMIT ${len(params_relaxed)}
                """
                rows = await conn.fetch(sql_cat_rel, *params_relaxed)

        # 2. General token search using `word_similarity` + accessory guard
        if not rows and tokens:
            like_patterns = [f"%{t}%" for t in tokens[:4]]
            where_parts = [f"normalized_name LIKE ${i + 2}" for i in range(len(like_patterns))]
            params = [norm_q, *like_patterns]
            price_clause = ""
            if min_price_toman is not None and min_price_toman > 0:
                params.append(min_price_toman)
                price_clause += f" AND min_price_toman >= ${len(params)}"
            if max_price_toman is not None and max_price_toman > 0:
                params.append(max_price_toman)
                price_clause += f" AND min_price_toman <= ${len(params)}"
            params.append(fetch_limit)

            sql = f"""
                SELECT
                    product_id, persian_title, model_name, category_name, brand_name,
                    image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                    word_similarity($1, normalized_name) AS trgm_sim
                FROM products
                WHERE offer_count > 0
                  AND min_price_toman > 0
                  AND persian_title NOT LIKE '%حذف%'
                  {accessory_guard}
                  AND ({' AND '.join(where_parts)})
                  {price_clause}
                ORDER BY {order_clause}
                LIMIT ${len(params)}
            """
            rows = await conn.fetch(sql, *params)

            # Broaden to OR matching if strict AND returned fewer than 2 products
            if len(rows) < 2 and len(like_patterns) > 1:
                sql_or = f"""
                    SELECT
                        product_id, persian_title, model_name, category_name, brand_name,
                        image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                        word_similarity($1, normalized_name) AS trgm_sim
                    FROM products
                    WHERE offer_count > 0
                      AND min_price_toman > 0
                      AND persian_title NOT LIKE '%حذف%'
                      {accessory_guard}
                      AND ({' OR '.join(where_parts)})
                      {price_clause}
                    ORDER BY trgm_sim DESC, {order_clause}
                    LIMIT ${len(params)}
                """
                rows = await conn.fetch(sql_or, *params)

        # Fallback to top-offered products if query was purely generic (e.g., "یه چیز خوب میخوام")
        if not rows:
            rows = await conn.fetch(
                """
                SELECT
                    product_id, persian_title, model_name, category_name, brand_name,
                    image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                    0.5 AS trgm_sim
                FROM products
                WHERE offer_count > 0
                  AND min_price_toman > 0
                ORDER BY offer_count DESC
                LIMIT $1
                """,
                limit,
            )

        results: list[dict[str, Any]] = []
        seen_signatures: set[tuple[int, str]] = set()
        for r in rows:
            min_p = int(r["min_price_toman"] or 0)
            # Deduplicate duplicate product listings that share the exact same price and model code
            norm_title = normalize_persian_text(r["persian_title"])
            model_codes = [m for m in re.findall(r"[a-z0-9]{3,}", norm_title) if not m.isdigit()]
            sig_key = (min_p, model_codes[0] if model_codes else norm_title[:18])
            if sig_key in seen_signatures:
                continue
            seen_signatures.add(sig_key)

            specs = (
                json.loads(r["specs_json"])
                if isinstance(r["specs_json"], str)
                else dict(r["specs_json"] or {})
            )
            results.append(
                {
                    "product_id": r["product_id"],
                    "title": r["persian_title"],
                    "english_title": r["model_name"] or r["persian_title"],
                    "category_id": abs(hash(r["category_name"])) % 1000,
                    "category_name": r["category_name"],
                    "brand_name": r["brand_name"],
                    "image_url": r["image_url"] or "",
                    "min_price_toman": min_p,
                    "max_price_toman": int(r["max_price_toman"] or 0),
                    "store_count": int(r["offer_count"] or 0),
                    "specs": {k: str(v) for k, v in list(specs.items())[:8]},
                    "trgm_sim": float(r["trgm_sim"] or 0.5),
                }
            )
            if len(results) >= limit:
                break

        await set_cached_json(redis_client, cache_key, results, settings.redis_qcache_ttl_seconds)
        return results


async def fetch_candidate_offers(
    pg_pool: asyncpg.Pool,
    product_ids: list[str],
    user_lat: float,
    user_lng: float,
    category_name: str | None = None,
    max_price_toman: int | None = None,
    limit: int | None = None,
    redis_client: aioredis.Redis | None = None,
) -> list[dict[str, Any]]:
    """Fetch candidate physical store offers in Tehran for given `product_ids`.

    Strictly prioritizes `offers` (actual product stock, `is_category_fallback=False`).
    Only if zero `offers` exist does it fall back to `shops.category_names_json` (`is_category_fallback=True`).
    """
    max_candidates = limit or settings.max_candidate_offers
    cache_key = query_cache_key(
        "offers",
        {
            "pids": product_ids[:5],
            "lat": round(user_lat, 3),
            "lng": round(user_lng, 3),
            "cat": category_name,
            "max_p": max_price_toman,
        },
    )
    cached = await get_cached_json(redis_client, cache_key)
    if isinstance(cached, list) and cached:
        return cached

    candidates: list[dict[str, Any]] = []
    async with pg_pool.acquire() as conn:
        if product_ids:
            params: list[Any] = [product_ids]
            price_filter = ""
            if max_price_toman is not None and max_price_toman > 0:
                params.append(max_price_toman)
                price_filter = f" AND o.price_toman <= ${len(params)}"
            params.append(max_candidates)

            sql = f"""
                SELECT
                    o.offer_id, o.product_id, o.shop_id, o.price_toman,
                    o.has_official_warranty, o.warranty_provider, o.last_price_changed_at,
                    p.persian_title AS product_name, p.category_name, p.specs_json,
                    s.name AS shop_name, s.latitude, s.longitude, s.address,
                    s.mall_name, s.floor_label, s.unit_label, s.mall_note,
                    s.primary_phone, s.score AS shop_score, s.votes_count,
                    s.supports_fast_delivery, s.has_in_person_installment,
                    s.installment_providers, s.weekly_hours_json,
                    s.website_url, s.instagram, s.is_real_torob_shop
                FROM offers o
                JOIN shops s ON s.shop_id = o.shop_id
                JOIN products p ON p.product_id = o.product_id
                WHERE o.product_id = ANY($1::text[])
                  {price_filter}
                ORDER BY s.is_real_torob_shop DESC, o.price_toman ASC
                LIMIT ${len(params)}
            """
            rows = await conn.fetch(sql, *params)
            for r in rows:
                dist_km = round(haversine_km(user_lat, user_lng, float(r["latitude"]), float(r["longitude"])), 2)
                drive_m, walk_m = estimate_travel_minutes(dist_km)
                is_open, hours_fa = evaluate_weekly_hours(r["weekly_hours_json"])
                fresh_badge, age_days = format_freshness_badge(r["last_price_changed_at"])
                specs = (
                    json.loads(r["specs_json"])
                    if isinstance(r["specs_json"], str)
                    else dict(r["specs_json"] or {})
                )
                candidates.append(
                    {
                        "offer_id": r["offer_id"],
                        "product_id": r["product_id"],
                        "product_name": r["product_name"],
                        "category_name": r["category_name"],
                        "specs": specs,
                        "shop_id": r["shop_id"],
                        "shop_name": r["shop_name"],
                        "price_toman": int(r["price_toman"]),
                        "distance_km": dist_km,
                        "driving_minutes": drive_m,
                        "walking_minutes": walk_m,
                        "latitude": float(r["latitude"]),
                        "longitude": float(r["longitude"]),
                        "address": r["address"] or "تهران",
                        "mall_micro_guide": {
                            "mall_name": r["mall_name"],
                            "floor_label": r["floor_label"],
                            "unit_label": r["unit_label"],
                            "note_fa": r["mall_note"],
                        },
                        "is_open_now": is_open,
                        "today_hours_fa": hours_fa,
                        "last_price_changed_at": r["last_price_changed_at"].isoformat()
                        if r["last_price_changed_at"]
                        else None,
                        "freshness_badge_fa": fresh_badge,
                        "freshness_age_days": age_days,
                        "shop_score": float(r["shop_score"] or 4.5),
                        "votes_count": int(r["votes_count"] or 15),
                        "supports_fast_delivery": bool(r["supports_fast_delivery"]),
                        "has_official_warranty": bool(r["has_official_warranty"]),
                        "warranty_provider": r["warranty_provider"],
                        "has_in_person_installment": bool(r["has_in_person_installment"]),
                        "installment_providers": list(r["installment_providers"] or []),
                        "primary_phone": r["primary_phone"] or "",
                        "is_real_torob_shop": bool(r["is_real_torob_shop"]),
                        "instagram": r["instagram"],
                        "website_url": r["website_url"],
                        "is_category_fallback": False,
                    }
                )

        # Explicit Category Fallback ONLY when 0 offers exist in `offers`
        if not candidates and category_name:
            cat_json = json.dumps([category_name], ensure_ascii=False)
            fb_rows = await conn.fetch(
                """
                SELECT
                    shop_id, name AS shop_name, latitude, longitude, address,
                    mall_name, floor_label, unit_label, mall_note,
                    primary_phone, score AS shop_score, votes_count,
                    supports_fast_delivery, has_in_person_installment,
                    installment_providers, weekly_hours_json,
                    website_url, instagram, is_real_torob_shop
                FROM shops
                WHERE category_names_json @> $1::jsonb
                ORDER BY is_real_torob_shop DESC
                LIMIT $2
                """,
                cat_json,
                min(15, max_candidates),
            )
            for idx, r in enumerate(fb_rows):
                dist_km = round(haversine_km(user_lat, user_lng, float(r["latitude"]), float(r["longitude"])), 2)
                drive_m, walk_m = estimate_travel_minutes(dist_km)
                is_open, hours_fa = evaluate_weekly_hours(r["weekly_hours_json"])
                candidates.append(
                    {
                        "offer_id": f"fallback_{r['shop_id']}_{idx}",
                        "product_id": product_ids[0] if product_ids else "category_fallback",
                        "product_name": f"فروشگاه هم‌صنف ({category_name}) — نیازمند استعلام تلفنی موجودی",
                        "category_name": category_name,
                        "specs": {},
                        "shop_id": r["shop_id"],
                        "shop_name": r["shop_name"],
                        "price_toman": 0,
                        "distance_km": dist_km,
                        "driving_minutes": drive_m,
                        "walking_minutes": walk_m,
                        "latitude": float(r["latitude"]),
                        "longitude": float(r["longitude"]),
                        "address": r["address"] or "تهران",
                        "mall_micro_guide": {
                            "mall_name": r["mall_name"],
                            "floor_label": r["floor_label"],
                            "unit_label": r["unit_label"],
                            "note_fa": r["mall_note"],
                        },
                        "is_open_now": is_open,
                        "today_hours_fa": hours_fa,
                        "last_price_changed_at": None,
                        "freshness_badge_fa": "نیازمند استعلام تلفنی قیمت و موجودی",
                        "freshness_age_days": 14.0,
                        "shop_score": float(r["shop_score"] or 4.3),
                        "votes_count": int(r["votes_count"] or 10),
                        "supports_fast_delivery": bool(r["supports_fast_delivery"]),
                        "has_official_warranty": False,
                        "warranty_provider": None,
                        "has_in_person_installment": bool(r["has_in_person_installment"]),
                        "installment_providers": list(r["installment_providers"] or []),
                        "primary_phone": r["primary_phone"] or "",
                        "is_real_torob_shop": bool(r["is_real_torob_shop"]),
                        "instagram": r["instagram"],
                        "website_url": r["website_url"],
                        "is_category_fallback": True,
                    }
                )

    await set_cached_json(redis_client, cache_key, candidates, settings.redis_qcache_ttl_seconds)
    return candidates


async def fetch_product_comparison(
    pg_pool: asyncpg.Pool,
    product_ids: list[str],
    user_lat: float,
    user_lng: float,
) -> dict[str, Any]:
    """Build dynamic category-aware comparison matrix across 2-3 products with live Tehran store availability."""
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT product_id, persian_title, brand_name, category_name, image_url,
                   specs_json, min_price_toman, offer_count
            FROM products
            WHERE product_id = ANY($1::text[])
            """,
            product_ids,
        )
        models: list[dict[str, Any]] = []
        spec_key_counts: dict[str, int] = {}
        category_name = "محصولات منتخب"

        for r in rows:
            category_name = r["category_name"] or category_name
            specs = (
                json.loads(r["specs_json"])
                if isinstance(r["specs_json"], str)
                else dict(r["specs_json"] or {})
            )
            for k in list(specs.keys())[:10]:
                spec_key_counts[k] = spec_key_counts.get(k, 0) + 1

            offers = await fetch_candidate_offers(
                pg_pool,
                [r["product_id"]],
                user_lat=user_lat,
                user_lng=user_lng,
                limit=15,
            )
            open_offers = [o for o in offers if o["is_open_now"] and not o["is_category_fallback"]]
            sorted_open = sorted(open_offers or offers, key=lambda x: x["distance_km"])
            closest = None
            if sorted_open:
                c0 = sorted_open[0]
                closest = {
                    "shop_id": c0["shop_id"],
                    "shop_name": c0["shop_name"],
                    "distance_km": c0["distance_km"],
                    "price_toman": c0["price_toman"],
                    "mall_badge_fa": c0["mall_micro_guide"].get("note_fa"),
                }

            models.append(
                {
                    "product_id": r["product_id"],
                    "name": r["persian_title"],
                    "brand_name": r["brand_name"],
                    "image_url": r["image_url"] or "",
                    "min_in_person_price_toman": int(r["min_price_toman"] or 0),
                    "open_stores_count": len(open_offers),
                    "closest_open_shop": closest,
                    "specs": {k: str(v) for k, v in specs.items()},
                    "pros_fa": [
                        f"موجود در {len(open_offers) or int(r['offer_count'] or 1)} فروشگاه حضوری تهران",
                        f"شروع قیمت از {int(r['min_price_toman'] or 0):,} تومان",
                    ],
                    "cons_fa": ["نیازمند هماهنگی تلفنی پیش از مراجعه حضوری"],
                }
            )

        top_spec_keys = [
            k for k, _ in sorted(spec_key_counts.items(), key=lambda item: item[1], reverse=True)[:6]
        ]
        return {
            "category_name": category_name,
            "spec_keys": top_spec_keys,
            "models": models,
        }


async def fetch_fallback_store(
    pg_pool: asyncpg.Pool,
    offer_id: str,
    user_lat: float,
    user_lng: float,
    excluded_shop_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Find the best 1-tap rescue store when a user arrives at a closed or out-of-stock shop."""
    excluded = set(excluded_shop_ids or [])
    async with pg_pool.acquire() as conn:
        orig = await conn.fetchrow(
            """
            SELECT o.offer_id, o.product_id, o.shop_id, o.price_toman,
                   s.mall_name, s.latitude, s.longitude, p.category_name
            FROM offers o
            JOIN shops s ON s.shop_id = o.shop_id
            JOIN products p ON p.product_id = o.product_id
            WHERE o.offer_id = $1
            """,
            str(offer_id),
        )
        if orig is None:
            return None

        excluded.add(str(orig["shop_id"]))
        ref_lat = float(orig["latitude"] or user_lat)
        ref_lng = float(orig["longitude"] or user_lng)
        orig_mall = orig["mall_name"]

        candidates = await fetch_candidate_offers(
            pg_pool,
            [orig["product_id"]],
            user_lat=ref_lat,
            user_lng=ref_lng,
            category_name=orig["category_name"],
            limit=30,
        )
        filtered = [c for c in candidates if str(c["shop_id"]) not in excluded]

        # Priority 3 Fallback: If no other shop stocks this exact product_id, find open stores in the same category/mall
        if not filtered:
            sim_rows = await conn.fetch(
                """
                SELECT o.product_id
                FROM products p
                JOIN offers o ON o.product_id = p.product_id
                WHERE p.category_name = $1 AND o.shop_id != $2
                LIMIT 10
                """,
                orig["category_name"],
                str(orig["shop_id"]),
            )
            sim_pids = list({str(r["product_id"]) for r in sim_rows})
            sim_candidates = await fetch_candidate_offers(
                pg_pool,
                sim_pids,
                user_lat=ref_lat,
                user_lng=ref_lng,
                category_name=orig["category_name"],
                limit=30,
            )
            sim_filtered = [c for c in sim_candidates if str(c["shop_id"]) not in excluded]
            if not sim_filtered:
                return None
            open_sim = [c for c in sim_filtered if c["is_open_now"]]
            best_sim = sorted(open_sim or sim_filtered, key=lambda x: (x["distance_km"], x["price_toman"]))[0]
            return {
                "fallback_type": "similar_product_nearby",
                "banner_fa": f"فروشگاه جایگزین هم‌صنف در نزدیکی شما ({best_sim['distance_km']} کیلومتر فاصله):",
                "alternative_store": best_sim,
            }

        # Priority 1: Open store inside the exact same indoor mall (`mall_name`)
        same_mall = [
            c
            for c in filtered
            if orig_mall and c["mall_micro_guide"].get("mall_name") == orig_mall and c["is_open_now"]
        ]
        if same_mall:
            best = sorted(same_mall, key=lambda x: x["price_toman"])[0]
            return {
                "fallback_type": "exact_product_same_mall",
                "banner_fa": f"جایگزین فوری در همان {orig_mall} (فاصله کمتر از ۱ دقیقه پیاده):",
                "alternative_store": best,
            }

        # Priority 2: Closest open store nearby stocking the exact same product
        open_nearby = [c for c in filtered if c["is_open_now"]]
        best = sorted(open_nearby or filtered, key=lambda x: (x["distance_km"], x["price_toman"]))[0]
        return {
            "fallback_type": "exact_product_nearby",
            "banner_fa": f"نزدیک‌ترین فروشگاه باز جایگزین ({best['distance_km']} کیلومتر فاصله):",
            "alternative_store": best,
        }
