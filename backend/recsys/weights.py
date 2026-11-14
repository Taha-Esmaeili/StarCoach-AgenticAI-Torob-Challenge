"""5+1 Store Weight Manager, Sparse Override Fusion, Contrastive Store Learner & Open-Category Price Priors.

Implements Layer-2 Store Weights & Consolidation (`specs/003-clean-adaptive-recsys/`):
1. Persistent Profile (`user_profiles.store_weights_json`): 5 orthogonal numerical store criteria in `[0.10, 1.00]^5`
   (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`), updated ONLY from positive UI
   selections (`thumbs_up` / store selection) or explicit slider overrides (`weight_override`).
2. Conditional 6th Slot (`w_offer_custom`): Activated dynamically in-session when the shopper expresses an
   unstructured store/mall/offer condition (`custom_offer_criterion`).
3. Sparse Override Fusion + L1 Simplex Normalization (`sum_k w_hat_k = 1.0`) strictly honoring
   `settings.recsys_mention_score_threshold` (`0.35`) with zero hardcoded overrides.
"""

import math
from typing import Any

from backend.config import settings
from backend.models.schemas import ActiveWeightSlot
from backend.recsys.jev_engine import (
    CUSTOM_OFFER_SLOT_META,
    STORE_CRITERIA_CATALOG,
    ScoreJudgment,
)


def clip(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def l1_normalize_weights(raw_weights: dict[str, float]) -> dict[str, float]:
    """Normalize non-negative weights onto the probability simplex (`sum_k w_hat_k = 1.0`)."""
    cleaned = {k: max(0.0, float(v)) for k, v in raw_weights.items()}
    total = sum(cleaned.values())
    if total <= 1e-9:
        n = max(1, len(cleaned))
        return {k: round(1.0 / n, 6) for k in cleaned}
    return {k: v / total for k, v in cleaned.items()}


def _resolve_prior_store_weights(user_profile: dict[str, Any]) -> dict[str, float]:
    """Extract the 5 canonical store weights from `user_profile["store_weights"]`."""
    defaults = settings.default_store_weights
    stored = user_profile.get("store_weights") or {}
    return {
        key: clip(float(stored.get(key, defaults[key])), 0.10, 1.00)
        for key in STORE_CRITERIA_CATALOG
    }


def fuse_and_normalize_weights(
    user_profile: dict[str, Any],
    session_judgments: dict[str, ScoreJudgment],
    include_custom_offer: bool = False,
    custom_offer_label_fa: str | None = None,
) -> tuple[list[ActiveWeightSlot], dict[str, float], float]:
    """Combine stored 5-criteria store weights (+ optional 6th `w_offer_custom`) with turn judgments via Sparse Override.

    Returns `(active_weight_slots, l1_weights_map, mean_effective_confidence)`.
    """
    prior_weights = _resolve_prior_store_weights(user_profile)
    mention_thresh = float(settings.recsys_mention_score_threshold)
    tiebreaker_factor = float(settings.recsys_unmentioned_tiebreaker_factor)

    active_catalog: dict[str, dict[str, Any]] = dict(STORE_CRITERIA_CATALOG)
    if include_custom_offer:
        active_catalog["w_offer_custom"] = {
            "slot": int(CUSTOM_OFFER_SLOT_META["slot"]),
            "group": "dynamic",
            "label_fa": custom_offer_label_fa or str(CUSTOM_OFFER_SLOT_META["label_fa"]),
        }

    mentioned_keys = [
        key
        for key in active_catalog
        if key in session_judgments and session_judgments[key].score >= mention_thresh
    ]
    has_any_mention = len(mentioned_keys) > 0

    raw_weights: dict[str, float] = {}
    confidences: dict[str, float] = {}
    slot_meta: list[dict[str, Any]] = []

    for key, meta in active_catalog.items():
        slot_num = int(meta["slot"])
        slot_group = str(meta.get("group") or "base")
        prior_w = prior_weights.get(key, 0.30)
        judgment = session_judgments.get(key)
        base_conf = judgment.confidence if judgment is not None else 0.50

        if has_any_mention:
            if key in mentioned_keys and judgment is not None:
                w_val = clip(judgment.score, 0.10, 1.00)
                eff_conf = max(base_conf, 0.85)
            else:
                w_val = min(0.035, tiebreaker_factor * prior_w)
                eff_conf = base_conf
        else:
            w_val = prior_w
            eff_conf = max(base_conf, 0.55 if int(user_profile.get("interaction_count", 0)) > 0 else base_conf)

        raw_weights[key] = w_val
        confidences[key] = clip(eff_conf, 0.0, 1.0)
        slot_meta.append(
            {
                "slot": slot_num,
                "key": key,
                "label_fa": str(meta["label_fa"]),
                "slot_group": slot_group if slot_group in ("base", "persona", "dynamic") else "base",
                "unconstrained_weight": w_val,
                "confidence": confidences[key],
            }
        )

    l1_map = l1_normalize_weights(raw_weights)

    active_slots: list[ActiveWeightSlot] = []
    for item in sorted(slot_meta, key=lambda x: x["slot"]):
        k = item["key"]
        active_slots.append(
            ActiveWeightSlot(
                slot=item["slot"],
                key=k,
                label_fa=item["label_fa"],
                slot_group=item["slot_group"],
                weight=round(l1_map[k], 6),
                unconstrained_weight=round(item["unconstrained_weight"], 4),
                confidence=round(item["confidence"], 4),
            )
        )

    if active_slots:
        drift = 1.0 - sum(s.weight for s in active_slots)
        active_slots[0].weight = round(max(0.0, active_slots[0].weight + drift), 6)

    mean_eff_conf = sum(confidences.values()) / float(max(1, len(confidences)))
    return active_slots, l1_map, round(mean_eff_conf, 4)


def update_store_weights_contrastive(
    user_profile: dict[str, Any],
    selected_features: dict[str, float] | None = None,
    shown_feature_list: list[dict[str, float]] | None = None,
    shown_features_list: list[dict[str, float]] | None = None,
    explicit_deltas: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Update user's 5 persistent store criteria weights strictly from revealed UI selections or slider overrides.

    Contrastive update:
    `p_{u,k} <- clip(p_{u,k} + lr * (f_{o*,k} - mean_{o in S} f_{o,k}), 0.10, 1.00)`
    """
    lr = float(settings.recsys_contrastive_feedback_lr)
    sw = _resolve_prior_store_weights(user_profile)

    shown_list = shown_feature_list or shown_features_list
    if selected_features and shown_list:
        n_shown = len(shown_list)
        for key in STORE_CRITERIA_CATALOG:
            f_key = key.replace("w_", "f_", 1)
            sel_val = selected_features.get(key, selected_features.get(f_key))
            if sel_val is not None:
                mean_shown = (
                    sum(float(f.get(key, f.get(f_key, 0.5))) for f in shown_list) / float(n_shown)
                )
                diff = float(sel_val) - mean_shown
                sw[key] = round(clip(sw[key] + lr * diff, 0.10, 1.00), 4)

    if explicit_deltas:
        for key, target_val in explicit_deltas.items():
            if key in STORE_CRITERIA_CATALOG:
                sw[key] = round(clip(float(target_val), 0.10, 1.00), 4)

    user_profile["store_weights"] = sw
    user_profile["interaction_count"] = int(user_profile.get("interaction_count", 0)) + 1
    return user_profile


def update_category_price_percentile(
    user_profile: dict[str, Any],
    category_name: str,
    observed_percentile: float,
) -> dict[str, Any]:
    """Update open-category spending percentile prior `pi_{u,c} in [0.0, 1.0]` with `eta = 0.30 / sqrt(1 + n)`."""
    cat = (category_name or "").strip()
    if not cat:
        return user_profile
    obs = clip(float(observed_percentile), 0.0, 1.0)
    priors = dict(user_profile.get("price_percentiles") or {})
    entry = priors.get(cat) if isinstance(priors.get(cat), dict) else None
    if entry is None:
        priors[cat] = {"pct": round(obs, 4), "n": 1}
    else:
        n_prev = max(0, int(entry.get("n", 0)))
        old_pct = clip(float(entry.get("pct", 0.5)), 0.0, 1.0)
        eta = 0.30 / math.sqrt(1.0 + float(n_prev))
        new_pct = (1.0 - eta) * old_pct + eta * obs
        priors[cat] = {"pct": round(clip(new_pct, 0.0, 1.0), 4), "n": n_prev + 1}
    user_profile["price_percentiles"] = priors
    return user_profile
