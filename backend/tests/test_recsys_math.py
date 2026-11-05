"""Phase 3 self-check: verify 15-Parameter RecSys math, Two-Layer L1 normalization, deduplication, hurdles, and anti-fatigue gate."""

import math
import pytest

from backend.config import settings
from backend.db.profiles import build_default_profile
from backend.models.schemas import HardConstraintsState
from backend.recsys.clarifier import (
    build_clarification_card,
    map_clarification_answers_to_deltas,
    should_trigger_clarification,
)
from backend.recsys.deduplicator import cosine_similarity, upsert_dynamic_spec_slots
from backend.recsys.jev_engine import (
    CandidateDynamicSpec,
    deterministic_text_embedding,
    evaluate_turn_with_jev,
)
from backend.recsys.scorer import score_and_rank_offers
from backend.recsys.weights import (
    fuse_and_normalize_weights,
    l1_normalize_weights,
    update_profile_ema_unconstrained,
)


@pytest.mark.asyncio
async def test_two_layer_normalization_and_situational_adaptation():
    """Verify SC-003: Handsfree (Fast) vs. Phone (Cheap) adaptation and sum(w_hat) == 1.0 without DB dilution."""
    profile = build_default_profile("usr_math_01")
    orig_price_w = profile["base_weights"]["w_price"]

    # Query 1: Urgent handsfree ("سریع‌ترین هندزفری سیمی همین الان")
    eval_fast = await evaluate_turn_with_jev("سریع‌ترین هندزفری سیمی که همین الان باز باشه")
    slots_fast, l1_fast, _ = fuse_and_normalize_weights(profile, eval_fast.session_weights)

    assert math.isclose(sum(s.weight for s in slots_fast), 1.0, abs_tol=1e-5)
    assert math.isclose(sum(l1_fast.values()), 1.0, abs_tol=1e-5)
    assert l1_fast["w_distance"] > 2.0 * l1_fast["w_price"]

    # Update DB profile for only w_distance and verify w_price in DB is NOT diluted by L1 normalization
    profile = update_profile_ema_unconstrained(profile, explicit_deltas={"w_distance": 0.90})
    assert profile["base_weights"]["w_distance"] == 0.90
    assert profile["base_weights"]["w_price"] == orig_price_w

    # Query 2: Same user next day wants cheapest phone ("ارزان‌ترین گوشی آیفون در تهران")
    eval_cheap = await evaluate_turn_with_jev("ارزان‌ترین گوشی آیفون با کمترین قیمت در کل تهران")
    slots_cheap, l1_cheap, _ = fuse_and_normalize_weights(profile, eval_cheap.session_weights)
    assert math.isclose(sum(s.weight for s in slots_cheap), 1.0, abs_tol=1e-5)
    assert l1_cheap["w_price"] > 1.8 * l1_cheap["w_distance"]


@pytest.mark.asyncio
async def test_hybrid_deduplication_and_fixed_15_slot_capacity():
    """Verify FR-009: duplicate concepts merge (>0.80 cosine or Noul) and dynamic slots never exceed 5 (total 15)."""
    profile = build_default_profile("usr_dedup_01")

    emb1 = deterministic_text_embedding("حذف نویز میکروفون و مکالمه")
    emb2 = deterministic_text_embedding("میکروفون با قابلیت حذف نویز مکالمه")
    assert cosine_similarity(emb1, emb2) > settings.recsys_dedup_cosine_high_threshold

    # Insert first dynamic feature
    c1 = CandidateDynamicSpec(
        feature_key="spec_anc_1",
        label_fa="حذف نویز میکروفون و مکالمه",
        category_name="هدفون",
        weight=0.80,
        confidence=0.85,
    )
    profile = await upsert_dynamic_spec_slots(profile, [c1])
    assert len(profile["dynamic_slots"]) == 1

    # Insert semantically duplicate feature -> must merge into slot 11 rather than creating slot 12
    c1_dup = CandidateDynamicSpec(
        feature_key="spec_anc_2",
        label_fa="میکروفون با قابلیت حذف نویز مکالمه",
        category_name="هدفون",
        weight=0.95,
        confidence=0.92,
    )
    profile = await upsert_dynamic_spec_slots(profile, [c1_dup])
    assert len(profile["dynamic_slots"]) == 1
    assert profile["dynamic_slots"][0]["session_hits"] == 2

    # Insert 6 truly distinct specs -> must evict oldest/lowest-utility slot and cap dynamic_slots at 5
    distinct_labels = [
        ("spec_oled", "صفحه نمایش امولد ۱۲۰ هرتز"),
        ("spec_chip", "تراشه پردازنده اسنپدراگون"),
        ("spec_body", "بدنه تیتانیومی و فریم فلزی"),
        ("spec_fastcharge", "آداپتور سوپر فست شارژ ۱۰۰ وات"),
        ("spec_speaker", "بلندگو و اسپیکر استریو دالبی"),
        ("spec_fingerprint", "حسگر اثر انگشت اولتراسونیک"),
    ]
    distinct_specs = [
        CandidateDynamicSpec(key, label, "گوشی موبایل", 0.72 + i * 0.03, 0.85)
        for i, (key, label) in enumerate(distinct_labels)
    ]
    profile = await upsert_dynamic_spec_slots(profile, distinct_specs)
    assert len(profile["dynamic_slots"]) == settings.recsys_dynamic_slots
    slot_ids = [s["slot_id"] for s in profile["dynamic_slots"]]
    assert slot_ids == [11, 12, 13, 14, 15]


def test_anti_fatigue_clarification_gate():
    """Verify SC-004: Ask at most once on Turn 1 when confidence < 0.45; re-ask ONLY on ThumbsDown or Noul >= 0.70."""
    # Turn 1: Low confidence (0.30 < 0.45) and count == 0 -> triggers Round 1
    ask1, count1 = should_trigger_clarification(effective_confidence=0.30, clarification_count=0)
    assert ask1 is True and count1 == 1

    # Turn 2: Even if confidence is still low (0.32), normal turn MUST NOT ask again
    ask2, count2 = should_trigger_clarification(
        effective_confidence=0.32,
        clarification_count=count1,
        explicit_thumbs_down=False,
        dissatisfied_noul=0.20,
    )
    assert ask2 is False and count2 == 1

    # Turn 3: User clicks ThumbsDown (or dissatisfied_noul >= 0.70) -> triggers Round 2 (final retry)
    ask3, count3 = should_trigger_clarification(
        effective_confidence=0.50,
        clarification_count=count2,
        explicit_thumbs_down=True,
    )
    assert ask3 is True and count3 == 2

    # Turn 4: Hard cap at RECSYS_MAX_CLARIFICATION_ROUNDS (2) -> never asks a 3rd time
    ask4, count4 = should_trigger_clarification(
        effective_confidence=0.20,
        clarification_count=count3,
        explicit_thumbs_down=True,
        dissatisfied_noul=0.95,
    )
    assert ask4 is False and count4 == 2

    card = build_clarification_card("گوشی موبایل", clarification_round=1)
    assert len(card.options) == 3
    deltas = map_clarification_answers_to_deltas(selected_option_id="opt_fastest")
    assert deltas["w_distance"] >= 0.90


def test_hurdle_multiplier_and_pareto_top3_diversity():
    """Verify FR-010: Dealbreaker hurdle Phi(i) penalizes non-compliant stores and Pareto Top-3 roles are assigned."""
    candidates = [
        {
            "offer_id": "off_1",
            "product_id": "prod_1",
            "product_name": "گوشی سامسونگ A55",
            "shop_id": "shop_1",
            "shop_name": "موبایل ولیعصر (قسطی و باز)",
            "price_toman": 21_500_000,
            "distance_km": 1.8,
            "driving_minutes": 7,
            "walking_minutes": 20,
            "latitude": 35.72,
            "longitude": 51.40,
            "address": "تهران، ولیعصر، پاساژ نور، طبقه همکف، واحد ۱۲",
            "mall_micro_guide": {"mall_name": "پاساژ نور", "floor_label": "طبقه همکف", "unit_label": "واحد ۱۲"},
            "is_open_now": True,
            "today_hours_fa": "۱۰:۰۰ تا ۲۱:۰۰",
            "freshness_badge_fa": "بروزرسانی ۲ ساعت پیش",
            "freshness_age_days": 0.1,
            "shop_score": 4.8,
            "votes_count": 80,
            "has_official_warranty": True,
            "warranty_provider": "گارانتی ۱۸ ماهه شرکتی",
            "has_in_person_installment": True,
            "installment_providers": ["ترب‌پی", "اسنپ‌پی"],
            "is_real_torob_shop": True,
            "is_category_fallback": False,
        },
        {
            "offer_id": "off_2",
            "product_id": "prod_1",
            "product_name": "گوشی سامسونگ A55",
            "shop_id": "shop_2",
            "shop_name": "موبایل نزدیک ولی نقدی",
            "price_toman": 21_200_000,
            "distance_km": 0.4,
            "driving_minutes": 2,
            "walking_minutes": 5,
            "latitude": 35.721,
            "longitude": 51.401,
            "address": "تهران، ولیعصر",
            "mall_micro_guide": {},
            "is_open_now": True,
            "today_hours_fa": "۱۰:۰۰ تا ۲۱:۰۰",
            "freshness_badge_fa": "بروزرسانی ۱ روز پیش",
            "freshness_age_days": 1.0,
            "shop_score": 4.5,
            "votes_count": 20,
            "has_official_warranty": True,
            "warranty_provider": "گارانتی شرکتی",
            "has_in_person_installment": False,
            "installment_providers": [],
            "is_real_torob_shop": False,
            "is_category_fallback": False,
        },
        {
            "offer_id": "off_3",
            "product_id": "prod_1",
            "product_name": "گوشی سامسونگ A55",
            "shop_id": "shop_3",
            "shop_name": "موبایل ارزان جمهوری (قسطی)",
            "price_toman": 20_800_000,
            "distance_km": 5.5,
            "driving_minutes": 18,
            "walking_minutes": 65,
            "latitude": 35.69,
            "longitude": 51.40,
            "address": "تهران، جمهوری، پاساژ علاءالدین",
            "mall_micro_guide": {"mall_name": "پاساژ علاءالدین"},
            "is_open_now": True,
            "today_hours_fa": "۱۰:۰۰ تا ۲۱:۰۰",
            "freshness_badge_fa": "بروزرسانی ۳ ساعت پیش",
            "freshness_age_days": 0.2,
            "shop_score": 4.4,
            "votes_count": 30,
            "has_official_warranty": True,
            "warranty_provider": "گارانتی شرکتی",
            "has_in_person_installment": True,
            "installment_providers": ["ترب‌پی"],
            "is_real_torob_shop": False,
            "is_category_fallback": False,
        },
    ]

    l1_w = l1_normalize_weights(
        {
            "w_distance": 0.45,
            "w_price": 0.15,
            "w_installment": 0.25,
            "w_open_now": 0.15,
        }
    )
    ranked = score_and_rank_offers(
        candidates,
        l1_weights=l1_w,
        hard_constraints=HardConstraintsState(require_installment=True),
    )
    assert len(ranked) == 3
    # off_2 lacks installment so Hurdle Phi(off_2) = 0.15 pushes it to last place despite being 0.4km away
    assert ranked[0].offer_id == "off_1"
    assert ranked[-1].offer_id == "off_2"
    roles = {r.pareto_role for r in ranked}
    assert "best_overall" in roles
    assert "closest_open" in roles
    assert "lowest_price" in roles
