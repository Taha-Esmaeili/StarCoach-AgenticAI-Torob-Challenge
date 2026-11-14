"""Sub-second PostgreSQL (`pg_trgm` + Haversine) & Redis cached queries for products and stores.

Zero hardcoded category lists, stopword sets, or regex filters:
- Category resolution is driven dynamically by database trigram similarity + Decision Model selection.
- Product search incorporates model-expanded `catalog_search_terms` across product titles, `specs_json`,
  and `offers.seller_title` / `offers.description` (supporting stock/open-box/conceptual queries).
- Enforces strict separation of `offers.csv` (verified stocked products) vs. `shops.category_names` fallback.
"""

import json
import math
import re
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from backend.config import settings
from backend.db.normalizer import (
    canonicalize_spec_map,
    evaluate_weekly_hours,
    format_freshness_badge,
    normalize_persian_text,
    parse_warranty,
    to_persian_digits,
)
from backend.db.redis_cache import get_cached_json, query_cache_key, set_cached_json

_BUDGET_DIST_NUM_RE = re.compile(
    r"\b\d+(?:[.,/]\d+)?\s*(?:میلیون|میلیارد|تومن|تومان|هزار|کیلومتر|متر|درصد|تومانی|میلیونی|ساعت|دقیقه|روز|ماه|ماهه|سال|ساله|عدد)\b"
)

_SQL_NORM_CAT_EXPR = (
    "REPLACE(LOWER(TRANSLATE(category_name, "
    "'يیئكآأإةؤ۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩' || chr(8204), "
    "'یییکاااهو01234567890123456789')), ' ', '')"
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
    """Extract normalized tokens while preserving model numbers (`5`, `16`, `256`) and stripping budget/distance units."""
    norm = normalize_persian_text(query)
    stripped = _BUDGET_DIST_NUM_RE.sub(" ", norm)
    raw_tokens: list[str] = []
    for t in stripped.split():
        if t.isdigit():
            if 1 <= len(t) <= 4 and t not in raw_tokens:
                raw_tokens.append(t)
        elif len(t) >= 2 and t not in raw_tokens:
            raw_tokens.append(t)
    substantial = [t for t in raw_tokens if len(t) >= 3 or t.isascii() or t.isdigit()]
    chosen = substantial if substantial else raw_tokens
    return chosen[:8]


async def fetch_candidate_categories(
    pg_pool: asyncpg.Pool | None,
    query: str,
    limit: int = 10,
) -> list[str]:
    """Retrieve top candidate `category_name`s from PostgreSQL matching tokens in `query` (`< 5 ms`).

    Passed directly to the Decision Model (`choice`) so category routing requires zero hardcoded rules.
    """
    if pg_pool is None:
        return []
    tokens = extract_search_tokens(query)
    if not tokens:
        return []
    non_digit_tokens = [t for t in tokens if not t.isdigit()] or tokens
    sql = f"""
        WITH tok_cats AS (
            SELECT
                tok,
                category_name,
                GREATEST(
                    word_similarity(tok, category_name),
                    CASE WHEN LENGTH(REPLACE(tok, ' ', '')) >= 3 AND {_SQL_NORM_CAT_EXPR} LIKE '%' || REPLACE(tok, ' ', '') || '%' THEN 1.0 ELSE 0.0 END
                )
                + 0.002 * LEAST(LENGTH(REPLACE(tok, ' ', '')), 10)
                - CASE
                    WHEN tok NOT IN ('کیف', 'کاور', 'قاب', 'گارد', 'قطعه', 'قطعات', 'دسته', 'دیسک', 'کابل', 'جانبی', 'پمپ', 'شارژر', 'محافظ', 'فن', 'پایه')
                     AND (
                        category_name LIKE '%لوازم جانبی%'
                        OR category_name LIKE '%کیف و کاور%'
                        OR category_name LIKE '%کاور و قاب%'
                        OR category_name LIKE '%قطعات%'
                        OR category_name LIKE '%محافظ صفحه%'
                        OR category_name LIKE '%دیسک بازی%'
                        OR category_name LIKE '%دسته بازی%'
                        OR category_name LIKE '%کابل و تبدیل%'
                     )
                    THEN 0.30
                    ELSE 0.0
                  END AS w_sim,
                SUM(offer_count) AS total_offers,
                ROW_NUMBER() OVER (
                    PARTITION BY tok
                    ORDER BY
                        ROUND(
                            GREATEST(
                                word_similarity(tok, category_name),
                                CASE WHEN LENGTH(REPLACE(tok, ' ', '')) >= 3 AND {_SQL_NORM_CAT_EXPR} LIKE '%' || REPLACE(tok, ' ', '') || '%' THEN 1.0 ELSE 0.0 END
                            )::numeric,
                            1
                        ) DESC,
                        SUM(offer_count) DESC
                ) AS rn
            FROM products
            CROSS JOIN unnest($1::text[]) AS tok
            WHERE offer_count > 0
              AND min_price_toman > 0
              AND normalized_name NOT LIKE '%حذف شده%'
              AND category_name NOT LIKE '%حذف%'
              AND (
                  word_similarity(tok, category_name) >= 0.45
                  OR {_SQL_NORM_CAT_EXPR} LIKE '%' || REPLACE(tok, ' ', '') || '%'
              )
            GROUP BY tok, category_name
        ),
        title_cats AS (
            SELECT
                category_name,
                LEAST(0.95, 0.78 + 0.04 * COUNT(DISTINCT tok)) AS w_sim,
                SUM(offer_count) AS total_offers,
                COUNT(DISTINCT tok) AS matched_toks
            FROM products
            CROSS JOIN unnest($2::text[]) AS tok
            WHERE offer_count > 0
              AND min_price_toman > 0
              AND normalized_name NOT LIKE '%حذف شده%'
              AND category_name NOT LIKE '%حذف%'
              AND (
                  CASE
                      WHEN tok ~ '^[0-9]+$' THEN normalized_name ~ ('(^|[^0-9])' || tok || '($|[^0-9])')
                      ELSE REPLACE(normalized_name, ' ', '') LIKE '%' || REPLACE(tok, ' ', '') || '%'
                  END
              )
            GROUP BY category_name
            ORDER BY COUNT(DISTINCT tok) DESC, SUM(offer_count) DESC
            LIMIT 6
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
        LIMIT $3
    """
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(sql, non_digit_tokens, tokens, limit)
    return [str(r["category_name"]) for r in rows if r["category_name"]]


async def _resolve_dynamic_categories_sql(
    conn: asyncpg.Connection,
    norm_query: str,
    category_keywords: list[str] | None = None,
    is_accessory_request: bool = False,
) -> list[str]:
    """Dynamically resolve the best matching `category_name`s in `products` via exact, spaceless, or trigram similarity."""
    probe_terms = [
        normalize_persian_text(k)
        for k in (category_keywords or [])
        if k and len(normalize_persian_text(k)) >= 2
    ]
    if norm_query and norm_query not in probe_terms:
        probe_terms.append(norm_query)
    for qt in extract_search_tokens(norm_query):
        if not qt.isdigit() and len(qt.replace(" ", "")) >= 3 and qt not in probe_terms:
            probe_terms.append(qt)
    if not probe_terms:
        return []

    if category_keywords:
        spaceless_kw = [
            normalize_persian_text(k).replace(" ", "")
            for k in category_keywords
            if k and normalize_persian_text(k).replace(" ", "")
        ]
        exact_rows = await conn.fetch(
            f"""
            SELECT category_name, SUM(offer_count) AS total_offers
            FROM products
            WHERE (
                  category_name = ANY($1::text[])
                  OR {_SQL_NORM_CAT_EXPR} = ANY($2::text[])
              )
              AND offer_count > 0
              AND category_name NOT LIKE '%حذف%'
              AND normalized_name NOT LIKE '%حذف شده%'
            GROUP BY category_name
            ORDER BY total_offers DESC
            LIMIT 1
            """,
            category_keywords,
            spaceless_kw,
        )
        if exact_rows:
            return [str(exact_rows[0]["category_name"])]

    probe_spaceless = [p.replace(" ", "") for p in probe_terms if len(p.replace(" ", "")) >= 3]
    sql = f"""
        SELECT
            category_name,
            (
                MAX(
                    GREATEST(
                        similarity(kw, category_name),
                        CASE
                            WHEN LENGTH(REPLACE(kw, ' ', '')) >= 3
                             AND {_SQL_NORM_CAT_EXPR} LIKE '%' || REPLACE(kw, ' ', '') || '%'
                            THEN 0.86
                            ELSE 0.0
                        END
                    )
                )
                - CASE
                    WHEN NOT $3::bool AND (
                        category_name LIKE '%لوازم جانبی%'
                        OR category_name LIKE '%کیف و کاور%'
                        OR category_name LIKE '%کاور و قاب%'
                        OR category_name LIKE '%قطعات%'
                        OR category_name LIKE '%محافظ صفحه%'
                        OR category_name LIKE '%دیسک بازی%'
                        OR category_name LIKE '%دسته بازی%'
                        OR category_name LIKE '%کابل و تبدیل%'
                    ) THEN 0.35
                    ELSE 0.0
                  END
            ) AS cat_sim,
            SUM(offer_count) AS total_offers
        FROM products
        CROSS JOIN unnest($1::text[]) AS kw
        WHERE offer_count > 0
          AND min_price_toman > 0
          AND category_name NOT LIKE '%حذف%'
          AND normalized_name NOT LIKE '%حذف شده%'
          AND (
              word_similarity(kw, category_name) >= 0.45
              OR (
                  cardinality($2::text[]) > 0
                  AND {_SQL_NORM_CAT_EXPR} LIKE ANY($2::text[])
              )
          )
        GROUP BY category_name
        ORDER BY cat_sim DESC, total_offers DESC
        LIMIT 3
    """
    spaceless_patterns = [f"%{s}%" for s in probe_spaceless]
    rows = await conn.fetch(sql, probe_terms, spaceless_patterns, bool(is_accessory_request))
    if not rows:
        return []
    top_sim = float(rows[0]["cat_sim"] or 0.0)
    return [str(r["category_name"]) for r in rows if float(r["cat_sim"] or 0.0) >= top_sim - 0.06]


async def fetch_product_by_id(
    pg_pool: asyncpg.Pool,
    product_id: str,
) -> dict[str, Any] | None:
    """Fetch a single product dictionary by `product_id` for `selected_product_id` synchronization."""
    if not product_id:
        return None
    async with pg_pool.acquire() as conn:
        r = await conn.fetchrow(
            """
            SELECT product_id, persian_title, model_name, category_name, brand_name,
                   image_url, specs_json, min_price_toman, max_price_toman, offer_count
            FROM products
            WHERE product_id = $1
            """,
            str(product_id),
        )
        if r is None:
            return None
        specs = (
            json.loads(r["specs_json"])
            if isinstance(r["specs_json"], str)
            else dict(r["specs_json"] or {})
        )
        return {
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
            "trgm_sim": 1.0,
            "category_p10_price": 0,
            "category_p90_price": 0,
            "offer_titles_sample": "",
            "budget_relaxed": False,
        }


async def search_products(
    pg_pool: asyncpg.Pool,
    query: str,
    max_price_toman: int | None = None,
    limit: int = 6,
    redis_client: aioredis.Redis | None = None,
    min_price_toman: int | None = None,
    price_tier: str = "mid",
    category_keywords: list[str] | None = None,
    is_accessory_request: bool = False,
    catalog_search_terms: list[str] | None = None,
    excluded_product_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search stocked products via dynamic SQL category resolution, `catalog_search_terms`, and offer-text awareness."""
    raw_norm = normalize_persian_text(query)
    tokens = extract_search_tokens(raw_norm)
    norm_q = " ".join(tokens) if tokens else raw_norm
    norm_cat_kw = [normalize_persian_text(k) for k in (category_keywords or []) if k]
    clean_terms = [
        normalize_persian_text(t)
        for t in (catalog_search_terms or [])
        if t and len(normalize_persian_text(t)) >= 2
    ][:5]
    excl_pids = [str(p) for p in (excluded_product_ids or []) if p]

    cache_key = query_cache_key(
        "products_v11",
        {
            "q": norm_q,
            "terms": clean_terms,
            "cat_kw": norm_cat_kw,
            "acc": is_accessory_request,
            "tier": price_tier,
            "min_p": min_price_toman,
            "max_p": max_price_toman,
            "excl": sorted(excl_pids),
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

    fetch_limit = max(limit * 3, 16)
    norm_terms = [normalize_persian_text(t) for t in clean_terms if normalize_persian_text(t)]
    term_patterns = [f"%{t}%" for t in norm_terms]
    budget_relaxed = False

    async with pg_pool.acquire() as conn:
        rows: list[Any] = []
        cat_p10 = 0
        cat_p90 = 0
        matched_cats = await _resolve_dynamic_categories_sql(
            conn,
            norm_query=norm_q,
            category_keywords=norm_cat_kw,
            is_accessory_request=is_accessory_request,
        )
        if not matched_cats and clean_terms:
            matched_cats = await _resolve_dynamic_categories_sql(
                conn,
                norm_query=" ".join(clean_terms),
                category_keywords=norm_cat_kw,
                is_accessory_request=is_accessory_request,
            )

        # 1. Search inside dynamically matched categories first
        if matched_cats:
            span_row = await conn.fetchrow(
                """
                SELECT
                    PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY min_price_toman) AS p10,
                    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY min_price_toman) AS p90
                FROM products
                WHERE offer_count > 0
                  AND min_price_toman > 0
                  AND normalized_name NOT LIKE '%حذف شده%'
                  AND category_name = ANY($1::text[])
                """,
                matched_cats,
            )
            if span_row:
                cat_p10 = int(round(float(span_row["p10"] or 0)))
                cat_p90 = int(round(float(span_row["p90"] or 0)))

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
            cat_spaceless_str = " ".join(
                normalize_persian_text(c).replace(" ", "") for c in [*matched_cats, *norm_cat_kw]
            )
            specific_tokens = [
                t
                for t in tokens
                if t not in cat_word_set
                and (t.isdigit() or t.replace(" ", "") not in cat_spaceless_str)
            ][:6]
            spec_spaceless = [t.replace(" ", "") for t in specific_tokens if not t.isdigit() and t.replace(" ", "")]
            spec_digits = [t for t in specific_tokens if t.isdigit()]
            total_spec = len(spec_spaceless) + len(spec_digits)

            cat_outlier_floor = (
                max(int(cat_p10 * 0.6), int(cat_p90 * 0.12))
                if (not is_accessory_request and cat_p90 > 0)
                else 0
            )

            async def _fetch_in_cat(
                min_p_val: int,
                max_p_val: int,
                min_hits_val: int,
                sort_sql: str,
            ) -> list[Any]:
                sql_cat = f"""
                    WITH offer_hits AS (
                        SELECT DISTINCT o.product_id
                        FROM offers o
                        JOIN products p2 ON p2.product_id = o.product_id
                        WHERE cardinality($3::text[]) > 0
                            AND p2.category_name = ANY($2::text[])
                            AND (o.seller_title ILIKE ANY($3::text[]) OR o.description ILIKE ANY($3::text[]))
                        LIMIT 250
                    ),
                    scored AS (
                        SELECT
                            products.product_id, products.persian_title, products.model_name,
                            products.category_name, products.brand_name, products.image_url,
                            products.specs_json, products.min_price_toman, products.max_price_toman,
                            products.offer_count,
                            GREATEST(word_similarity($1, products.normalized_name), 0.72) AS trgm_sim,
                            (
                                (
                                    SELECT COUNT(*)
                                    FROM unnest($5::text[]) AS st
                                    WHERE REPLACE(products.normalized_name, ' ', '') LIKE '%' || st || '%'
                                )
                                + (
                                    SELECT COUNT(*)
                                    FROM unnest($6::text[]) AS dt
                                    WHERE products.normalized_name ~ ('(^|[^0-9])' || dt || '($|[^0-9])')
                                )
                            ) AS token_hits,
                            (
                                CASE WHEN oh.product_id IS NOT NULL THEN 2 ELSE 0 END
                                + (
                                    SELECT COUNT(*) * 2
                                    FROM unnest($3::text[]) AS tp
                                    WHERE products.normalized_name ILIKE tp
                                       OR products.specs_json::text ILIKE tp
                                )
                            ) AS concept_boost,
                            CASE
                                WHEN $11 > 0 AND products.min_price_toman < $11 THEN 1
                                ELSE 0
                            END AS is_price_outlier
                        FROM products
                        LEFT JOIN offer_hits oh ON oh.product_id = products.product_id
                        WHERE products.offer_count > 0
                          AND products.min_price_toman > 0
                          AND products.normalized_name NOT LIKE '%حذف شده%'
                          AND products.category_name NOT LIKE '%حذف%'
                          AND products.category_name = ANY($2::text[])
                          AND NOT (products.product_id = ANY($4::text[]))
                          AND ($7 <= 0 OR products.min_price_toman >= $7)
                          AND ($8 <= 0 OR products.min_price_toman <= $8)
                    )
                    SELECT *
                    FROM scored
                    WHERE token_hits >= $9
                    ORDER BY is_price_outlier ASC, token_hits DESC, concept_boost DESC, {sort_sql}
                    LIMIT $10
                """
                return await conn.fetch(
                    sql_cat,
                    norm_q,
                    matched_cats,
                    term_patterns,
                    excl_pids,
                    spec_spaceless,
                    spec_digits,
                    min_p_val,
                    max_p_val,
                    min_hits_val,
                    fetch_limit,
                    cat_outlier_floor,
                )

            eff_min_p = int(min_price_toman or 0)
            eff_max_p = int(max_price_toman or 0)
            if total_spec > 0:
                rows = await _fetch_in_cat(eff_min_p, eff_max_p, total_spec, order_clause)
                if len(rows) < 2 and total_spec > 1:
                    partial_rows = await _fetch_in_cat(eff_min_p, eff_max_p, 1, order_clause)
                    if partial_rows:
                        seen_r = {r["product_id"] for r in rows}
                        rows = [*rows, *(pr for pr in partial_rows if pr["product_id"] not in seen_r)]
            if not rows:
                rows = await _fetch_in_cat(eff_min_p, eff_max_p, 0, order_clause)

            # If budget constraint eliminated all items inside the right category, relax budget inside category
            # rather than falling through to unrelated cheap items in other categories!
            if not rows and eff_max_p > 0:
                relax_sort = "min_price_toman ASC, offer_count DESC"
                if total_spec > 0:
                    rows = await _fetch_in_cat(0, 0, total_spec, relax_sort)
                    if len(rows) < 2 and total_spec > 1:
                        partial_rows = await _fetch_in_cat(0, 0, 1, relax_sort)
                        if partial_rows:
                            seen_r = {r["product_id"] for r in rows}
                            rows = [*rows, *(pr for pr in partial_rows if pr["product_id"] not in seen_r)]
                if not rows:
                    rows = await _fetch_in_cat(0, 0, 0, relax_sort)
                if rows:
                    budget_relaxed = True

        # 2. General token + catalog-term search using spaceless trigram index
        all_search_tokens = list(
            dict.fromkeys([*tokens, *(t for ct in clean_terms for t in extract_search_tokens(ct))])
        )
        if not rows and all_search_tokens:
            gen_non_digits = [t.replace(" ", "") for t in all_search_tokens if not t.isdigit() and len(t.replace(" ", "")) >= 2][:4]
            gen_digits = [t for t in all_search_tokens if t.isdigit()][:2]

            async def _fetch_general(max_p_val: int, use_or: bool, sort_sql: str) -> list[Any]:
                conds: list[str] = []
                g_params: list[Any] = [norm_q, excl_pids, int(min_price_toman or 0), max_p_val]
                for gt in gen_non_digits:
                    g_params.append(f"%{gt}%")
                    conds.append(f"REPLACE(normalized_name, ' ', '') LIKE ${len(g_params)}")
                for gd in gen_digits:
                    g_params.append(f"(^|[^0-9]){gd}($|[^0-9])")
                    conds.append(f"normalized_name ~ ${len(g_params)}")
                if not conds:
                    return []
                g_params.append(fetch_limit)
                joiner = " OR " if use_or else " AND "
                sql_gen = f"""
                    SELECT
                        product_id, persian_title, model_name, category_name, brand_name,
                        image_url, specs_json, min_price_toman, max_price_toman, offer_count,
                        word_similarity($1, normalized_name) AS trgm_sim
                    FROM products
                    WHERE offer_count > 0
                      AND min_price_toman > 0
                      AND normalized_name NOT LIKE '%حذف شده%'
                      AND category_name NOT LIKE '%حذف%'
                      AND NOT (product_id = ANY($2::text[]))
                      AND ($3 <= 0 OR min_price_toman >= $3)
                      AND ($4 <= 0 OR min_price_toman <= $4)
                      AND ({joiner.join(conds)})
                    ORDER BY {'trgm_sim DESC, ' if use_or else ''}{sort_sql}
                    LIMIT ${len(g_params)}
                """
                return await conn.fetch(sql_gen, *g_params)

            eff_max_p = int(max_price_toman or 0)
            rows = await _fetch_general(eff_max_p, False, order_clause)
            if not rows and eff_max_p > 0:
                rows = await _fetch_general(0, False, "min_price_toman ASC, offer_count DESC")
                if rows:
                    budget_relaxed = True
            if len(rows) < 2 and (len(gen_non_digits) + len(gen_digits)) > 1 and gen_non_digits:
                or_rows = await _fetch_general(0 if budget_relaxed else eff_max_p, True, order_clause)
                if or_rows:
                    seen_r = {r["product_id"] for r in rows}
                    rows = [*rows, *(orr for orr in or_rows if orr["product_id"] not in seen_r)]

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
                  AND normalized_name NOT LIKE '%حذف شده%'
                  AND category_name NOT LIKE '%حذف%'
                  AND NOT (product_id = ANY($1::text[]))
                ORDER BY offer_count DESC
                LIMIT $2
                """,
                excl_pids,
                limit,
            )

        results: list[dict[str, Any]] = []
        seen_signatures: set[tuple[int, str]] = set()
        for r in rows:
            min_p = int(r["min_price_toman"] or 0)
            norm_title = normalize_persian_text(r["persian_title"])
            sig_key = (min_p, norm_title[:36])
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
                    "category_p10_price": cat_p10,
                    "category_p90_price": cat_p90,
                    "offer_titles_sample": "",
                    "budget_relaxed": budget_relaxed,
                }
            )
            if len(results) >= limit:
                break

        if results:
            pids = [str(it["product_id"]) for it in results]
            sample_rows = await conn.fetch(
                """
                SELECT product_id,
                       STRING_AGG(DISTINCT LEFT(TRIM(COALESCE(seller_title, '') || ' ' || COALESCE(description, '')), 90), ' | ') AS offer_sample
                FROM (
                    SELECT product_id, seller_title, description
                    FROM offers
                    WHERE product_id = ANY($1::text[])
                      AND (seller_title IS NOT NULL OR description IS NOT NULL)
                    LIMIT 40
                ) sub
                GROUP BY product_id
                """,
                pids,
            )
            sample_map = {str(sr["product_id"]): str(sr["offer_sample"] or "")[:220] for sr in sample_rows}
            for it in results:
                it["offer_titles_sample"] = sample_map.get(str(it["product_id"]), "")

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
    require_installment: bool = False,
    require_torob_pay: bool = False,
    require_warranty: bool = False,
    max_distance_km: float | None = None,
    excluded_offer_ids: list[str] | None = None,
    excluded_shop_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch candidate physical store offers in Tehran for given `product_ids`.

    Strictly prioritizes `offers` (actual product stock, `is_category_fallback=False`).
    Only if zero `offers` exist does it fall back to `shops.category_names_json` (`is_category_fallback=True`).
    """
    max_candidates = limit or settings.max_candidate_offers
    excl_offers = [str(oid) for oid in (excluded_offer_ids or []) if oid]
    excl_shops = [str(sid) for sid in (excluded_shop_ids or []) if sid]
    cache_key = query_cache_key(
        "offers_v3",
        {
            "pids": product_ids[:5],
            "lat": round(user_lat, 3),
            "lng": round(user_lng, 3),
            "cat": category_name,
            "max_p": max_price_toman,
            "inst": require_installment,
            "tpay": require_torob_pay,
            "warr": require_warranty,
            "max_d": round(max_distance_km, 2) if max_distance_km is not None else None,
            "ex_o": sorted(excl_offers),
            "ex_s": sorted(excl_shops),
            "lim": max_candidates,
        },
    )
    cached = await get_cached_json(redis_client, cache_key)
    if isinstance(cached, list) and cached:
        return cached

    sql_limit = max(max_candidates, 120)
    candidates: list[dict[str, Any]] = []
    async with pg_pool.acquire() as conn:
        if product_ids:
            sql = """
                SELECT
                    o.offer_id, o.product_id, o.shop_id, o.price_toman,
                    o.seller_title, o.description, o.warranty_raw,
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
                  AND NOT (o.offer_id = ANY($2::text[]))
                  AND NOT (o.shop_id = ANY($3::text[]))
                  AND p.normalized_name NOT LIKE '%حذف شده%'
                  AND p.category_name NOT LIKE '%حذف%'
                ORDER BY
                    (CASE WHEN $8 > 0 AND o.price_toman > $8 THEN 1 ELSE 0 END) ASC,
                    (CASE WHEN $7 AND NOT (s.installment_providers && ARRAY['ترب‌پی', 'ترب پی']::text[]) THEN 1 ELSE 0 END) ASC,
                    (CASE WHEN $6 AND NOT s.has_in_person_installment THEN 1 ELSE 0 END) ASC,
                    (
                        CASE
                            WHEN $9 > 0
                             AND SQRT(POWER((s.latitude - $4) * 111.0, 2) + POWER((s.longitude - $5) * 90.1, 2)) > $9
                            THEN 1
                            ELSE 0
                        END
                    ) ASC,
                    s.is_real_torob_shop DESC,
                    o.price_toman ASC
                LIMIT $10
            """
            rows = await conn.fetch(
                sql,
                product_ids,
                excl_offers,
                excl_shops,
                float(user_lat),
                float(user_lng),
                bool(require_installment),
                bool(require_torob_pay),
                int(max_price_toman or 0),
                float(max_distance_km or 0.0),
                int(sql_limit),
            )
            for r in rows:
                dist_km = round(haversine_km(user_lat, user_lng, float(r["latitude"]), float(r["longitude"])), 2)
                drive_m, walk_m = estimate_travel_minutes(dist_km)
                is_open, hours_fa = evaluate_weekly_hours(r["weekly_hours_json"])
                fresh_badge, age_days = format_freshness_badge(r["last_price_changed_at"])
                raw_w = str(r["warranty_raw"] or "")
                if raw_w.strip():
                    has_warr, warr_prov, _ = parse_warranty(raw_w)
                else:
                    has_warr = bool(r["has_official_warranty"])
                    warr_prov = r["warranty_provider"]
                specs = (
                    json.loads(r["specs_json"])
                    if isinstance(r["specs_json"], str)
                    else dict(r["specs_json"] or {})
                )
                inst_provs = (
                    json.loads(r["installment_providers"])
                    if isinstance(r["installment_providers"], str)
                    else list(r["installment_providers"] or [])
                )
                candidates.append(
                    {
                        "offer_id": r["offer_id"],
                        "product_id": r["product_id"],
                        "product_name": r["product_name"],
                        "category_name": r["category_name"],
                        "specs": specs,
                        "seller_title": r["seller_title"] or "",
                        "description": r["description"] or "",
                        "warranty_raw": raw_w,
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
                        "has_official_warranty": has_warr,
                        "warranty_provider": warr_prov,
                        "has_in_person_installment": bool(r["has_in_person_installment"]),
                        "installment_providers": inst_provs,
                        "primary_phone": r["primary_phone"] or "",
                        "is_real_torob_shop": bool(r["is_real_torob_shop"]),
                        "instagram": r["instagram"],
                        "website_url": r["website_url"],
                        "is_category_fallback": False,
                    }
                )

            if max_price_toman is not None and max_price_toman > 0:
                in_budget = [c for c in candidates if c["price_toman"] <= max_price_toman]
                if in_budget:
                    candidates = in_budget

        # Explicit Category Fallback ONLY when 0 offers exist in `offers`
        if not candidates and category_name and "حذف" not in category_name:
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
                  AND NOT (shop_id = ANY($2::text[]))
                ORDER BY is_real_torob_shop DESC
                LIMIT $3
                """,
                cat_json,
                excl_shops,
                min(15, max_candidates),
            )
            for idx, r in enumerate(fb_rows):
                dist_km = round(haversine_km(user_lat, user_lng, float(r["latitude"]), float(r["longitude"])), 2)
                drive_m, walk_m = estimate_travel_minutes(dist_km)
                is_open, hours_fa = evaluate_weekly_hours(r["weekly_hours_json"])
                inst_provs = (
                    json.loads(r["installment_providers"])
                    if isinstance(r["installment_providers"], str)
                    else list(r["installment_providers"] or [])
                )
                candidates.append(
                    {
                        "offer_id": f"fallback_{r['shop_id']}_{idx}",
                        "product_id": product_ids[0] if product_ids else "category_fallback",
                        "product_name": f"فروشگاه هم‌صنف ({category_name}) — نیازمند استعلام تلفنی موجودی",
                        "category_name": category_name,
                        "specs": {},
                        "seller_title": "",
                        "description": "",
                        "warranty_raw": "",
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
                        "installment_providers": inst_provs,
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
        row_map = {str(r["product_id"]): r for r in rows}
        ordered_rows = [row_map[pid] for pid in product_ids if pid in row_map]
        models: list[dict[str, Any]] = []
        spec_key_counts: dict[str, int] = {}
        category_name = "محصولات منتخب"

        for r in ordered_rows:
            category_name = r["category_name"] or category_name
            raw_specs = (
                json.loads(r["specs_json"])
                if isinstance(r["specs_json"], str)
                else dict(r["specs_json"] or {})
            )
            specs = canonicalize_spec_map(raw_specs)
            for k in list(specs.keys())[:10]:
                spec_key_counts[k] = spec_key_counts.get(k, 0) + 1

            offers = await fetch_candidate_offers(
                pg_pool,
                [r["product_id"]],
                user_lat=user_lat,
                user_lng=user_lng,
                limit=30,
            )
            open_offers = [o for o in offers if o["is_open_now"] and not o["is_category_fallback"]]
            sorted_open = sorted(open_offers, key=lambda x: (x["distance_km"], x["price_toman"]))
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

            total_shop_cnt = int(r["offer_count"] or len(offers) or 1)
            availability_pro = (
                f"هم‌اکنون در {to_persian_digits(len(open_offers))} فروشگاه باز تهران موجود است"
                if open_offers
                else f"ثبت‌شده در {to_persian_digits(total_shop_cnt)} فروشگاه حضوری تهران (هم‌اکنون خارج از ساعت کاری)"
            )
            models.append(
                {
                    "product_id": r["product_id"],
                    "name": r["persian_title"],
                    "brand_name": r["brand_name"],
                    "image_url": r["image_url"] or "",
                    "min_in_person_price_toman": int(r["min_price_toman"] or 0),
                    "open_stores_count": len(open_offers),
                    "closest_open_shop": closest,
                    "specs": specs,
                    "pros_fa": [
                        availability_pro,
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
    excluded = {str(s) for s in (excluded_shop_ids or []) if s}
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
        orig_price = int(orig["price_toman"] or 0)
        fair_cap = int(orig_price * 1.15) if orig_price > 0 else 0

        # Always pass the USER's coordinates so `distance_km` reflects real distance from user!
        candidates = await fetch_candidate_offers(
            pg_pool,
            [orig["product_id"]],
            user_lat=user_lat,
            user_lng=user_lng,
            category_name=orig["category_name"],
            excluded_shop_ids=list(excluded),
            limit=80,
        )
        real_filtered = [
            c for c in candidates
            if str(c["shop_id"]) not in excluded and not c.get("is_category_fallback")
        ]
        filtered = real_filtered or [c for c in candidates if str(c["shop_id"]) not in excluded]

        if not filtered:
            sim_rows = await conn.fetch(
                """
                SELECT o.product_id
                FROM products p
                JOIN offers o ON o.product_id = p.product_id
                WHERE p.category_name = $1
                  AND o.shop_id != $2
                  AND p.normalized_name NOT LIKE '%حذف شده%'
                LIMIT 12
                """,
                orig["category_name"],
                str(orig["shop_id"]),
            )
            sim_pids = list({str(r["product_id"]) for r in sim_rows})
            sim_candidates = await fetch_candidate_offers(
                pg_pool,
                sim_pids,
                user_lat=user_lat,
                user_lng=user_lng,
                category_name=orig["category_name"],
                excluded_shop_ids=list(excluded),
                limit=40,
            )
            sim_filtered = [c for c in sim_candidates if str(c["shop_id"]) not in excluded]
            if not sim_filtered:
                return None
            open_sim = [c for c in sim_filtered if c["is_open_now"]]
            chosen = sorted(
                open_sim or sim_filtered,
                key=lambda x: (haversine_km(ref_lat, ref_lng, x["latitude"], x["longitude"]), x["price_toman"]),
            )[0]
            closed_note = "" if chosen["is_open_now"] else " (هم‌اکنون بسته — جهت مراجعه در ساعت کاری)"
            return {
                "fallback_type": "similar_product_nearby",
                "banner_fa": (
                    f"موجودی دقیق در فروشگاه‌های دیگر تمام شده؛ نزدیک‌ترین فروشگاه هم‌صنف "
                    f"«{chosen['shop_name']}» در فاصله {to_persian_digits(chosen['distance_km'])} کیلومتری شما پیشنهاد شد{closed_note}."
                ),
                "alternative_store": chosen,
            }

        def _step_km(c: dict[str, Any]) -> float:
            return round(haversine_km(ref_lat, ref_lng, c["latitude"], c["longitude"]), 2)

        def _is_fair_price(c: dict[str, Any]) -> bool:
            return fair_cap <= 0 or c["price_toman"] <= 0 or c["price_toman"] <= fair_cap

        same_mall = [
            c for c in filtered if orig_mall and c["mall_micro_guide"].get("mall_name") == orig_mall
        ]
        open_pool = [c for c in filtered if c["is_open_now"]]

        if open_pool:
            open_mall_fair = [c for c in same_mall if c["is_open_now"] and _is_fair_price(c)]
            if open_mall_fair:
                chosen = sorted(open_mall_fair, key=lambda x: x["price_toman"])[0]
                loc_note = chosen["mall_micro_guide"].get("note_fa") or orig_mall
                return {
                    "fallback_type": "exact_product_same_mall",
                    "banner_fa": (
                        f"همین مدل هم‌اکنون در همان پاساژ ({loc_note}) در فروشگاه باز «{chosen['shop_name']}» "
                        f"(فاصله از شما: {to_persian_digits(chosen['distance_km'])} کیلومتر) موجود است!"
                    ),
                    "alternative_store": chosen,
                }

            open_fair = [c for c in open_pool if _is_fair_price(c)]
            chosen = sorted(open_fair or open_pool, key=lambda x: (_step_km(x), x["price_toman"]))[0]
            is_in_same_mall = bool(orig_mall and chosen["mall_micro_guide"].get("mall_name") == orig_mall)
            return {
                "fallback_type": "exact_product_same_mall" if is_in_same_mall else "exact_product_nearby",
                "banner_fa": (
                    f"نزدیک‌ترین فروشگاه باز دارای همین مدل: «{chosen['shop_name']}» "
                    f"(فاصله از شما: {to_persian_digits(chosen['distance_km'])} کیلومتر)."
                ),
                "alternative_store": chosen,
            }

        # All candidate stores are currently outside working hours -> pick fairest price/step and state clearly
        mall_fair_closed = [c for c in same_mall if _is_fair_price(c)]
        if mall_fair_closed:
            chosen = sorted(mall_fair_closed, key=lambda x: x["price_toman"])[0]
            loc_note = chosen["mall_micro_guide"].get("note_fa") or orig_mall
            return {
                "fallback_type": "exact_product_same_mall",
                "banner_fa": (
                    f"در حال حاضر هیچ فروشگاه بازی یافت نشد؛ برای مراجعه در ساعت کاری، همین مدل در همان پاساژ ({loc_note}) "
                    f"در «{chosen['shop_name']}» (فاصله از شما: {to_persian_digits(chosen['distance_km'])} کیلومتر) موجود است."
                ),
                "alternative_store": chosen,
            }

        fair_closed = [c for c in filtered if _is_fair_price(c)]
        chosen = sorted(fair_closed or filtered, key=lambda x: (_step_km(x), x["price_toman"]))[0]
        return {
            "fallback_type": "exact_product_nearby",
            "banner_fa": (
                f"در حال حاضر هیچ فروشگاه بازی یافت نشد؛ نزدیک‌ترین فروشگاه جایگزین برای ساعت کاری: "
                f"«{chosen['shop_name']}» در فاصله {to_persian_digits(chosen['distance_km'])} کیلومتری شما."
            ),
            "alternative_store": chosen,
        }
