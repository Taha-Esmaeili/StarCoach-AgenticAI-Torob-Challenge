"""Phase 3 self-check: verify 15-Parameter RecSys math, Two-Layer L1 normalization, deduplication, hurdles, and anti-fatigue gate."""

import math
import pytest

from backend.config import settings
from backend.db.profiles import (
    _MEMORY_TRAITS,
    build_default_profile,
    fetch_domain_traits_pgvector,
    save_or_update_domain_trait,
)
from backend.models.schemas import HardConstraintsState
from backend.recsys.clarifier import (
    build_clarification_card,
    map_clarification_answers_to_deltas,
    should_trigger_clarification,
)
from backend.recsys.deduplicator import (
    cosine_similarity,
    sync_user_domain_traits,
    upsert_dynamic_spec_slots,
)
from backend.recsys.jev_engine import (
    CandidateDynamicSpec,
    ExtractedDomainTrait,
    ScoreJudgment,
    embed_text_async,
    evaluate_turn_with_jev,
    _has_valid_api_key,
)
from backend.recsys.scorer import score_and_rank_offers
from backend.recsys.weights import (
    fuse_and_normalize_weights,
    l1_normalize_weights,
    update_profile_ema_unconstrained,
    update_store_weights_contrastive,
)


@pytest.mark.asyncio
async def test_live_model_enforcement_without_simulators():
    """Verify that when no real API key is set, evaluate_turn_with_jev and embed_text_async raise RuntimeError (zero simulation)."""
    if not _has_valid_api_key(settings.llm_api_key) and not _has_valid_api_key(settings.typesafe_api_key):
        with pytest.raises(RuntimeError):
            await evaluate_turn_with_jev("یه لپ‌تاپ سبک میخوام")
        with pytest.raises(RuntimeError):
            await embed_text_async("وزن و ابعاد دستگاه")


def test_two_layer_normalization_and_situational_adaptation():
    """Verify SC-001 & SC-003: Handsfree (Fast) vs. Phone (Cheap) adaptation and sum(w_hat) == 1.0 without DB dilution."""
    profile = build_default_profile("usr_math_01")
    orig_price_w = profile["base_weights"]["w_price"]

    # Query 1: Urgent handsfree (only w_distance=0.95, w_open_now=0.55 mentioned)
    fast_judgments = {
        "w_distance": ScoreJudgment(score=0.95, confidence=0.92),
        "w_open_now": ScoreJudgment(score=0.55, confidence=0.88),
        "w_price": ScoreJudgment(score=0.0, confidence=0.85),
        "w_trust_freshness": ScoreJudgment(score=0.0, confidence=0.85),
        "w_installment": ScoreJudgment(score=0.0, confidence=0.85),
    }
    slots_fast, l1_fast, _ = fuse_and_normalize_weights(profile, fast_judgments)

    assert math.isclose(sum(s.weight for s in slots_fast), 1.0, abs_tol=1e-5)
    assert math.isclose(sum(l1_fast.values()), 1.0, abs_tol=1e-5)
    assert l1_fast["w_distance"] > 2.0 * l1_fast["w_price"]

    # Update DB profile for only w_distance and verify w_price in DB is NOT diluted by L1 normalization
    profile = update_profile_ema_unconstrained(profile, explicit_deltas={"w_distance": 0.90})
    assert profile["base_weights"]["w_distance"] == 0.90
    assert profile["base_weights"]["w_price"] == orig_price_w

    # Query 2: Same user next day wants cheapest phone (only w_price=0.95 mentioned -> gets >= 80% weight!)
    cheap_judgments = {
        "w_price": ScoreJudgment(score=0.95, confidence=0.95),
        "w_distance": ScoreJudgment(score=0.0, confidence=0.85),
        "w_open_now": ScoreJudgment(score=0.0, confidence=0.85),
        "w_trust_freshness": ScoreJudgment(score=0.0, confidence=0.85),
        "w_installment": ScoreJudgment(score=0.0, confidence=0.85),
    }
    slots_cheap, l1_cheap, _ = fuse_and_normalize_weights(profile, cheap_judgments)
    assert math.isclose(sum(s.weight for s in slots_cheap), 1.0, abs_tol=1e-5)
    assert l1_cheap["w_price"] >= 0.80


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


def test_sparse_single_criterion_weight_no_dilution_sc001():
    """Verify SC-001: Single mentioned store criterion receives >= 80% (0.80) of normalized weight."""
    profile = build_default_profile("usr_sc001")
    cheap_weights = {
        "w_price": ScoreJudgment(score=0.95, confidence=0.94),
        "w_distance": ScoreJudgment(score=0.0, confidence=0.88),
        "w_open_now": ScoreJudgment(score=0.0, confidence=0.88),
        "w_trust_freshness": ScoreJudgment(score=0.0, confidence=0.88),
        "w_installment": ScoreJudgment(score=0.0, confidence=0.88),
    }
    _, l1_cheap, _ = fuse_and_normalize_weights(profile, cheap_weights)
    assert math.isclose(sum(l1_cheap.values()), 1.0, abs_tol=1e-5)
    assert l1_cheap["w_price"] >= 0.80

    near_weights = {
        "w_price": ScoreJudgment(score=0.0, confidence=0.88),
        "w_distance": ScoreJudgment(score=0.95, confidence=0.94),
        "w_open_now": ScoreJudgment(score=0.0, confidence=0.88),
        "w_trust_freshness": ScoreJudgment(score=0.0, confidence=0.88),
        "w_installment": ScoreJudgment(score=0.0, confidence=0.88),
    }
    _, l1_near, _ = fuse_and_normalize_weights(profile, near_weights)
    assert math.isclose(sum(l1_near.values()), 1.0, abs_tol=1e-5)
    assert l1_near["w_distance"] >= 0.80


@pytest.mark.asyncio
async def test_domain_isolated_trait_memory_and_polarity_safe_dedup_sc002_sc003():
    """Verify SC-002 (100% Domain Isolation) and SC-003 (Polarity-Safe Aspect Update + Ephemeral Filter)."""
    _MEMORY_TRAITS.clear()
    user_1 = "usr_domain_digital"
    user_2 = "usr_domain_shoes"
    unit_vec = [1.0] + [0.0] * (settings.embedding_dim - 1)

    # 1. User 1 stores lightweight laptop preference in `electronics`
    row_1 = await save_or_update_domain_trait(
        pg_pool=None,
        user_id=user_1,
        domain="electronics",
        aspect="وزن و ابعاد دستگاه",
        preference="سبک، خوش‌دست و قابل‌حمل",
        aspect_embedding=unit_vec,
    )
    u1_elec_traits = await fetch_domain_traits_pgvector(None, user_1, "electronics")
    assert len(u1_elec_traits) == 1
    assert "سبک" in u1_elec_traits[0]["preference"]

    # 2. SC-003: User 1 reverses preference on the exact same aspect ("وزن و ابعاد دستگاه": سبک -> سنگین و صنعتی)
    await save_or_update_domain_trait(
        pg_pool=None,
        user_id=user_1,
        domain="electronics",
        aspect="وزن و ابعاد دستگاه",
        preference="بدنه سنگین، مستحکم و صنعتی",
        aspect_embedding=unit_vec,
        matched_trait_id=int(row_1["trait_id"]),
    )
    u1_elec_after = await fetch_domain_traits_pgvector(None, user_1, "electronics")
    assert len(u1_elec_after) == 1
    assert "سنگین" in u1_elec_after[0]["preference"]
    assert u1_elec_after[0]["hit_count"] == 2

    # 3. SC-002: User 2 stores orthopedic wide-toe shoe preference in `footwear_apparel`
    await save_or_update_domain_trait(
        pg_pool=None,
        user_id=user_2,
        domain="footwear_apparel",
        aspect="ارگونومی و ساختار کفی کفش",
        preference="کفی طبی و پنجه پهن مناسب پیاده‌روی طولانی",
        aspect_embedding=unit_vec,
    )

    # Verify strict isolation across users and domains
    assert await fetch_domain_traits_pgvector(None, user_1, "footwear_apparel") == []
    assert await fetch_domain_traits_pgvector(None, user_2, "electronics") == []
    u2_footwear = await fetch_domain_traits_pgvector(None, user_2, "footwear_apparel")
    assert len(u2_footwear) == 1
    assert "طبی" in u2_footwear[0]["preference"]

    # 4. Ephemeral gift trait (`is_durable=False`) MUST NOT be persisted by `sync_user_domain_traits`
    gift_traits = [
        ExtractedDomainTrait(
            domain="electronics",
            aspect="وزن و ابعاد دستگاه",
            preference="سبک",
            is_durable=False,
        )
    ]
    await sync_user_domain_traits("usr_gift", "electronics", gift_traits, pg_pool=None)
    assert await fetch_domain_traits_pgvector(None, "usr_gift", "electronics") == []


def test_outlier_resistant_exponential_price_decay_and_contrastive_feedback():
    """Verify outlier price does not distort f_price for normal stores, and contrastive feedback updates weights."""
    base_candidates = [
        {
            "offer_id": "off_min",
            "product_id": "p1",
            "product_name": "محصول تست",
            "shop_id": "s1",
            "shop_name": "فروشگاه اول",
            "price_toman": 20_000_000,
            "distance_km": 2.0,
            "driving_minutes": 8,
            "walking_minutes": 25,
            "latitude": 35.72,
            "longitude": 51.40,
            "address": "تهران",
            "mall_micro_guide": {},
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۱",
            "freshness_badge_fa": "امروز",
            "freshness_age_days": 0.2,
            "has_official_warranty": True,
            "has_in_person_installment": False,
            "installment_providers": [],
            "is_real_torob_shop": True,
            "is_category_fallback": False,
        },
        {
            "offer_id": "off_mid",
            "product_id": "p1",
            "product_name": "محصول تست",
            "shop_id": "s2",
            "shop_name": "فروشگاه دوم",
            "price_toman": 21_000_000,
            "distance_km": 2.0,
            "driving_minutes": 8,
            "walking_minutes": 25,
            "latitude": 35.72,
            "longitude": 51.40,
            "address": "تهران",
            "mall_micro_guide": {},
            "is_open_now": True,
            "today_hours_fa": "۱۰ تا ۲۱",
            "freshness_badge_fa": "امروز",
            "freshness_age_days": 0.2,
            "has_official_warranty": True,
            "has_in_person_installment": False,
            "installment_providers": [],
            "is_real_torob_shop": True,
            "is_category_fallback": False,
        },
    ]
    outlier_candidate = dict(base_candidates[1], offer_id="off_outlier", shop_id="s99", price_toman=99_000_000)

    weights = {"w_price": 1.0}
    ranked_normal = score_and_rank_offers(base_candidates, l1_weights=weights, hard_constraints=HardConstraintsState())
    ranked_outlier = score_and_rank_offers(
        [*base_candidates, outlier_candidate],
        l1_weights=weights,
        hard_constraints=HardConstraintsState(),
    )

    f_mid_normal = next(r for r in ranked_normal if r.offer_id == "off_mid").feature_scores["f_price"]
    f_mid_outlier = next(r for r in ranked_outlier if r.offer_id == "off_mid").feature_scores["f_price"]
    assert math.isclose(f_mid_normal, f_mid_outlier, abs_tol=1e-6)

    # Verify Contrastive Revealed-Preference update (SC-005)
    profile = build_default_profile("usr_contrastive")
    orig_dist = profile["base_weights"]["w_distance"]
    updated = update_store_weights_contrastive(
        profile,
        selected_features={"f_distance": 0.95, "f_price": 0.40},
        shown_features_list=[
            {"f_distance": 0.95, "f_price": 0.40},
            {"f_distance": 0.30, "f_price": 0.95},
        ],
    )
    assert updated["base_weights"]["w_distance"] > orig_dist
