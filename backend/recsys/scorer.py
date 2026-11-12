"""5-Criteria Orthogonal Store Utility Scorer, Dealbreaker Hurdle Phi(i), and Pareto Top-3 Selector.

Evaluates (`specs/002-jev-domain-recsys/`):
U(u, q, i) = Phi(i) * sum_{k=1..5} w_hat_k(u, q) * f_{i,k}

Where:
- `f_{i,1}` (`w_price`): Outlier-resistant relative exponential decay `exp(-(P_i - P_min) / (0.15 * P_min))`
- `f_{i,2}` (`w_distance`): Exponential urban distance decay `exp(-d_i / 8.0)`
- `f_{i,3}` (`w_open_now`): Open status (`1.0` open, `0.4` unknown hours, `0.0` closed)
- `f_{i,4}` (`w_trust_freshness`): `0.65 * exp(-age_days / 14.0) + 0.20 * I(is_real_shop) + 0.15 * I(has_warranty)`
- `f_{i,5}` (`w_installment`): Verified in-person installment availability (`1.0` or `0.0`)
"""

import math
from typing import Any

from backend.config import settings
from backend.db.normalizer import to_persian_digits
from backend.models.schemas import HardConstraintsState, MallMicroGuide, ScoredStoreOffer


def _compute_feature_vector(
    offer: dict[str, Any],
    min_price: int,
    max_price: int | None = None,
    dynamic_slots: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Compute normalized `[0.0, 1.0]` feature values `f_{i,k}` for the 5 orthogonal store criteria."""
    # 1. Price Advantage (Outlier-resistant relative exponential decay anchored at floor price P_min)
    price = int(offer.get("price_toman", 0))
    tau_price = max(0.01, float(settings.recsys_price_decay_ratio))
    if price <= 0 or min_price <= 0:
        f_price = 0.50
    else:
        delta_ratio = max(0.0, float(price - min_price) / float(min_price))
        f_price = math.exp(-delta_ratio / tau_price)

    # 2. Proximity / Distance in Tehran
    dist_km = max(0.0, float(offer.get("distance_km", 5.0)))
    tau_dist = max(0.5, float(settings.recsys_distance_decay_km))
    f_distance = math.exp(-dist_km / tau_dist)

    # 3. Open-Now Status
    if offer.get("is_open_now") is True:
        f_open_now = 1.0
    elif offer.get("today_hours_fa") in (None, "", "نامشخص"):
        f_open_now = 0.40
    else:
        f_open_now = 0.0

    # 4. Price Freshness & Shop Trust
    age_days = max(0.0, float(offer.get("freshness_age_days", 3.0)))
    half_life = max(1.0, float(settings.recsys_freshness_half_life_days))
    fresh_part = math.exp(-age_days / half_life)
    real_part = 1.0 if offer.get("is_real_torob_shop") else 0.0
    warr_part = 1.0 if offer.get("has_official_warranty") else 0.0
    f_trust_freshness = 0.65 * fresh_part + 0.20 * real_part + 0.15 * warr_part

    # 5. In-Person Installment / Credit
    f_installment = 1.0 if offer.get("has_in_person_installment") else 0.0

    return {
        "w_price": max(0.0, min(1.0, f_price)),
        "w_distance": max(0.0, min(1.0, f_distance)),
        "w_open_now": max(0.0, min(1.0, f_open_now)),
        "w_trust_freshness": max(0.0, min(1.0, f_trust_freshness)),
        "w_installment": max(0.0, min(1.0, f_installment)),
        "f_price": max(0.0, min(1.0, f_price)),
        "f_distance": max(0.0, min(1.0, f_distance)),
        "f_open_now": max(0.0, min(1.0, f_open_now)),
        "f_trust_freshness": max(0.0, min(1.0, f_trust_freshness)),
        "f_installment": max(0.0, min(1.0, f_installment)),
        # Legacy aliases mapped cleanly for backward-compatible callers
        "w_freshness": fresh_part,
        "w_score": f_trust_freshness,
        "w_warranty": warr_part,
        "w_verified_shop": real_part,
    }


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
        elif k in ("w_trust_freshness", "w_warranty", "w_verified_shop", "w_freshness"):
            if offer.get("is_real_torob_shop"):
                reasons.append("فروشگاه رسمی تاییدشده ترب")
            elif offer.get("has_official_warranty"):
                reasons.append(offer.get("warranty_provider") or "گارانتی معتبر شرکتی")

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
    """Score candidate store offers using the 5-criteria utility function and assign Pareto Top-3 roles."""
    if not candidates:
        return []

    positive_prices = [int(c["price_toman"]) for c in candidates if int(c.get("price_toman", 0)) > 0]
    min_price = min(positive_prices) if positive_prices else 1_000_000

    scored_items: list[tuple[float, dict[str, Any], list[str], dict[str, float]]] = []
    for cand in candidates:
        feats = _compute_feature_vector(cand, min_price=min_price)
        contributions = {k: float(w) * feats.get(k, 0.0) for k, w in l1_weights.items() if k in feats}
        linear_utility = sum(contributions.values())

        phi = compute_hurdle_multiplier(cand, hard_constraints)
        final_u = max(0.05, min(0.99, phi * max(0.05, linear_utility)))
        reasons = build_why_this_shop_fa(cand, contributions)
        scored_items.append((final_u, cand, reasons, feats))

    scored_items.sort(key=lambda item: item[0], reverse=True)
    top_n = limit or settings.top_ranked_stores_limit
    selected = scored_items[:top_n]

    # Pareto-Front Top-3 Diversity Assignment:
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
    for u_val, cand, reasons, feats in selected:
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
                feature_scores={k: round(float(v), 4) for k, v in feats.items() if k.startswith("f_")},
            )
        )

    return results
