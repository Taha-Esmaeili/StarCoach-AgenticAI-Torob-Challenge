"""Tier-2 regression & audit-fix verification tests covering `recsys_audit_issues/01..06`."""

import asyncpg
import pytest

from backend.config import settings
from backend.db.normalizer import canonicalize_spec_map, parse_warranty
from backend.db.queries import (
    extract_search_tokens,
    fetch_candidate_categories,
    fetch_candidate_offers,
    fetch_fallback_store,
    fetch_product_comparison,
    search_products,
)
from backend.main import _build_inline_comparison_matrix
from backend.models.schemas import HardConstraintsState, RecommendedProductItem
from backend.recsys.clarifier import should_trigger_clarification
from backend.recsys.scorer import score_and_rank_offers_with_meta


def test_01_search_tokens_keep_model_numbers_and_strip_budget_distance():
    tokens = extract_search_tokens("آیفون ۱۶ نرمال ۱۲۸ گیگ تا ۶۰ میلیون حداکثر ۵ کیلومتر")
    assert "16" in tokens
    assert "128" in tokens
    assert "60" not in tokens
    assert "5" not in tokens

    ps5_tokens = extract_search_tokens("پلی استیشن ۵ اسلیم دیجیتال")
    assert "5" in ps5_tokens
    assert "اسلیم" in ps5_tokens


def test_02_parse_warranty_rejects_test_only_and_used_phrases():
    for non_warranty in (
        "مهلت تست 7 روزه",
        "تحویل در حضور مشتری",
        "ضمانت اصالت و سلامت فیزیکی کالا",
        "بدون گارانتی",
        "دست دوم استوک در حد نو",
        "مشابه اصل های کپی",
        '{"description": "بدون گارانتی", "provider": "متفرقه"}',
    ):
        has_w, prov, _ = parse_warranty(non_warranty)
        assert has_w is False, f"Expected False for {non_warranty!r}"
        assert prov is None

    has_real, label, months = parse_warranty('{"provider": "شرکتی داریا همراه", "period_months": 18}')
    assert has_real is True
    assert months == 18
    assert label is not None and "۱۸" in label and "داریا" in label


def test_03_04_scorer_hard_constraints_counterfeit_floor_dedup_and_pareto():
    candidates = [
        # Counterfeit / accessory outlier at 830k vs ~20M real AirPods
        {
            "offer_id": "off_fake",
            "product_id": "p1",
            "shop_id": "shop_fake",
            "shop_name": "فروشگاه کپی",
            "price_toman": 830_000,
            "distance_km": 1.2,
            "driving_minutes": 6,
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۲",
            "has_official_warranty": False,
            "has_in_person_installment": False,
            "installment_providers": [],
            "freshness_age_days": 2.0,
            "freshness_badge_fa": "بروزرسانی ۲ روز پیش",
        },
        # Duplicate shop_id (`shop_a`) with two offers — only the better one must appear
        {
            "offer_id": "off_a1",
            "product_id": "p1",
            "shop_id": "shop_a",
            "shop_name": "اپل استور تجریش",
            "price_toman": 19_500_000,
            "distance_km": 2.1,
            "driving_minutes": 9,
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۲",
            "has_official_warranty": True,
            "warranty_provider": "گارانتی ۱۸ ماهه شرکتی",
            "has_in_person_installment": True,
            "installment_providers": ["ترب‌پی"],
            "freshness_age_days": 1.0,
            "freshness_badge_fa": "بروزرسانی دیروز",
        },
        {
            "offer_id": "off_a2",
            "product_id": "p1",
            "shop_id": "shop_a",
            "shop_name": "اپل استور تجریش",
            "price_toman": 20_100_000,
            "distance_km": 2.1,
            "driving_minutes": 9,
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۲",
            "has_official_warranty": True,
            "warranty_provider": "گارانتی ۱۸ ماهه شرکتی",
            "has_in_person_installment": True,
            "installment_providers": ["ترب‌پی"],
            "freshness_age_days": 1.0,
            "freshness_badge_fa": "بروزرسانی دیروز",
        },
        # Far store (14.5 km) that violates max_distance_km=5.0
        {
            "offer_id": "off_far",
            "product_id": "p1",
            "shop_id": "shop_far",
            "shop_name": "موبایل جنوب تهران",
            "price_toman": 19_200_000,
            "distance_km": 14.5,
            "driving_minutes": 38,
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۱",
            "has_official_warranty": True,
            "warranty_provider": "گارانتی ۱۸ ماهه شرکتی",
            "has_in_person_installment": False,
            "installment_providers": [],
            "freshness_age_days": 210.0,
            "freshness_badge_fa": "بروزرسانی ۷ ماه پیش",
        },
        # Second valid nearby store within 5km, slightly more expensive than shop_a
        {
            "offer_id": "off_b",
            "product_id": "p1",
            "shop_id": "shop_b",
            "shop_name": "دیجیتال شمرون",
            "price_toman": 21_200_000,
            "distance_km": 1.5,
            "driving_minutes": 7,
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۲",
            "has_official_warranty": True,
            "warranty_provider": "گارانتی ۱۲ ماهه شرکتی",
            "has_in_person_installment": True,
            "installment_providers": ["اسنپ‌پی"],
            "freshness_age_days": 180.0,
            "freshness_badge_fa": "بروزرسانی ۶ ماه پیش",
            "f_offer_custom": 0.25,
        },
    ]
    weights = {
        "w_price": 0.35,
        "w_distance": 0.25,
        "w_open_now": 0.15,
        "w_trust_freshness": 0.15,
        "w_installment": 0.10,
    }
    ranked, unmet = score_and_rank_offers_with_meta(
        candidates,
        l1_weights=weights,
        hard_constraints=HardConstraintsState(require_open_now=True, require_warranty=True),
        max_distance_km=5.0,
    )
    assert unmet == []
    shop_ids = [s.shop_id for s in ranked]
    assert len(shop_ids) == len(set(shop_ids)), "Duplicate shop_id leaked into ranked stores"
    assert "shop_far" not in shop_ids, "Store outside max_distance_km=5.0 was not filtered"
    assert "shop_fake" not in shop_ids, "Store without official warranty was not filtered"
    assert ranked[0].shop_id == "shop_a"
    assert ranked[0].pareto_role == "best_overall"
    # shop_b is 21.2M > shop_a (19.5M), so shop_b MUST NOT get pareto_role == "lowest_price"
    for s in ranked[1:]:
        assert s.pareto_role != "lowest_price"
        assert not any("۷ ماه" in r or "۶ ماه" in r for r in s.why_this_shop_fa)
        assert not any("شرط خاص" in r for r in s.why_this_shop_fa)

    # Test counterfeit outlier penalty when warranty filter is off
    ranked_no_warr, _ = score_and_rank_offers_with_meta(
        candidates,
        l1_weights={"w_price": 0.80, "w_distance": 0.20},
        hard_constraints=HardConstraintsState(),
    )
    assert ranked_no_warr[0].shop_id != "shop_fake"
    fake_entry = next(s for s in ranked_no_warr if s.shop_id == "shop_fake")
    assert fake_entry.pareto_role != "lowest_price"
    assert fake_entry.feature_scores["f_price"] == pytest.approx(0.20)

    # Test Policy A1 graceful relaxation when 0 stores are open at night
    closed_pool = [{**c, "is_open_now": False} for c in candidates[1:3]]
    ranked_relaxed, unmet_night = score_and_rank_offers_with_meta(
        closed_pool,
        l1_weights={"w_open_now": 0.60, "w_price": 0.40},
        hard_constraints=HardConstraintsState(require_open_now=True),
    )
    assert "باز بودن فعلی مغازه" in unmet_night
    assert ranked_relaxed[0].utility_score > 30, "Relaxed store utility must not collapse to 10%"


def test_05_clarifier_respects_specific_model_intent():
    should_ask, next_c = should_trigger_clarification(
        effective_confidence=0.90,
        clarification_count=0,
        explicit_thumbs_down=False,
        dissatisfied_noul=0.05,
        needs_clarification_noul=0.75,
        intent_choice="store_ranking",
    )
    assert should_ask is False
    assert next_c == 0


def test_06_comparison_headers_and_spec_canonicalization():
    merged = canonicalize_spec_map({"مقدار RAM": "8 گیگابایت", "ظرفیت رم": "8GB", "پردازنده‌": "M2", "تراشه": "Apple M2"})
    assert list(merged.keys()) == ["ظرفیت رم", "پردازنده / تراشه"]

    cards = [
        RecommendedProductItem(
            product_id=f"p{i}",
            title=f"گوشی شیائومی مدل Redmi Note 13 Pro 4G ظرفیت 256 گیگابایت رم 8 گیگابایت ({variant})",
            english_title="Redmi Note 13 Pro",
            category_id=1,
            category_name="گوشی موبایل",
            image_url="",
            min_price_toman=18_000_000 + i * 500_000,
            max_price_toman=20_000_000,
            store_count=12,
            match_score=95 - i,
            best_for_fa="خرید حضوری",
            badge_fa="پیشنهاد",
            pros_fa=["کیفیت ساخت"],
            cons_fa=[],
            specs={"ظرفیت رم": "8 گیگابایت"} if i == 1 else {"مقدار RAM": "8 گیگابایت"},
        )
        for i, variant in enumerate(["گلوبال", "پک هند", "ویتنام"], start=1)
    ]
    matrix = _build_inline_comparison_matrix(cards)
    assert matrix is not None
    product_headers = matrix.headers[1:]
    assert len(product_headers) == 3
    assert len(set(product_headers)) == 3, f"Duplicate headers found: {product_headers}"
    ram_rows = [r for r in matrix.rows if "رم" in str(r["feature"]) or "RAM" in str(r["feature"])]
    assert len(ram_rows) == 1


@pytest.mark.asyncio
async def test_live_db_orthography_censored_filter_comparison_and_fallback():
    pool = await asyncpg.create_pool(dsn=settings.asyncpg_dsn, min_size=1, max_size=3)
    try:
        # 1. Orthography + double-space category resolution (`پلی استیشن ۵`, `لپتاپ`) + zero censored items
        ps5_cats = await fetch_candidate_categories(pool, "پلی استیشن ۵ اسلیم دیجیتال", limit=5)
        assert any("PS5" in c or "پلی" in c for c in ps5_cats), f"PS5 category missed: {ps5_cats}"
        assert all("حذف" not in c for c in ps5_cats)

        laptop_cats = await fetch_candidate_categories(pool, "لپتاپ", limit=5)
        assert any("لپ تاپ" in c for c in laptop_cats), f"Spaceless لپتاپ missed: {laptop_cats}"

        ps5_prods = await search_products(
            pool,
            query="پلی استیشن ۵ اسلیم دیجیتال",
            category_keywords=["کنسول بازی  PS5"],
            limit=5,
        )
        assert len(ps5_prods) >= 1
        assert all("حذف" not in p["title"] for p in ps5_prods)
        assert any("PS5" in p["title"] or "پلی" in p["title"] for p in ps5_prods)

        iphone_prods = await search_products(
            pool,
            query="آیفون ۱۶ نرمال ۱۲۸ گیگ",
            category_keywords=["گوشی موبایل"],
            limit=5,
        )
        assert len(iphone_prods) >= 1
        assert any("16" in p["title"] or "۱۶" in p["title"] for p in iphone_prods)

        # 2. Proximity-priority SQL (`max_distance_km=5.0`) keeps nearby Valiasr shops instead of cutting off by global price
        valiasr_offers = await fetch_candidate_offers(
            pool,
            product_ids=[p["product_id"] for p in iphone_prods],
            user_lat=35.7117,
            user_lng=51.4070,
            max_distance_km=5.0,
            limit=60,
        )
        assert any(float(o["distance_km"]) <= 5.0 for o in valiasr_offers)

        # 3. Comparison endpoint invariant: if open_stores_count == 0, closest_open_shop MUST be None
        comp = await fetch_product_comparison(
            pool,
            product_ids=[p["product_id"] for p in iphone_prods[:2]],
            user_lat=35.7575,
            user_lng=51.4100,
        )
        for m in comp["models"]:
            if m["open_stores_count"] == 0:
                assert m["closest_open_shop"] is None
            else:
                assert m["closest_open_shop"] is not None

        # 4. Fallback store distance_km is measured from USER (Vanak), NOT 0.01 km from Shop 1 (Jomhouri/Tajrish)
        multi_offer_pid = await pool.fetchval(
            """
            SELECT o.product_id
            FROM offers o
            JOIN shops s ON s.shop_id = o.shop_id
            WHERE s.latitude IS NOT NULL
            GROUP BY o.product_id
            HAVING COUNT(DISTINCT o.shop_id) >= 4
            LIMIT 1
            """
        )
        sample_offer_id = await pool.fetchval(
            "SELECT offer_id FROM offers WHERE product_id = $1 LIMIT 1",
            multi_offer_pid,
        )
        # Place user far north-east so distance from user is clearly > 1.0 km even if two shops are in the same mall
        fb = await fetch_fallback_store(
            pool,
            offer_id=sample_offer_id,
            user_lat=35.8150,
            user_lng=51.4700,
        )
        assert fb is not None
        alt = fb["alternative_store"]
        assert float(alt["distance_km"]) > 0.5, f"Expected distance from user, got {alt['distance_km']}"
    finally:
        await pool.close()


def test_07_bounded_memory_and_feedback_contracts():
    from backend.db.profiles import _MAX_MEMORY_CACHE_SIZE, _put_bounded_memory
    from backend.models.schemas import FeedbackRequest

    store: dict[str, int] = {}
    for i in range(_MAX_MEMORY_CACHE_SIZE + 10):
        _put_bounded_memory(store, f"k_{i}", i)
    assert len(store) == _MAX_MEMORY_CACHE_SIZE
    assert "k_0" not in store
    assert f"k_{_MAX_MEMORY_CACHE_SIZE + 9}" in store

    req_prod = FeedbackRequest(
        session_id="sess_test",
        feedback_type="product_select",
        selected_product_id="prod_4",
    )
    assert req_prod.selected_product_id == "prod_4"

    req_const = FeedbackRequest(
        session_id="sess_test",
        feedback_type="constraint_update",
        hard_constraints=HardConstraintsState(require_open_now=True, require_installment=True),
        require_torob_pay=True,
    )
    assert req_const.require_torob_pay is True
    assert req_const.hard_constraints is not None and req_const.hard_constraints.require_open_now is True
