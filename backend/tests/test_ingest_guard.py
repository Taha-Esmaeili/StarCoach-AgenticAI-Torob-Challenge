"""Dataset guard rules, clean schema purge audit, Asia/Tehran open-hours accuracy, and <50ms query benchmark."""

from datetime import datetime, timezone
import time
import pytest

from backend.config import settings
from backend.db.normalizer import (
    clean_null_str,
    evaluate_weekly_hours,
    extract_mall_micro_guide,
    normalize_persian_text,
    parse_payment_options,
    parse_product_specs,
    parse_warranty,
)
from backend.db.postgres import create_pg_pool, ensure_schema
from backend.db.profiles import (
    fetch_user_traits,
    find_closest_user_aspects_pgvector,
    load_shopping_session,
    load_user_profile,
    save_shopping_session,
    save_user_profile,
    upsert_user_trait_with_inertia,
)
from backend.db.queries import (
    fetch_candidate_offers,
    fetch_fallback_store,
    fetch_product_comparison,
    search_products,
)
from backend.db.redis_cache import create_redis_client, session_key


def test_normalizer_mall_extraction_and_tehran_timezone_rules():
    assert clean_null_str("null") is None
    assert clean_null_str("  NULL ") is None
    assert normalize_persian_text("گوشی آیفون ۱۶\u200cپرو") == "گوشی ایفون 16 پرو"

    mall = extract_mall_micro_guide("خیابان جمهوری، نبش شیخ هادی، پاساژ علالدین 2، طبقه 6، واحد 622")
    assert mall["mall_name"] == "پاساژ علالدین 2"
    assert mall["floor_label"] == "طبقه 6"
    assert mall["unit_label"] == "واحد 622"

    _, has_inst, providers = parse_payment_options(
        '[{"provider_name":"ترب‌پی","channel":"in_person"},{"provider_name":"اسنپ‌پی","channel":"unknown"}]'
    )
    assert has_inst is True
    assert "ترب‌پی" in providers and "اسنپ‌پی" in providers

    specs = parse_product_specs('[{"key":"رم","value":"8 گیگابایت"},{"key":"حافظه","value":"null"}]')
    assert specs == {"رم": "8 گیگابایت"}

    has_w, prov, months = parse_warranty('{"description":"گارانتی ۱۸ ماهه شرکتی","period_months":18}')
    assert has_w is True
    assert prov == "گارانتی ۱۸ ماهه شرکتی"
    assert months == 18

    # Bug #10 verification: 2026-10-10 is Saturday (`sat`).
    # 17:00 UTC == 20:30 Asia/Tehran -> outside 10:00..19:00 shift (must be False, NOT UTC True!)
    sat_schedule = '{"sat":{"status":"declared","shifts":[{"start_time":"10:00:00","end_time":"19:00:00"}]}}'
    open_evening_utc, hours_fa = evaluate_weekly_hours(
        sat_schedule,
        now_dt=datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc),
    )
    assert open_evening_utc is False
    assert "۱۰:۰۰ تا ۱۹:۰۰" in hours_fa

    # 12:00 UTC == 15:30 Asia/Tehran -> inside 10:00..19:00 shift (must be True)
    open_midday_utc, _ = evaluate_weekly_hours(
        sat_schedule,
        now_dt=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
    )
    assert open_midday_utc is True


@pytest.mark.asyncio
async def test_postgres_clean_schema_sub50ms_queries_and_durable_persistence():
    pool = await create_pg_pool()
    redis_client = await create_redis_client()
    try:
        await ensure_schema(pool)
        async with pool.acquire() as conn:
            shops_count = await conn.fetchval("SELECT COUNT(*) FROM shops;")
            real_shops_count = await conn.fetchval("SELECT COUNT(*) FROM shops WHERE is_real_torob_shop = TRUE;")
            mall_shops_count = await conn.fetchval("SELECT COUNT(*) FROM shops WHERE mall_name IS NOT NULL;")
            products_count = await conn.fetchval("SELECT COUNT(*) FROM products;")
            offers_count = await conn.fetchval("SELECT COUNT(*) FROM offers;")

            has_dyn_table = await conn.fetchval("SELECT to_regclass('public.user_dynamic_slots') IS NOT NULL;")
            has_prod_emb = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='products' AND column_name='embedding');"
            )
            has_trait_domain = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='user_trait_memory' AND column_name='domain');"
            )

        assert shops_count == 6476
        assert real_shops_count == 112
        assert mall_shops_count >= 3500
        assert products_count == 225903
        assert offers_count == 331506
        assert has_dyn_table is False
        assert has_prod_emb is False
        assert has_trait_domain is False

        # Verify sub-second product search (including catalog_search_terms) & Redis cache hit < 50ms
        prods = await search_products(
            pool,
            "دوربین سونی",
            catalog_search_terms=["سونی", "دیجیتال"],
            limit=5,
            redis_client=redis_client,
        )
        assert len(prods) >= 1
        pid = prods[0]["product_id"]

        t0 = time.perf_counter()
        prods_cached = await search_products(
            pool,
            "دوربین سونی",
            catalog_search_terms=["سونی", "دیجیتال"],
            limit=5,
            redis_client=redis_client,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert len(prods_cached) == len(prods)
        assert elapsed_ms < 50.0

        # Verify strict offer stock retrieval (is_category_fallback == False) + seller_title/description presence
        offers = await fetch_candidate_offers(
            pool,
            [pid],
            user_lat=settings.default_user_lat,
            user_lng=settings.default_user_lng,
            category_name=prods[0]["category_name"],
            redis_client=redis_client,
        )
        assert len(offers) >= 1
        assert offers[0]["is_category_fallback"] is False
        assert offers[0]["price_toman"] > 0
        assert "seller_title" in offers[0] and "description" in offers[0]

        # Verify category fallback when querying a synthetic non-existent product_id
        fallback_offers = await fetch_candidate_offers(
            pool,
            ["product_nonexistent_000"],
            user_lat=settings.default_user_lat,
            user_lng=settings.default_user_lng,
            category_name="دوربین مدار بسته",
        )
        assert len(fallback_offers) >= 1
        assert fallback_offers[0]["is_category_fallback"] is True

        # Verify dynamic product comparison & 1-tap fallback rescue
        comp = await fetch_product_comparison(
            pool,
            [p["product_id"] for p in prods[:2]],
            user_lat=settings.default_user_lat,
            user_lng=settings.default_user_lng,
        )
        assert len(comp["models"]) >= 1

        fb_store = await fetch_fallback_store(
            pool,
            offer_id=str(offers[0]["offer_id"]),
            user_lat=settings.default_user_lat,
            user_lng=settings.default_user_lng,
        )
        assert fb_store is None or "alternative_store" in fb_store

        # Verify clean `user_profiles` (`store_weights` + `price_percentiles`) + `user_trait_memory` pgvector cosine
        test_uid = "usr_pytest_clean_003"
        unit_vec = [1.0] + [0.0] * (settings.embedding_dim - 1)
        prof = await load_user_profile(test_uid, pg_pool=pool, redis_client=redis_client)
        prof["store_weights"]["w_distance"] = 0.82
        prof["price_percentiles"]["دوربین عکاسی و فیلمبرداری"] = {"pct": 0.68, "n": 3}
        await save_user_profile(prof, pg_pool=pool, redis_client=redis_client)

        await upsert_user_trait_with_inertia(
            pg_pool=pool,
            user_id=test_uid,
            source_category="دوربین عکاسی و فیلمبرداری",
            aspect="وزن بدنه",
            preference="سبک و قابل‌حمل برای سفر",
            aspect_embedding=unit_vec,
            alpha=settings.recsys_trait_confirmed_step,
        )
        closest = await find_closest_user_aspects_pgvector(pool, test_uid, unit_vec, limit=3)
        assert len(closest) >= 1
        assert float(closest[0]["cos_sim"]) > 0.99

        traits = await fetch_user_traits(pool, test_uid)
        assert any(t["source_category"] == "دوربین عکاسی و فیلمبرداری" for t in traits)

        # Verify durable `session_context_json` recovery in PostgreSQL after Redis eviction
        sess_id = "sess_pytest_durable_003"
        sess = await load_shopping_session(sess_id, user_id=test_uid, pg_pool=pool, redis_client=redis_client)
        sess["clarification_count"] = 1
        sess["product_search_query"] = "دوربین ولاگ سونی"
        sess["catalog_search_terms"] = ["سونی", "لرزشگیر"]
        sess["custom_offer_criterion"] = "پاساژ پایتخت"
        await save_shopping_session(sess, pg_pool=pool, redis_client=redis_client)

        await redis_client.delete(session_key(sess_id))
        reloaded = await load_shopping_session(sess_id, user_id=test_uid, pg_pool=None, redis_client=redis_client)
        # Without pg_pool, cache miss creates fresh or memory; now reload strictly from PostgreSQL:
        from backend.db.profiles import _MEMORY_SESSIONS

        _MEMORY_SESSIONS.pop(sess_id, None)
        await redis_client.delete(session_key(sess_id))
        reloaded_pg = await load_shopping_session(sess_id, user_id=test_uid, pg_pool=pool, redis_client=redis_client)
        assert reloaded_pg["clarification_count"] == 1
        assert reloaded_pg["product_search_query"] == "دوربین ولاگ سونی"
        assert reloaded_pg["catalog_search_terms"] == ["سونی", "لرزشگیر"]
        assert reloaded_pg["custom_offer_criterion"] == "پاساژ پایتخت"
    finally:
        await redis_client.aclose()
        await pool.close()
