"""5-Criteria Sparse Override Weight Manager & Contrastive Revealed-Preference Learner.

Implements the Two-Stage Jev Store Weight Architecture (`specs/002-jev-domain-recsys/`):
1. Layer 1 (Database / Redis Storage): 5 orthogonal store weights in `[0.10, 1.00]^5`
   (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`), updated ONLY
   from UI feedback (never mutated by emergency chat text).
2. Sparse Override Fusion:
   - If the user mentions at least 1 criterion in chat (`score >= 0.35`), mentioned criteria receive
     their direct `Jev` score `s_k(q)` while unmentioned criteria receive a bounded tie-breaker
     `min(0.04, 0.10 * p_k(u))` so a single explicit priority achieves `>= 80%` normalized weight (`SC-001`).
   - If no store criterion is mentioned in chat, stored user weights `p_k(u)` are used directly.
3. Layer 2 (Query-Time Ranking): L1 Simplex Normalization `sum_{k=1..5} w_hat_k(u, q) = 1.0`.
"""

from typing import Any

from backend.config import settings
from backend.models.schemas import ActiveWeightSlot
from backend.recsys.jev_engine import STORE_CRITERIA_CATALOG, ScoreJudgment


def clip(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def compute_fusion_alpha(confidence: float) -> float:
    """Backward-compatible precision gate helper."""
    return clip(
        settings.recsys_fusion_gamma * confidence,
        settings.recsys_fusion_alpha_min,
        settings.recsys_fusion_alpha_max,
    )


def l1_normalize_weights(raw_weights: dict[str, float]) -> dict[str, float]:
    """Normalize non-negative weights onto the probability simplex (`sum_k w_hat_k = 1.0`)."""
    cleaned = {k: max(0.0, float(v)) for k, v in raw_weights.items()}
    total = sum(cleaned.values())
    if total <= 1e-9:
        n = max(1, len(cleaned))
        return {k: round(1.0 / n, 6) for k in cleaned}
    return {k: v / total for k, v in cleaned.items()}


def _resolve_prior_store_weights(user_profile: dict[str, Any]) -> dict[str, float]:
    """Extract the 5 canonical store weights from `user_profile` with backward-compatible key mapping."""
    defaults = settings.default_store_weights
    base_stored = user_profile.get("base_weights") or {}
    persona_stored = user_profile.get("persona_weights") or {}

    w_trust = base_stored.get(
        "w_trust_freshness",
        base_stored.get("w_freshness", base_stored.get("w_score", persona_stored.get("w_warranty", defaults["w_trust_freshness"]))),
    )
    w_inst = base_stored.get(
        "w_installment",
        persona_stored.get("w_installment", defaults["w_installment"]),
    )

    return {
        "w_price": float(base_stored.get("w_price", defaults["w_price"])),
        "w_distance": float(base_stored.get("w_distance", defaults["w_distance"])),
        "w_open_now": float(base_stored.get("w_open_now", defaults["w_open_now"])),
        "w_trust_freshness": float(w_trust),
        "w_installment": float(w_inst),
    }


def _resolve_session_judgment(
    key: str,
    session_judgments: dict[str, ScoreJudgment],
) -> ScoreJudgment | None:
    """Resolve canonical 5-criteria session judgment, folding legacy aliases into `w_trust_freshness`."""
    if key in session_judgments:
        return session_judgments[key]
    if key == "w_trust_freshness":
        aliases = [
            session_judgments[a]
            for a in ("w_warranty", "w_verified_shop", "w_freshness", "w_score")
            if a in session_judgments
        ]
        if aliases:
            return max(aliases, key=lambda j: j.score)
    return None


def fuse_and_normalize_weights(
    user_profile: dict[str, Any],
    session_judgments: dict[str, ScoreJudgment],
) -> tuple[list[ActiveWeightSlot], dict[str, float], float]:
    """Combine stored 5-criteria store weights with current turn Jev 3-level judgments via Sparse Override.

    Returns `(active_weight_slots, l1_weights_map, mean_effective_confidence)`.
    """
    prior_weights = _resolve_prior_store_weights(user_profile)
    mention_thresh = min(float(settings.recsys_mention_score_threshold), 0.18)
    tiebreaker_factor = settings.recsys_unmentioned_tiebreaker_factor

    resolved_judgments: dict[str, ScoreJudgment | None] = {
        key: _resolve_session_judgment(key, session_judgments) for key in STORE_CRITERIA_CATALOG
    }
    mentioned_keys = [
        key
        for key, j in resolved_judgments.items()
        if j is not None and j.score >= mention_thresh
    ]
    has_any_mention = len(mentioned_keys) > 0

    raw_weights: dict[str, float] = {}
    confidences: dict[str, float] = {}
    slot_meta: list[dict[str, Any]] = []

    for key, meta in STORE_CRITERIA_CATALOG.items():
        slot_num = int(meta["slot"])
        prior_w = clip(prior_weights.get(key, 0.30), 0.10, 1.00)
        judgment = resolved_judgments.get(key)
        base_conf = judgment.confidence if judgment is not None else 0.50

        if has_any_mention:
            if key in mentioned_keys and judgment is not None:
                # Active session priority directly overrides prior
                w_val = clip(judgment.score, 0.10, 1.00)
                eff_conf = max(base_conf, 0.85)
            else:
                # Unmentioned criterion gets only a small tie-breaker so mentioned criteria are never diluted
                w_val = min(0.035, tiebreaker_factor * prior_w)
                eff_conf = base_conf
        else:
            # No store criterion mentioned in chat -> fall back to user's behavioral prior
            w_val = prior_w
            eff_conf = max(base_conf, 0.55 if user_profile.get("interaction_count", 0) > 0 else base_conf)

        raw_weights[key] = w_val
        confidences[key] = clip(eff_conf, 0.0, 1.0)
        slot_meta.append(
            {
                "slot": slot_num,
                "key": key,
                "label_fa": meta["label_fa"],
                "slot_group": "base",
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
                slot_group="base",
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
    """Update user's 5 store criteria weights from real UI actions (revealed preference).

    Applies contrastive debiasing:
    `p_k(u) <- clip(p_k(u) + lr * (f_selected_k - mean_shown_k), 0.10, 1.00)`
    so features shared across all displayed stores do not create an echo chamber.
    """
    lr = settings.recsys_contrastive_feedback_lr
    base_w = dict(settings.default_base_weights)
    base_w.update(user_profile.get("base_weights") or {})
    persona_w = dict(settings.default_persona_weights)
    persona_w.update(user_profile.get("persona_weights") or {})

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
                cur = float(base_w.get(key, 0.30))
                base_w[key] = round(clip(cur + lr * diff, 0.10, 1.00), 4)

    if explicit_deltas:
        for key, target_val in explicit_deltas.items():
            clamped = round(clip(float(target_val), 0.0, 1.0), 4)
            base_w[key] = clamped
            if key in persona_w:
                persona_w[key] = clamped
            if key in ("w_warranty", "w_verified_shop", "w_freshness", "w_score"):
                base_w["w_trust_freshness"] = clamped

    user_profile["base_weights"] = base_w
    user_profile["persona_weights"] = persona_w
    user_profile["interaction_count"] = int(user_profile.get("interaction_count", 0)) + 1
    return user_profile


def update_profile_ema_unconstrained(
    user_profile: dict[str, Any],
    session_judgments: dict[str, ScoreJudgment] | None = None,
    explicit_deltas: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Backward-compatible profile updater used by explicit feedback and legacy unit tests."""
    eta = settings.recsys_ema_learning_rate
    base_w = dict(settings.default_base_weights)
    base_w.update(user_profile.get("base_weights") or {})

    persona_w = dict(settings.default_persona_weights)
    persona_w.update(user_profile.get("persona_weights") or {})

    if session_judgments:
        active_thresh = min(float(settings.recsys_mention_score_threshold), 0.18)
        for key, judgment in session_judgments.items():
            if judgment.score < active_thresh:
                # Unmentioned criteria (Level 0) MUST NOT overwrite or decay stored user weights!
                continue
            step = max(eta * judgment.confidence, 0.65)
            if key in base_w:
                base_w[key] = round(clip((1.0 - step) * base_w[key] + step * judgment.score, 0.0, 1.0), 4)
            elif key in persona_w:
                persona_w[key] = round(clip((1.0 - step) * persona_w[key] + step * judgment.score, 0.0, 1.0), 4)

    if explicit_deltas:
        for key, target_val in explicit_deltas.items():
            clamped = round(clip(float(target_val), 0.0, 1.0), 4)
            if key in base_w or key in STORE_CRITERIA_CATALOG:
                base_w[key] = clamped
            if key in persona_w:
                persona_w[key] = clamped
            if key in ("w_warranty", "w_verified_shop", "w_freshness", "w_score"):
                base_w["w_trust_freshness"] = clamped
            for dyn in user_profile.get("dynamic_slots", []):
                if dyn.get("feature_key") == key:
                    dyn["weight"] = clamped

    user_profile["base_weights"] = base_w
    user_profile["persona_weights"] = persona_w
    user_profile["interaction_count"] = int(user_profile.get("interaction_count", 0)) + 1
    return user_profile
