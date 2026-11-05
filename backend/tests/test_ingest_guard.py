"""Phase 2 self-check: dataset guard rules, PostgreSQL + pgvector + pg_trgm counts, Redis caching, and <50ms query benchmark."""

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
from backend.db.postgres import create_pg_pool
from backend.db.profiles import (
    find_closest_dynamic_slot_pgvector,
    load_shopping_session,
    load_user_profile,
    save_shopping_session,
    save_user_profile,
)
from backend.db.queries import (
    fetch_candidate_offers,
    fetch_fallback_store,
    fetch_product_comparison,
    search_products,
)
from backend.db.redis_cache import create_redis_client


def test_normalizer_and_mall_extraction_rules():
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

    is_open, hours_fa = evaluate_weekly_hours(
        '{"sat":{"status":"declared","shifts":[{"start_time":"10:00:00","end_time":"19:00:00"}]}}'
    )
    assert isinstance(is_open, bool)
    assert len(hours_fa) > 0


@pytest.mark.asyncio
async def test_postgres_pgvector_redis_dataset_and_sub50ms_queries():
    pool = await create_pg_pool()
    redis_client = await create_redis_client()
    try:
        async with pool.acquire() as conn:
            shops_count = await conn.fetchval("SELECT COUNT(*) FROM shops;")
            real_shops_count = await conn.fetchval("SELECT COUNT(*) FROM shops WHERE is_real_torob_shop = TRUE;")
            mall_shops_count = await conn.fetchval("SELECT COUNT(*) FROM shops WHERE mall_name IS NOT NULL;")
            products_count = await conn.fetchval("SELECT COUNT(*) FROM products;")
            offers_count = await conn.fetchval("SELECT COUNT(*) FROM offers;")

        assert shops_count == 6476
        assert real_shops_count == 112
        assert mall_shops_count >= 3500
        assert products_count == 225903
        assert offers_count == 331506

        # Verify sub-second product search & Redis cache hit < 50ms
        prods = await search_products(pool, "دوربین سونی", limit=5, redis_client=redis_client)
        assert len(prods) >= 1
        pid = prods[0]["product_id"]

        t0 = time.perf_counter()
        prods_cached = await search_products(pool, "دوربین سونی", limit=5, redis_client=redis_client)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert len(prods_cached) == len(prods)
        assert elapsed_ms < 50.0

        # Verify strict offer stock retrieval (is_category_fallback == False)
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

        # Verify user_profiles + pgvector dynamic slot cosine similarity (<=>) + Redis session persistence
        test_uid = "usr_pytest_pgvector"
        unit_vec = [1.0] + [0.0] * (settings.embedding_dim - 1)
        prof = await load_user_profile(test_uid, pg_pool=pool, redis_client=redis_client)
        prof["dynamic_slots"] = [
            {
                "slot_id": 11,
                "feature_key": "spec_anc_mic",
                "label_fa": "حذف نویز میکروفون",
                "category_name": "هدفون، هدست و هندزفری",
                "weight": 0.85,
                "confidence": 0.90,
                "embedding": unit_vec,
                "session_hits": 2,
            }
        ]
        await save_user_profile(prof, pg_pool=pool, redis_client=redis_client)

        matched_slot, cos_sim = await find_closest_dynamic_slot_pgvector(pool, test_uid, unit_vec)
        assert matched_slot == 11
        assert cos_sim > 0.99

        sess = await load_shopping_session(
            "sess_pytest_01",
            user_id=test_uid,
            pg_pool=pool,
            redis_client=redis_client,
        )
        sess["clarification_count"] = 1
        await save_shopping_session(sess, pg_pool=pool, redis_client=redis_client)
        reloaded_sess = await load_shopping_session(
            "sess_pytest_01",
            user_id=test_uid,
            pg_pool=pool,
            redis_client=redis_client,
        )
        assert reloaded_sess["clarification_count"] == 1
    finally:
        await redis_client.aclose()
        await pool.close()
