"""5+1 Orthogonal Store Utility Scorer, Dealbreaker Hurdle Phi(i), and True Pareto Top-3 Reordering.

Evaluates (`specs/003-clean-adaptive-recsys/`):
U(u, q, i) = Phi(i) * sum_{k in ActiveSlots} w_hat_k(u, q) * f_{i,k}

Where:
- `f_{i,1}` (`w_price`): Outlier-resistant relative exponential decay `exp(-(P_i - P_min) / (0.15 * P_min))`
- `f_{i,2}` (`w_distance`): Exponential urban distance decay `exp(-d_i / 8.0)`
- `f_{i,3}` (`w_open_now`): Open status (`1.0` open, `0.4` unknown hours, `0.0` closed)
- `f_{i,4}` (`w_trust_freshness`): `0.65 * exp(-age_days / 14.0) + 0.20 * I(is_real_shop) + 0.15 * I(has_warranty)`
- `f_{i,5}` (`w_installment`): Verified in-person installment availability (`1.0` or `0.0`)
- `f_{i,6}` (`w_offer_custom`, optional): Decision-Model open-vocabulary offer score in `[0.0, 1.0]`

Physically places `best_overall` at index `0`, `closest_open` at index `1`, and `lowest_price` at index `2`.
"""

import math
from typing import Any

from backend.config import settings
from backend.db.normalizer import to_persian_digits
from backend.models.schemas import HardConstraintsState, MallMicroGuide, ScoredStoreOffer


def _compute_authentic_price_bounds(
    candidates: list[dict[str, Any]],
    wants_used_or_stock: bool = False,
) -> tuple[int, int]:
    """Return `(effective_min_price, authentic_floor_price)` using median outlier guard (`0.35 * median`)."""
    positive_prices = sorted(int(c["price_toman"]) for c in candidates if int(c.get("price_toman", 0)) > 0)
    if not positive_prices:
        return 1_000_000, 0
    if wants_used_or_stock or len(positive_prices) < 3:
        return positive_prices[0], 0
    median_price = positive_prices[len(positive_prices) // 2]
    authentic_floor = int(median_price * 0.35)
    valid_prices = [p for p in positive_prices if p >= authentic_floor]
    eff_min = valid_prices[0] if valid_prices else positive_prices[0]
    return eff_min, authentic_floor


def _compute_feature_vector(
    offer: dict[str, Any],
    min_price: int,
    authentic_floor: int = 0,
) -> dict[str, float]:
    """Compute normalized `[0.0, 1.0]` feature values `f_{i,k}` for the 5 base + optional 6th custom store criteria."""
    price = int(offer.get("price_toman", 0))
    tau_price = max(0.01, float(settings.recsys_price_decay_ratio))
    is_suspicious = bool(authentic_floor > 0 and 0 < price < authentic_floor)
    if price <= 0 or min_price <= 0:
        f_price = 0.50
    elif is_suspicious:
        f_price = 0.20
    else:
        delta_ratio = max(0.0, float(price - min_price) / float(min_price))
        f_price = math.exp(-delta_ratio / tau_price)

    dist_km = max(0.0, float(offer.get("distance_km", 5.0)))
    tau_dist = max(0.5, float(settings.recsys_distance_decay_km))
    f_distance = math.exp(-dist_km / tau_dist)

    if offer.get("is_open_now") is True:
        f_open_now = 1.0
    elif offer.get("today_hours_fa") in (None, "", "نامشخص"):
        f_open_now = 0.40
    else:
        f_open_now = 0.0

    age_days = max(0.0, float(offer.get("freshness_age_days", 3.0)))
    half_life = max(1.0, float(settings.recsys_freshness_half_life_days))
    fresh_part = math.exp(-age_days / half_life)
    real_part = 1.0 if offer.get("is_real_torob_shop") else 0.0
    warr_part = 1.0 if offer.get("has_official_warranty") else 0.0
    f_trust_freshness = 0.65 * fresh_part + 0.20 * real_part + 0.15 * warr_part

    f_installment = 1.0 if offer.get("has_in_person_installment") else 0.0

    feats: dict[str, float] = {
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
        "is_suspicious_price": 1.0 if is_suspicious else 0.0,
    }
    if "f_offer_custom" in offer and offer["f_offer_custom"] is not None:
        f_custom = max(0.0, min(1.0, float(offer["f_offer_custom"])))
        feats["w_offer_custom"] = f_custom
        feats["f_offer_custom"] = f_custom
    return feats


def _apply_strict_hard_constraints(
    candidates: list[dict[str, Any]],
    hard_constraints: HardConstraintsState,
    max_distance_km: float | None = None,
    require_torob_pay: bool = False,
    max_price_toman: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Enforce Policy A1: keep ONLY compliant stores when ≥1 exists; otherwise relax only unsatisifiable constraints and report them."""
    if not candidates:
        return [], []

    real_pool = [c for c in candidates if not c.get("is_category_fallback")]
    pool = real_pool if real_pool else list(candidates)
    unmet_labels: list[str] = []

    checks: list[tuple[str, Any]] = []
    if max_distance_km is not None and float(max_distance_km) > 0:
        d_lim = float(max_distance_km)
        d_str = to_persian_digits(int(d_lim) if d_lim.is_integer() else round(d_lim, 1))
        checks.append((f"حداکثر فاصله {d_str} کیلومتر", lambda c, lim=d_lim: float(c.get("distance_km", 999.0)) <= lim))
    if max_price_toman is not None and int(max_price_toman) > 0:
        p_lim = int(max_price_toman)
        p_str = to_persian_digits(f"{p_lim:,}")
        checks.append((f"سقف بودجه {p_str} تومان", lambda c, lim=p_lim: c.get("is_category_fallback") or int(c.get("price_toman", 0)) <= lim))
    if require_torob_pay:
        checks.append((
            "پرداخت اقساطی با ترب‌پی",
            lambda c: any("ترب" in str(p) for p in (c.get("installment_providers") or [])),
        ))
    elif hard_constraints.require_installment:
        checks.append(("پرداخت اقساطی حضوری", lambda c: bool(c.get("has_in_person_installment"))))
    if hard_constraints.require_warranty:
        checks.append(("گارانتی معتبر شرکتی", lambda c: bool(c.get("has_official_warranty"))))
    if hard_constraints.require_open_now:
        checks.append(("باز بودن فعلی مغازه", lambda c: bool(c.get("is_open_now"))))

    for label_fa, pred in checks:
        matched = [c for c in pool if pred(c)]
        if matched:
            pool = matched
        else:
            unmet_labels.append(label_fa)

    return pool, unmet_labels


def build_why_this_shop_fa(
    offer: dict[str, Any],
    contributions: dict[str, float],
    feats: dict[str, float] | None = None,
) -> list[str]:
    """Generate truthful Persian attribution chips strictly from verified positive features."""
    reasons: list[str] = []
    f_map = feats or {}
    dist_km = offer.get("distance_km", 0.0)
    drive_m = offer.get("driving_minutes", 5)

    top_keys = [k for k, _ in sorted(contributions.items(), key=lambda item: item[1], reverse=True)]
    for k in top_keys:
        if len(reasons) >= 3:
            break
        if k == "w_offer_custom" and float(offer.get("f_offer_custom") or 0.0) >= 0.70:
            reasons.append(str(offer.get("custom_match_label_fa") or "منطبق با شرط خاص درخواستی شما"))
        elif k == "w_distance" and float(dist_km) <= 15.0:
            reasons.append(f"{to_persian_digits(dist_km)} کیلومتر فاصله ({to_persian_digits(drive_m)} دقیقه)")
        elif (
            k == "w_price"
            and int(offer.get("price_toman", 0)) > 0
            and float(f_map.get("f_price", 0.8)) >= 0.72
            and float(f_map.get("is_suspicious_price", 0.0)) < 0.5
        ):
            price_fmt = to_persian_digits(f"{int(offer['price_toman']):,}")
            reasons.append(f"قیمت رقابتی ({price_fmt} تومان)")
        elif k == "w_installment" and offer.get("has_in_person_installment"):
            provs = " و ".join((offer.get("installment_providers") or ["اقساطی"])[:2])
            reasons.append(f"پرداخت اقساطی حضوری ({provs})")
        elif k == "w_open_now" and offer.get("is_open_now"):
            reasons.append(f"هم‌اکنون باز ({offer.get('today_hours_fa', '')})")
        elif k == "w_trust_freshness":
            if offer.get("is_real_torob_shop"):
                reasons.append("فروشگاه رسمی تاییدشده ترب")
            elif offer.get("has_official_warranty"):
                reasons.append(str(offer.get("warranty_provider") or "گارانتی معتبر شرکتی"))

    if not reasons:
        reasons.append(f"{to_persian_digits(dist_km)} کیلومتر فاصله ({to_persian_digits(drive_m)} دقیقه)")
    if (
        offer.get("freshness_badge_fa")
        and float(offer.get("freshness_age_days", 14.0)) <= 7.0
        and len(reasons) < 3
    ):
        reasons.append(str(offer["freshness_badge_fa"]))
    return reasons[:3]


def score_and_rank_offers_with_meta(
    candidates: list[dict[str, Any]],
    l1_weights: dict[str, float],
    hard_constraints: HardConstraintsState,
    limit: int | None = None,
    max_distance_km: float | None = None,
    require_torob_pay: bool = False,
    max_price_toman: int | None = None,
    wants_used_or_stock: bool = False,
) -> tuple[list[ScoredStoreOffer], list[str]]:
    """Score candidate offers with strict hard-constraint filtering, unique `shop_id` dedup, and Pareto Top-3 placement."""
    if not candidates:
        return [], []

    working_pool, unmet_labels = _apply_strict_hard_constraints(
        candidates,
        hard_constraints=hard_constraints,
        max_distance_km=max_distance_km,
        require_torob_pay=require_torob_pay,
        max_price_toman=max_price_toman,
    )
    if not working_pool:
        return [], unmet_labels

    min_price, authentic_floor = _compute_authentic_price_bounds(
        working_pool,
        wants_used_or_stock=wants_used_or_stock,
    )

    # Pre-compute feature vectors so globally zeroed features (when a constraint was relaxed) don't crush all utilities to 10%
    raw_feature_rows = [
        (cand, _compute_feature_vector(cand, min_price=min_price, authentic_floor=authentic_floor))
        for cand in working_pool
    ]

    effective_w: dict[str, float] = {}
    for k, w in l1_weights.items():
        max_fk = max((fr[1].get(k, 0.0) for fr in raw_feature_rows), default=0.0)
        if max_fk > 1e-6:
            effective_w[k] = float(w)
    if effective_w:
        w_sum = sum(effective_w.values())
        effective_w = {k: v / w_sum for k, v in effective_w.items()}
    else:
        effective_w = {"w_price": 0.50, "w_distance": 0.30, "w_trust_freshness": 0.20}

    relax_scale = 0.88 if unmet_labels else 1.0
    scored_raw: list[tuple[float, dict[str, Any], list[str], dict[str, float]]] = []
    for cand, feats in raw_feature_rows:
        contributions = {k: float(w) * feats.get(k, 0.0) for k, w in effective_w.items() if k in feats}
        linear_utility = sum(contributions.values()) * relax_scale
        if feats.get("is_suspicious_price", 0.0) >= 0.5:
            linear_utility *= 0.45
        final_u = max(0.15, min(0.99, linear_utility))
        reasons = build_why_this_shop_fa(cand, contributions, feats=feats)
        scored_raw.append((final_u, cand, reasons, feats))

    scored_raw.sort(
        key=lambda item: (item[0], -int(item[1].get("price_toman") or 0)),
        reverse=True,
    )

    # Policy A3: Deduplicate to at most 1 best offer per unique physical `shop_id`
    scored_items: list[tuple[float, dict[str, Any], list[str], dict[str, float]]] = []
    seen_shops: set[str] = set()
    for item in scored_raw:
        sid = str(item[1].get("shop_id") or item[1]["offer_id"])
        if sid in seen_shops:
            continue
        seen_shops.add(sid)
        scored_items.append(item)

    top_n = limit or settings.top_ranked_stores_limit
    pool = scored_items[: max(top_n, 3)]

    best_overall_item = pool[0]
    best_overall_id = best_overall_item[1]["offer_id"]
    best_overall_price = int(best_overall_item[1].get("price_toman") or 0)
    search_tail = pool[1:]

    open_candidates = [item for item in search_tail if item[1].get("is_open_now")]
    closest_open_item = (
        min(open_candidates, key=lambda x: float(x[1].get("distance_km", 999.0)))
        if open_candidates
        else None
    )
    closest_open_id = closest_open_item[1]["offer_id"] if closest_open_item is not None else None

    price_candidates = [
        item
        for item in search_tail
        if item[1]["offer_id"] != closest_open_id
        and int(item[1].get("price_toman", 0)) > 0
        and item[3].get("is_suspicious_price", 0.0) < 0.5
    ]
    cand_lowest = (
        min(price_candidates, key=lambda x: int(x[1]["price_toman"]))
        if price_candidates
        else None
    )
    # Never label a store `lowest_price` if `best_overall` at [0] is strictly cheaper!
    lowest_price_item = (
        cand_lowest
        if (
            cand_lowest is not None
            and (best_overall_price <= 0 or int(cand_lowest[1]["price_toman"]) <= best_overall_price)
        )
        else None
    )
    lowest_price_id = lowest_price_item[1]["offer_id"] if lowest_price_item is not None else None

    # Physical Pareto Top-3 placement at indices [0, 1, 2]
    pinned_ids = {best_overall_id}
    ordered: list[tuple[float, dict[str, Any], list[str], dict[str, float]]] = [best_overall_item]
    if closest_open_item is not None and closest_open_id not in pinned_ids:
        ordered.append(closest_open_item)
        pinned_ids.add(closest_open_id)
    if lowest_price_item is not None and lowest_price_id not in pinned_ids:
        ordered.append(lowest_price_item)
        pinned_ids.add(lowest_price_id)
    for item in scored_items:
        if item[1]["offer_id"] not in pinned_ids:
            ordered.append(item)
            pinned_ids.add(item[1]["offer_id"])
    ordered = ordered[:top_n]

    results: list[ScoredStoreOffer] = []
    for u_val, cand, reasons, feats in ordered:
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
                product_id=str(cand.get("product_id") or ""),
                product_name=str(cand.get("product_name") or ""),
                shop_id=str(cand.get("shop_id") or oid),
                shop_name=str(cand.get("shop_name") or "فروشگاه"),
                price_toman=int(cand.get("price_toman", 0)),
                utility_score=max(15, min(99, int(round(u_val * 100)))),
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

    return results, unmet_labels


def score_and_rank_offers(
    candidates: list[dict[str, Any]],
    l1_weights: dict[str, float],
    hard_constraints: HardConstraintsState,
    limit: int | None = None,
) -> list[ScoredStoreOffer]:
    """Score candidate store offers using the 5+1 utility function and physically place Pareto Top-3 at `[0, 1, 2]`."""
    ranked, _ = score_and_rank_offers_with_meta(
        candidates=candidates,
        l1_weights=l1_weights,
        hard_constraints=hard_constraints,
        limit=limit,
    )
    return ranked
