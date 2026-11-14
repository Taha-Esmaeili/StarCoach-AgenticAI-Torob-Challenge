"""Spec 003 Two-Layer Adaptive RecSys unit & mocked tests (US1, US2, US3):
- US1: Category-agnostic selective trait transfer (`Noul >= 0.72`), dynamic concept expansion,
  100% Decision-Model trait attribution (`0%` false badges), and open-category price-prior boost.
- US2: Exact `.env` `recsys_mention_score_threshold` (`0.35`, no `0.18` cap), `>= 80%` sparse override,
  conditional 6th `w_offer_custom` slot, and physical Pareto Top-3 placement at `[0, 1, 2]`.
- US3: Gift/ephemeral shield (`>= 0.60`), Top-2 per-aspect `strength` inertia (`0.15` vs `0.35`, `0.92` rival decay),
  and contrastive store & category price-percentile learning.
"""

import math
import pytest

from backend.config import settings
from backend.db.profiles import (
    _MEMORY_TRAITS,
    build_default_profile,
    fetch_user_traits,
    upsert_user_trait_with_inertia,
)
from backend.main import _build_recommended_product_cards
from backend.models.schemas import HardConstraintsState
from backend.recsys import jev_engine
from backend.recsys.clarifier import (
    build_clarification_card,
    should_trigger_clarification,
)
from backend.recsys.deduplicator import (
    cosine_similarity,
    sync_user_traits,
)
from backend.recsys.jev_engine import (
    ExtractedTrait,
    ScoreJudgment,
    _has_valid_api_key,
    embed_text_async,
    evaluate_turn_with_jev,
    score_candidate_products_with_decision_model,
    score_custom_offer_criterion_with_decision_model,
)
from backend.recsys.scorer import score_and_rank_offers
from backend.recsys.weights import (
    fuse_and_normalize_weights,
    l1_normalize_weights,
    update_category_price_percentile,
    update_store_weights_contrastive,
)


@pytest.mark.asyncio
async def test_live_model_enforcement_without_simulators(monkeypatch):
    """Verify that when API keys are empty, evaluate_turn_with_jev and embed_text_async raise RuntimeError."""
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    assert not _has_valid_api_key(settings.llm_api_key)
    with pytest.raises(RuntimeError):
        await evaluate_turn_with_jev("یه لپ‌تاپ سبک میخوام")
    with pytest.raises(RuntimeError):
        await embed_text_async("وزن دستگاه")


@pytest.mark.asyncio
async def test_us1_selective_cross_category_trait_transfer_and_zero_false_badges(monkeypatch):
    """Verify SC-001, SC-002 & SC-003: Selective cross-category transfer (`0%` leak) + `0%` hallucinated badges."""
    stored_traits = [
        {
            "trait_id": 1,
            "source_category": "لپ‌تاپ و نوت‌بوک",
            "aspect": "حافظه رم",
            "preference": "حداقل ۳۲ گیگابایت رم",
            "strength": 0.90,
        },
        {
            "trait_id": 2,
            "source_category": "لپ‌تاپ و نوت‌بوک",
            "aspect": "وزن و حمل‌پذیری",
            "preference": "سبک و خوش‌دست برای جابه‌جایی روزانه",
            "strength": 0.85,
        },
        {
            "trait_id": 3,
            "source_category": "تجهیزات کوهنوردی",
            "aspect": "شارژدهی و دوام انرژی",
            "preference": "شارژدهی طولانی در سفر",
            "strength": 0.80,
        },
    ]
    stored_priors = {
        "لپ‌تاپ و نوت‌بوک": {"pct": 0.80, "n": 4},
        "ماگ و لیوان": {"pct": 0.20, "n": 2},
    }

    async def fake_decision(state_payload, questions):
        # Single parallel Turn-1 pass or Layer-1 product pass
        if "intent_choice" in questions:
            return {
                "intent_choice": {"choice": "store_ranking", "confidence": 0.92},
                "price_tier": {"choice": "mid", "confidence": 0.88},
                "needs_clarification": {"noul": 0.10, "confidence": 0.90},
                "user_dissatisfied": {"noul": 0.02, "confidence": 0.95},
                "is_ephemeral_or_gift": {"noul": 0.04, "confidence": 0.94},
                "require_open_now": {"noul": 0.05, "confidence": 0.90},
                "require_installment": {"noul": 0.05, "confidence": 0.90},
                "require_warranty": {"noul": 0.05, "confidence": 0.90},
                "w_price": {"score": 0.0, "confidence": 0.88},
                "w_distance": {"score": 0.0, "confidence": 0.88},
                "w_open_now": {"score": 0.0, "confidence": 0.88},
                "w_trust_freshness": {"score": 0.0, "confidence": 0.88},
                "w_installment": {"score": 0.0, "confidence": 0.88},
                "w_offer_custom": {"score": 0.0, "confidence": 0.88},
                # 32GB laptop RAM rejected (`0.04 < 0.72`), lightweight (`0.89`) & battery (`0.93`) transferred!
                "trait_transfer_0": {"noul": 0.04, "confidence": 0.95},
                "trait_transfer_1": {"noul": 0.89, "confidence": 0.92},
                "trait_transfer_2": {"noul": 0.93, "confidence": 0.92},
                "price_prior_transfer_0": {"noul": 0.86, "confidence": 0.90},
                "price_prior_transfer_1": {"noul": 0.08, "confidence": 0.90},
            }
        # Layer-1 candidate product scoring + semantic trait attribution
        return {
            "prod_0": {"score": 2.4, "confidence": 0.90},
            "prod_0_trait_0": {"noul": 0.91, "confidence": 0.92},  # 6000mAh satisfies high battery!
            "prod_0_trait_1": {"noul": 0.82, "confidence": 0.90},
            "prod_1": {"score": 2.4, "confidence": 0.90},
            "prod_1_trait_0": {"noul": 0.12, "confidence": 0.90},  # 3000mAh does NOT satisfy!
            "prod_1_trait_1": {"noul": 0.18, "confidence": 0.90},
        }

    async def fake_llm(message, session_context=None):
        return {
            "product_search_query": "گوشی موبایل",
            "catalog_search_terms": ["باتری قوی", "فست شارژ"],
            "category_keywords": ["گوشی موبایل"],
            "is_accessory_request": False,
            "custom_offer_criterion": "",
            "extracted_traits": [],
            "clarification_questions": [],
            "min_price_toman": None,
            "max_price_toman": None,
        }

    monkeypatch.setattr(jev_engine, "_call_decision_model", fake_decision)
    monkeypatch.setattr(jev_engine, "_extract_entities_with_llm", fake_llm)

    turn_eval = await evaluate_turn_with_jev(
        "یه گوشی خوب برای کارای روزانه میخوام",
        stored_user_traits=stored_traits,
        stored_price_priors=stored_priors,
    )
    transferred_prefs = [t["preference"] for t in turn_eval.transferred_traits]
    assert "حداقل ۳۲ گیگابایت رم" not in transferred_prefs  # 0% incompatible scale leak
    assert len(transferred_prefs) == 2
    assert turn_eval.catalog_search_terms == ["باتری قوی", "فست شارژ"]
    assert turn_eval.inferred_price_percentile == 0.80

    candidates = [
        {
            "product_id": "p_high_tier",
            "title": "گوشی مدل الف",
            "category_name": "گوشی موبایل",
            "min_price_toman": 42_000_000,
            "max_price_toman": 45_000_000,
            "store_count": 12,
            "specs": {"ظرفیت باتری": "6000 میلی‌آمپر ساعت", "وزن": "179 گرم"},
            "category_p10_price": 10_000_000,
            "category_p90_price": 50_000_000,
        },
        {
            "product_id": "p_entry_tier",
            "title": "گوشی مدل ب",
            "category_name": "گوشی موبایل",
            "min_price_toman": 14_000_000,
            "max_price_toman": 15_000_000,
            "store_count": 12,
            "specs": {"ظرفیت باتری": "3000 میلی‌آمپر ساعت", "وزن": "235 گرم"},
            "category_p10_price": 10_000_000,
            "category_p90_price": 50_000_000,
        },
    ]
    ranked_prods = await score_candidate_products_with_decision_model(
        user_message="یه گوشی خوب برای کارای روزانه میخوام",
        candidates=candidates,
        active_traits=turn_eval.transferred_traits,
        price_tier="mid",
        inferred_price_percentile=turn_eval.inferred_price_percentile,
        limit=4,
    )
    # Domain price prior (0.80) gently boosts the 80th-percentile product above the 10th-percentile tie
    assert ranked_prods[0]["product_id"] == "p_high_tier"
    assert len(ranked_prods[0]["matched_traits"]) == 2
    assert ranked_prods[1]["matched_traits"] == []  # Zero forced trait fallback!

    cards = _build_recommended_product_cards(ranked_prods)
    assert any("منطبق با ترجیح شما" in pro for pro in cards[0].pros_fa)
    assert all("منطبق با ترجیح شما" not in pro for pro in cards[1].pros_fa)
    assert "هماهنگ با سلیقه شما" not in cards[1].best_for_fa


@pytest.mark.asyncio
async def test_us2_five_plus_one_store_fusion_custom_slot_and_pareto_top3(monkeypatch):
    """Verify SC-004: Exact .env threshold (0.35), >=80% single priority, conditional 6th slot, and [0,1,2] Pareto."""
    profile = build_default_profile("usr_us2")
    profile["store_weights"]["w_installment"] = 0.85

    # 1. Sub-threshold jitter (0.25 < 0.35) MUST NOT trigger Sparse Override (fixing old min(..., 0.18) bug!)
    noisy_judgments = {
        "w_price": ScoreJudgment(score=0.25, confidence=0.80),
        "w_distance": ScoreJudgment(score=0.10, confidence=0.80),
        "w_open_now": ScoreJudgment(score=0.0, confidence=0.80),
        "w_trust_freshness": ScoreJudgment(score=0.0, confidence=0.80),
        "w_installment": ScoreJudgment(score=0.0, confidence=0.80),
    }
    _, l1_prior, _ = fuse_and_normalize_weights(profile, noisy_judgments)
    assert l1_prior["w_installment"] > l1_prior["w_price"]  # Stored profile prior is honored!

    # 2. Single explicit store criterion (`0.95 >= 0.35`) receives >= 80% normalized weight
    explicit_cheap = {
        "w_price": ScoreJudgment(score=0.95, confidence=0.94),
        "w_distance": ScoreJudgment(score=0.0, confidence=0.88),
        "w_open_now": ScoreJudgment(score=0.0, confidence=0.88),
        "w_trust_freshness": ScoreJudgment(score=0.0, confidence=0.88),
        "w_installment": ScoreJudgment(score=0.0, confidence=0.88),
    }
    slots_5, l1_cheap, _ = fuse_and_normalize_weights(profile, explicit_cheap)
    assert len(slots_5) == 5
    assert math.isclose(sum(l1_cheap.values()), 1.0, abs_tol=1e-5)
    assert l1_cheap["w_price"] >= 0.80

    # 3. Conditional 6th Slot (`w_offer_custom`) activates ONLY when `include_custom_offer=True`
    custom_judgments = {
        **explicit_cheap,
        "w_offer_custom": ScoreJudgment(score=0.90, confidence=0.92),
    }
    slots_6, l1_6, _ = fuse_and_normalize_weights(
        profile,
        custom_judgments,
        include_custom_offer=True,
        custom_offer_label_fa="شرط خاص: پاساژ چارسو",
    )
    assert len(slots_6) == 6
    assert slots_6[-1].slot == 6 and slots_6[-1].key == "w_offer_custom"
    assert math.isclose(sum(l1_6.values()), 1.0, abs_tol=1e-5)

    call_counter = {"count": 0}

    async def fake_offer_decision(state_payload, questions):
        call_counter["count"] += 1
        assert len(questions) <= settings.recsys_custom_offer_top_k
        return {k: {"score": 3.0 if k == "offer_3" else 0.3, "confidence": 0.90} for k in questions}

    monkeypatch.setattr(jev_engine, "_call_decision_model", fake_offer_decision)

    # Empty criterion -> 0 Decision Model calls
    raw_offers = [
        {
            "offer_id": f"off_{i}",
            "product_id": "p1",
            "product_name": "محصول تست",
            "shop_id": f"s_{i}",
            "shop_name": f"فروشگاه {i}",
            "price_toman": 20_000_000 + i * 500_000,
            "distance_km": 1.0 + i,
            "driving_minutes": 10,
            "walking_minutes": 25,
            "latitude": 35.72,
            "longitude": 51.40,
            "address": "تهران",
            "mall_micro_guide": {},
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۱",
            "freshness_badge_fa": "امروز",
            "freshness_age_days": 0.5,
            "has_official_warranty": True,
            "has_in_person_installment": i == 0,
            "installment_providers": ["ترب‌پی"] if i == 0 else [],
            "is_real_torob_shop": i == 0,
            "is_category_fallback": False,
        }
        for i in range(18)
    ]
    await score_custom_offer_criterion_with_decision_model("", raw_offers)
    assert call_counter["count"] == 0

    scored_custom_offers = await score_custom_offer_criterion_with_decision_model("پاساژ چارسو با مهلت تست", raw_offers)
    assert call_counter["count"] == 1
    assert scored_custom_offers[3]["f_offer_custom"] == 1.0
    assert scored_custom_offers[17]["f_offer_custom"] == 0.25  # Beyond Top-15 receives neutral baseline

    # 4. Physical Pareto Top-3 placement at indices [0, 1, 2] even when closest_open / lowest_price have lower utility
    pareto_pool = [
        dict(raw_offers[0], offer_id="best_u", price_toman=21_000_000, distance_km=3.0, has_in_person_installment=True),
        dict(raw_offers[1], offer_id="mid_1", price_toman=21_200_000, distance_km=3.2, has_in_person_installment=True),
        dict(raw_offers[2], offer_id="mid_2", price_toman=21_300_000, distance_km=3.5, has_in_person_installment=True),
        dict(raw_offers[3], offer_id="closest_4", price_toman=24_500_000, distance_km=0.2, has_in_person_installment=False),
        dict(raw_offers[4], offer_id="cheapest_5", price_toman=19_500_000, distance_km=14.0, has_in_person_installment=False),
    ]
    ranked = score_and_rank_offers(
        pareto_pool,
        l1_weights=l1_normalize_weights({"w_installment": 0.70, "w_trust_freshness": 0.30}),
        hard_constraints=HardConstraintsState(),
    )
    assert ranked[0].offer_id == "best_u" and ranked[0].pareto_role == "best_overall"
    assert ranked[1].offer_id == "closest_4" and ranked[1].pareto_role == "closest_open"
    assert ranked[2].offer_id == "cheapest_5" and ranked[2].pareto_role == "lowest_price"

    # 5. Category-neutral clarification card + dynamic custom questions
    card = build_clarification_card(
        "چادر مسافرتی و کمپینگ",
        clarification_round=1,
        custom_questions=[
            {
                "id": "capacity",
                "title": "ظرفیت نفرات",
                "question": "چادر را برای چند نفر می‌خواهید؟",
                "options": ["۲ تا ۴ نفره سبک", "۶ تا ۸ نفره خانوادگی", "تک‌نفره حرفه‌ای"],
            }
        ],
    )
    assert all("۱۸ ماهه" not in opt for q in card.questions for opt in q.options)
    assert any(q.id == "capacity" for q in card.questions)

    # Anti-fatigue cap verification
    ask1, c1 = should_trigger_clarification(effective_confidence=0.30, clarification_count=0)
    ask2, c2 = should_trigger_clarification(effective_confidence=0.30, clarification_count=c1)
    ask3, c3 = should_trigger_clarification(effective_confidence=0.50, clarification_count=c2, explicit_thumbs_down=True)
    ask4, c4 = should_trigger_clarification(effective_confidence=0.20, clarification_count=c3, explicit_thumbs_down=True)
    assert (ask1, c1) == (True, 1)
    assert (ask2, c2) == (False, 1)
    assert (ask3, c3) == (True, 2)
    assert (ask4, c4) == (False, 2)


@pytest.mark.asyncio
async def test_us3_gift_shield_top2_trait_inertia_and_contrastive_consolidation():
    """Verify SC-005: Gift shield (`0%` mutation), Top-2 per-aspect `strength` inertia, and contrastive store/price learning."""
    _MEMORY_TRAITS.clear()
    unit_vec = [1.0] + [0.0] * (settings.embedding_dim - 1)
    assert math.isclose(cosine_similarity(unit_vec, unit_vec), 1.0, abs_tol=1e-6)

    # 1. Gift / Ephemeral shield blocks trait persistence even when `is_durable=True` on raw extracted item
    gift_res = await sync_user_traits(
        user_id="usr_gift_shield",
        source_category="ساعت مچی",
        extracted_traits=[ExtractedTrait(aspect="سبک طراحی", preference="کلاسیک عقربه‌ای", is_durable=True)],
        pg_pool=None,
        is_ephemeral_or_gift=True,
    )
    assert gift_res == []
    assert await fetch_user_traits(None, "usr_gift_shield") == []

    # 2. Top-2 per-aspect `strength` inertia (`0.35` confirmed vs `0.15` soft, `0.92` rival decay)
    uid = "usr_inertia_top2"
    r1 = await upsert_user_trait_with_inertia(
        None, uid, "کفش ورزشی", "برند مورد علاقه", "نایکی (Nike)", unit_vec, alpha=0.35
    )
    r1 = await upsert_user_trait_with_inertia(
        None,
        uid,
        "کفش ورزشی",
        "برند مورد علاقه",
        "نایکی (Nike)",
        unit_vec,
        alpha=0.35,
        matched_aspect_rows=[r1],
        same_preference_trait_id=r1["trait_id"],
    )
    nike_strength_before = r1["strength"]
    assert nike_strength_before > 0.55

    # Single competing brand ('اسیکس') with soft turn step (`0.15`) MUST NOT erase established Nike preference!
    r2 = await upsert_user_trait_with_inertia(
        None,
        uid,
        "کفش ورزشی",
        "برند مورد علاقه",
        "اسیکس (Asics)",
        unit_vec,
        alpha=0.15,
        matched_aspect_rows=[r1],
    )
    stored_two = await fetch_user_traits(None, uid)
    assert len(stored_two) == 2
    assert stored_two[0]["preference"] == "نایکی (Nike)"  # Established preference stays #1!
    assert math.isclose(stored_two[0]["strength"], round(nike_strength_before * settings.recsys_trait_rival_decay, 4), abs_tol=1e-3)
    assert stored_two[1]["preference"] == "اسیکس (Asics)"

    # Adding a 3rd confirmed brand ('آدیداس', alpha=0.35) prunes the weakest 3rd stance ('اسیکس') keeping Top-2
    await upsert_user_trait_with_inertia(
        None,
        uid,
        "کفش ورزشی",
        "برند مورد علاقه",
        "آدیداس (Adidas)",
        unit_vec,
        alpha=0.35,
        matched_aspect_rows=stored_two,
    )
    stored_after_3rd = await fetch_user_traits(None, uid)
    assert len(stored_after_3rd) == 2
    prefs_after_3rd = {t["preference"] for t in stored_after_3rd}
    assert prefs_after_3rd == {"نایکی (Nike)", "آدیداس (Adidas)"}

    # 3. Contrastive store weight update & open-category price percentile update
    profile = build_default_profile("usr_contrastive_003")
    orig_dist = profile["store_weights"]["w_distance"]
    updated = update_store_weights_contrastive(
        profile,
        selected_features={"f_distance": 0.95, "f_price": 0.35},
        shown_features_list=[
            {"f_distance": 0.95, "f_price": 0.35},
            {"f_distance": 0.25, "f_price": 0.95},
        ],
    )
    assert updated["store_weights"]["w_distance"] > orig_dist
    assert 0.10 <= updated["store_weights"]["w_price"] <= 1.00

    updated = update_category_price_percentile(updated, "کفش ورزشی", 0.75)
    updated = update_category_price_percentile(updated, "کفش ورزشی", 0.85)
    assert updated["price_percentiles"]["کفش ورزشی"]["n"] == 2
    assert 0.75 < updated["price_percentiles"]["کفش ورزشی"]["pct"] <= 0.85
