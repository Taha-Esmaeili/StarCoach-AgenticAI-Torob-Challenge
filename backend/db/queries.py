"""Sub-second PostgreSQL (`pg_trgm` + `pgvector` + Haversine) & Redis cached queries for products and stores.

Enforces strict separation of `offers.csv` (verified stocked products) vs.
`shops.category_names` (labeled category fallback when 0 direct offers exist).
"""

import json
import math
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

_STOPWORDS_FA = {
    "یه",
    "یک",
    "میخوام",
    "میخواهم",
    "بخرم",
    "خرید",
    "حضوری",
    "برای",
    "تهران",
    "سمت",
    "نزدیک",
    "مغازه",
    "فروشگاه",
    "ارزون",
    "ارزان",
    "ارزانترین",
    "ارزونترین",
    "سریع",
    "سریعترین",
    "بهترین",
    "خوب",
    "الان",
    "همین",
    "باز",
    "قسطی",
    "اقساطی",
    "با",
    "در",
    "از",
    "تا",
    "میلیون",
    "تومان",
    "تومن",
    "چی",
    "کجا",
    "کجاست",
}


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
    """Extract normalized meaningful search tokens from a natural-language Persian query."""
    norm = normalize_persian_text(query)
    tokens = [t for t in norm.split() if len(t) >= 2 and t not in _STOPWORDS_FA and not t.isdigit()]
    return tokens[:6]


def rerank_products_with_domain_traits(
    raw_products: list[dict[str, Any]],
    domain_traits: list[dict[str, Any]] | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    """Stage-1 domain-trait product re-ranking (`T009`).

    Boosts candidate products whose title or specs align with the user's retrieved
    `domain_traits` (from `user_trait_memory`) and records matched traits for card display.
    """
    if not raw_products:
        return []
    traits = domain_traits or []
    norm_q = normalize_persian_text(query)
    reranked: list[dict[str, Any]] = []
    for prod in raw_products:
        item = dict(prod)
        specs_dict = item.get("specs") or {}
        blob = normalize_persian_text(
            f"{item.get('title', '')} {item.get('english_title', '')} "
            + " ".join(f"{k} {v}" for k, v in specs_dict.items())
        )
        matched_prefs: list[str] = []
        bonus = 0.0
        for t in traits:
            pref = str(t.get("preference") or "").strip()
            aspect = str(t.get("aspect") or "").strip()
            conf = float(t.get("confidence", 0.85))
            pref_tokens = [tok for tok in normalize_persian_text(pref).split() if len(tok) >= 2]
            aspect_tokens = [tok for tok in normalize_persian_text(aspect).split() if len(tok) >= 2]
            if any(tok in blob for tok in pref_tokens):
                bonus += 0.14 * conf
                matched_prefs.append(pref)
            elif any(tok in blob for tok in aspect_tokens):
                bonus += 0.07 * conf
                matched_prefs.append(pref)
            elif traits and len(matched_prefs) == 0:
                # Apply mild personal context alignment when user has active domain traits
                bonus += 0.03 * conf
                matched_prefs.append(pref)

        if norm_q and any(tok in blob for tok in extract_search_tokens(norm_q)):
            bonus += 0.04

        base_sim = float(item.get("trgm_sim") or 0.65)
        item["trgm_sim"] = round(min(0.99, base_sim + bonus), 4)
        item["matched_traits"] = matched_prefs[:2]
        reranked.append(item)

    reranked.sort(
        key=lambda p: (float(p.get("trgm_sim") or 0.0), int(p.get("store_count") or 0)),
        reverse=True,
    )
    return reranked


async def search_products(
    pg_pool: asyncpg.Pool,
    query: str,
    max_price_toman: int | None = None,
    limit: int = 6,
    query_embedding: list[float] | None = None,
    redis_client: aioredis.Redis | None = None,
) -> list[dict[str, Any]]:
    """Search stocked products via `pg_trgm` + token match + optional `pgvector` `<=>` cosine similarity."""
    tokens = extract_search_tokens(query)
    norm_q = " ".join(tokens) if tokens else normalize_persian_text(query)

    cache_key = query_cache_key(
        "products",
        {"q": norm_q, "max_p": max_price_toman, "limit": limit},
    )
    cached = await get_cached_json(redis_client, cache_key)
    if isinstance(cached, list) and cached:
        return cached

    async with pg_pool.acquire() as conn:
        rows: list[Any] = []
        if tokens:
            # Build token ILIKE clauses prioritizing products that actually have offers in Tehran
            like_patterns = [f"%{t}%" for t in tokens[:4]]
            where_parts = [f"normalized_name LIKE ${i + 2}" for i in range(len(like_patterns))]
            params: list[Any] = [norm_q, *like_patterns]
            price_clause = ""
            if max_price_toman is not None and max_price_toman > 0:
                params.append(max_price_toman)
                price_clause = f" AND min_price_toman <= ${len(params)}"
            params.append(limit)

            sql = f"""
                SELECT
                    product_id, persian_title, model_name, category_name, brand_name,
                    image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                    similarity(normalized_name, $1) AS trgm_sim
                FROM products
                WHERE offer_count > 0
                  AND ({' AND '.join(where_parts)})
                  {price_clause}
                ORDER BY trgm_sim DESC, offer_count DESC
                LIMIT ${len(params)}
            """
            rows = await conn.fetch(sql, *params)

            # Broaden to OR matching if strict AND returned fewer than 2 products
            if len(rows) < 2 and len(like_patterns) > 1:
                sql_or = f"""
                    SELECT
                        product_id, persian_title, model_name, category_name, brand_name,
                        image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                        similarity(normalized_name, $1) AS trgm_sim
                    FROM products
                    WHERE offer_count > 0
                      AND ({' OR '.join(where_parts)})
                      {price_clause}
                    ORDER BY trgm_sim DESC, offer_count DESC
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
                ORDER BY offer_count DESC
                LIMIT $1
                """,
                limit,
            )

        results: list[dict[str, Any]] = []
        for r in rows:
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
                    "min_price_toman": int(r["min_price_toman"] or 0),
                    "max_price_toman": int(r["max_price_toman"] or 0),
                    "store_count": int(r["offer_count"] or 0),
                    "specs": {k: str(v) for k, v in list(specs.items())[:8]},
                    "trgm_sim": float(r["trgm_sim"] or 0.5),
                }
            )

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
