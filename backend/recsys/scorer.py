"""15-Parameter Utility Scorer, Dealbreaker Hurdle Phi(i), Value-of-Travel Coupling, and Pareto Top-3 Selector.

Evaluates:
U(u, q, i) = Phi(i) * [ sum_{k=1..15} w_hat_k(u, q) * x_k(i, q)
                        - lambda_travel * (TravelCost_Toman(u, i) / Price_Toman(q)) ]
"""

import math
from typing import Any

from backend.config import settings
from backend.db.normalizer import to_persian_digits
from backend.models.schemas import HardConstraintsState, MallMicroGuide, ScoredStoreOffer


def _compute_feature_vector(
    offer: dict[str, Any],
    min_price: int,
    max_price: int,
    dynamic_slots: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute normalized `[0.0, 1.0]` feature values `x_k(i, q)` for all 15 slots."""
    dist_km = max(0.0, float(offer.get("distance_km", 5.0)))
    x_distance = math.exp(-dist_km / 6.0)  # 1.0 at 0km, ~0.51 at 4km, ~0.18 at 10km

    price = int(offer.get("price_toman", 0))
    if price <= 0:
        x_price = 0.50
    elif max_price > min_price:
        x_price = 1.0 - ((price - min_price) / float(max_price - min_price))
    else:
        x_price = 0.90

    raw_score = float(offer.get("shop_score", 4.5))
    votes = int(offer.get("votes_count", 15))
    prior_v = settings.recsys_bayesian_prior_votes
    bayesian_score = (votes * raw_score + prior_v * 4.2) / float(votes + prior_v)
    x_score = max(0.0, min(1.0, (bayesian_score - 1.0) / 4.0))

    x_open_now = 1.0 if offer.get("is_open_now") else 0.15

    age_days = max(0.0, float(offer.get("freshness_age_days", 3.0)))
    x_freshness = math.exp(-age_days / max(1.0, settings.recsys_freshness_half_life_days))

    x_installment = 1.0 if offer.get("has_in_person_installment") else 0.0
    x_warranty = 1.0 if offer.get("has_official_warranty") else 0.10
    x_mall = 1.0 if (offer.get("mall_micro_guide") or {}).get("mall_name") else 0.25
    x_verified = 1.0 if offer.get("is_real_torob_shop") else 0.30
    x_delivery = 1.0 if offer.get("supports_fast_delivery") else 0.20

    features = {
        "w_distance": x_distance,
        "w_price": max(0.0, min(1.0, x_price)),
        "w_score": x_score,
        "w_open_now": x_open_now,
        "w_freshness": x_freshness,
        "w_installment": x_installment,
        "w_warranty": x_warranty,
        "w_mall_cluster": x_mall,
        "w_verified_shop": x_verified,
        "w_delivery_backup": x_delivery,
    }

    # Dynamic Spec Slots (11..15)
    specs_blob = " ".join(
        [str(offer.get("product_name") or ""), json.dumps(offer.get("specs") or {}, ensure_ascii=False)]
    ) if isinstance(offer.get("specs"), dict) else str(offer.get("product_name") or "")
    for dyn in dynamic_slots:
        f_key = str(dyn.get("feature_key") or "")
        label = str(dyn.get("label_fa") or "")
        tokens = [t for t in label.split() if len(t) >= 3]
        matched = any(t in specs_blob for t in tokens) if tokens else True
        features[f_key] = 0.92 if matched else 0.45

    return features


import json


def compute_hurdle_multiplier(offer: dict[str, Any], hard_constraints: HardConstraintsState) -> float:
    """Compute Dealbreaker Hurdle Multiplier `Phi(i) in {1.0, RECSYS_HURDLE_PENALTY_MULTIPLIER}`."""
    penalty = settings.recsys_hurdle_penalty_multiplier
    if hard_constraints.require_open_now and not offer.get("is_open_now"):
        return penalty
    if hard_constraints.require_installment and not offer.get("has_in_person_installment"):
        return penalty
    if hard_constraints.require_warranty and not offer.get("has_official_warranty"):
        return penalty
    return 1.0


def build_why_this_shop_fa(
    offer: dict[str, Any],
    contributions: dict[str, float],
) -> list[str]:
    """Generate explainable Persian attribution chips from top weighted contributions."""
    reasons: list[str] = []
    dist_km = offer.get("distance_km", 0.0)
    drive_m = offer.get("driving_minutes", 5)

    top_keys = [k for k, _ in sorted(contributions.items(), key=lambda item: item[1], reverse=True)]
    for k in top_keys:
        if len(reasons) >= 3:
            break
        if k == "w_distance":
            reasons.append(f"{to_persian_digits(dist_km)} کیلومتر فاصله ({to_persian_digits(drive_m)} دقیقه)")
        elif k == "w_price" and offer.get("price_toman", 0) > 0:
            price_fmt = to_persian_digits(f"{int(offer['price_toman']):,}")
            reasons.append(f"قیمت رقابتی ({price_fmt} تومان)")
        elif k == "w_installment" and offer.get("has_in_person_installment"):
            provs = " و ".join((offer.get("installment_providers") or ["ترب‌پی"])[:2])
            reasons.append(f"پرداخت اقساطی حضوری ({provs})")
        elif k == "w_open_now" and offer.get("is_open_now"):
            reasons.append(f"هم‌اکنون باز ({offer.get('today_hours_fa', '')})")
        elif k == "w_warranty" and offer.get("has_official_warranty"):
            reasons.append(offer.get("warranty_provider") or "گارانتی معتبر شرکتی")
        elif k == "w_verified_shop" and offer.get("is_real_torob_shop"):
            reasons.append("فروشگاه رسمی تاییدشده ترب")
        elif k == "w_mall_cluster" and (offer.get("mall_micro_guide") or {}).get("mall_name"):
            reasons.append(f"مستقر در {offer['mall_micro_guide']['mall_name']}")

    if not reasons:
        reasons.append(f"{to_persian_digits(dist_km)} کیلومتر فاصله ({to_persian_digits(drive_m)} دقیقه)")
    if offer.get("freshness_badge_fa") and len(reasons) < 3:
        reasons.append(str(offer["freshness_badge_fa"]))
    return reasons[:3]


def score_and_rank_offers(
    candidates: list[dict[str, Any]],
    l1_weights: dict[str, float],
    hard_constraints: HardConstraintsState,
    dynamic_slots: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> list[ScoredStoreOffer]:
    """Score candidate store offers using the 15-parameter utility function and assign Pareto Top-3 roles."""
    if not candidates:
        return []

    dyn_list = dynamic_slots or []
    positive_prices = [int(c["price_toman"]) for c in candidates if int(c.get("price_toman", 0)) > 0]
    min_price = min(positive_prices) if positive_prices else 1_000_000
    max_price = max(positive_prices) if positive_prices else 1_000_000

    scored_items: list[tuple[float, dict[str, Any], list[str]]] = []
    for cand in candidates:
        feats = _compute_feature_vector(cand, min_price=min_price, max_price=max_price, dynamic_slots=dyn_list)
        contributions = {k: l1_weights.get(k, 0.0) * val for k, val in feats.items()}
        linear_utility = sum(contributions.values())

        # Enhancement 2: Net Value-of-Travel Coupling
        # Travelling 10km for a 200k Toman cable hurts utility much more than travelling 10km for a 50M Toman phone
        ref_price = max(250_000, int(cand.get("price_toman") or min_price))
        travel_cost_toman = float(cand.get("distance_km", 0.0)) * float(settings.recsys_travel_cost_per_km_toman)
        travel_penalty = settings.recsys_travel_coupling_lambda * min(0.35, travel_cost_toman / float(ref_price))

        phi = compute_hurdle_multiplier(cand, hard_constraints)
        final_u = max(0.05, min(0.99, phi * max(0.05, linear_utility - travel_penalty)))
        reasons = build_why_this_shop_fa(cand, contributions)
        scored_items.append((final_u, cand, reasons))

    scored_items.sort(key=lambda item: item[0], reverse=True)
    top_n = limit or settings.top_ranked_stores_limit
    selected = scored_items[:top_n]

    # Enhancement 4: Pareto-Front Top-3 Diversity Assignment
    # #1 Best Overall Utility, #2 Closest Open Store, #3 Lowest Price Store
    best_overall_id = selected[0][1]["offer_id"] if selected else None

    open_candidates = [item for item in selected[1:] if item[1].get("is_open_now")]
    closest_open_id = (
        min(open_candidates, key=lambda x: x[1]["distance_km"])[1]["offer_id"]
        if open_candidates
        else None
    )

    price_candidates = [
        item
        for item in selected[1:]
        if item[1]["offer_id"] != closest_open_id and int(item[1].get("price_toman", 0)) > 0
    ]
    lowest_price_id = (
        min(price_candidates, key=lambda x: x[1]["price_toman"])[1]["offer_id"]
        if price_candidates
        else None
    )

    results: list[ScoredStoreOffer] = []
    for u_val, cand, reasons in selected:
        oid = cand["offer_id"]
        if oid == best_overall_id:
            role = "best_overall"
            badge = "بهترین انتخاب کلی"
        elif oid == closest_open_id:
            role = "closest_open"
            badge = "نزدیک‌ترین مغازه باز"
        elif oid == lowest_price_id:
            role = "lowest_price"
            badge = "کمترین قیمت ثبت‌شده"
        else:
            role = "standard"
            badge = None

        mall_raw = cand.get("mall_micro_guide") or {}
        results.append(
            ScoredStoreOffer(
                offer_id=oid,
                product_id=cand["product_id"],
                product_name=cand["product_name"],
                shop_id=cand["shop_id"],
                shop_name=cand["shop_name"],
                price_toman=int(cand.get("price_toman", 0)),
                utility_score=max(10, min(99, int(round(u_val * 100)))),
                pareto_role=role,
                pareto_badge_fa=badge,
                why_this_shop_fa=reasons,
                distance_km=float(cand.get("distance_km", 0.0)),
                driving_minutes=int(cand.get("driving_minutes", 5)),
                walking_minutes=int(cand.get("walking_minutes", 15)),
                latitude=float(cand.get("latitude", settings.default_user_lat)),
                longitude=float(cand.get("longitude", settings.default_user_lng)),
                address=str(cand.get("address") or "تهران"),
                mall_micro_guide=MallMicroGuide(
                    mall_name=mall_raw.get("mall_name"),
                    floor_label=mall_raw.get("floor_label"),
                    unit_label=mall_raw.get("unit_label"),
                    note_fa=mall_raw.get("note_fa"),
                ),
                is_open_now=bool(cand.get("is_open_now", True)),
                today_hours_fa=str(cand.get("today_hours_fa") or "۱۰:۰۰ تا ۲۱:۰۰"),
                last_price_changed_at=cand.get("last_price_changed_at"),
                freshness_badge_fa=str(cand.get("freshness_badge_fa") or "بروزرسانی اخیر"),
                shop_score=float(cand.get("shop_score", 4.5)),
                votes_count=int(cand.get("votes_count", 15)),
                has_official_warranty=bool(cand.get("has_official_warranty", False)),
                warranty_provider=cand.get("warranty_provider"),
                has_in_person_installment=bool(cand.get("has_in_person_installment", False)),
                installment_providers=list(cand.get("installment_providers") or []),
                primary_phone=str(cand.get("primary_phone") or ""),
                is_real_torob_shop=bool(cand.get("is_real_torob_shop", False)),
                instagram=cand.get("instagram"),
                website_url=cand.get("website_url"),
                is_category_fallback=bool(cand.get("is_category_fallback", False)),
            )
        )

    return results
