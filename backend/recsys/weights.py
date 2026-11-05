"""15-Slot Weight Manager, Two-Layer L1 Normalization, and Confidence-Gated Fusion.

Implements the mathematical formulation in `JEV_MODEL_AND_RECSYS_REPORT.md`:
1. Layer 1 (Database / Redis Storage): Unconstrained weights in `[0.0, 1.0]^15` so adding or updating
   one feature never dilutes historical preferences.
2. Confidence-Gated Fusion:
   `w_tilde_k(u, q) = alpha_k(q) * w_session_k(q) + (1 - alpha_k(q)) * w_user_k(u)`
   where `alpha_k(q) = clip(gamma * c_k(q), alpha_min, alpha_max)` from `.env`.
3. Layer 2 (Query-Time Ranking): L1 Simplex Normalization `sum_{k=1..15} w_hat_k(u, q) = 1.0`
   so the utility score `U(u, q, i)` is a calibrated convex combination in `[0.0, 1.0]`.
"""

from typing import Any

from backend.config import settings
from backend.models.schemas import ActiveWeightSlot
from backend.recsys.jev_engine import SLOT_CATALOG, ScoreJudgment


def clip(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def compute_fusion_alpha(confidence: float) -> float:
    """Compute precision gate `alpha_k(q) = clip(gamma * c_k(q), alpha_min, alpha_max)`."""
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
    normed = {k: v / total for k, v in cleaned.items()}
    return normed


def fuse_and_normalize_weights(
    user_profile: dict[str, Any],
    session_judgments: dict[str, ScoreJudgment],
) -> tuple[list[ActiveWeightSlot], dict[str, float], float]:
    """Blend stored unconstrained user weights with session Jev judgments and L1-normalize.

    Returns `(active_weight_slots, l1_weights_map, mean_effective_confidence)`.
    """
    base_stored: dict[str, float] = dict(settings.default_base_weights)
    base_stored.update(user_profile.get("base_weights") or {})

    persona_stored: dict[str, float] = dict(settings.default_persona_weights)
    persona_stored.update(user_profile.get("persona_weights") or {})

    fused_unconstrained: dict[str, float] = {}
    confidences: dict[str, float] = {}
    slot_meta: list[dict[str, Any]] = []

    # 1. Fuse Slots 1..10 (5 Global Base + 5 Persona)
    for key, meta in SLOT_CATALOG.items():
        slot_num = int(meta["slot"])
        group = str(meta["group"])
        prior_w = float(base_stored.get(key, 0.5) if group == "base" else persona_stored.get(key, 0.35))
        judgment = session_judgments.get(key)
        if judgment is not None:
            alpha = compute_fusion_alpha(judgment.confidence)
            w_tilde = alpha * judgment.score + (1.0 - alpha) * prior_w
            eff_conf = max(judgment.confidence, 0.50 if user_profile.get("interaction_count", 0) > 0 else 0.0)
        else:
            w_tilde = prior_w
            eff_conf = 0.50
        w_tilde = clip(w_tilde, 0.0, 1.0)
        fused_unconstrained[key] = w_tilde
        confidences[key] = clip(eff_conf, 0.0, 1.0)
        slot_meta.append(
            {
                "slot": slot_num,
                "key": key,
                "label_fa": meta["label_fa"],
                "slot_group": group,
                "unconstrained_weight": w_tilde,
                "confidence": confidences[key],
            }
        )

    # 2. Include Slots 11..15 (Dynamic Category/Session Spec Slots)
    dynamic_slots: list[dict[str, Any]] = list(user_profile.get("dynamic_slots") or [])
    for idx, dyn in enumerate(dynamic_slots[: settings.recsys_dynamic_slots]):
        slot_num = int(dyn.get("slot_id") or (settings.recsys_base_slots + settings.recsys_persona_slots + idx + 1))
        f_key = str(dyn["feature_key"])
        w_val = clip(float(dyn.get("weight", 0.7)), 0.0, 1.0)
        c_val = clip(float(dyn.get("confidence", 0.8)), 0.0, 1.0)
        fused_unconstrained[f_key] = w_val
        confidences[f_key] = c_val
        slot_meta.append(
            {
                "slot": slot_num,
                "key": f_key,
                "label_fa": str(dyn.get("label_fa") or f_key),
                "slot_group": "dynamic",
                "unconstrained_weight": w_val,
                "confidence": c_val,
            }
        )

    # 3. Layer 2: L1 Simplex Normalization across all active slots (`sum_k w_hat_k = 1.0`)
    l1_map = l1_normalize_weights(fused_unconstrained)

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

    # Fix any floating-point rounding drift on the first slot so sum(slot.weight) == 1.000000
    if active_slots:
        drift = 1.0 - sum(s.weight for s in active_slots)
        active_slots[0].weight = round(max(0.0, active_slots[0].weight + drift), 6)

    # Effective confidence on the 5 Global Base Slots drives the Anti-Fatigue Clarification Gate
    base_keys = [k for k, m in SLOT_CATALOG.items() if m["group"] == "base"]
    mean_eff_conf = sum(confidences[k] for k in base_keys) / float(max(1, len(base_keys)))

    return active_slots, l1_map, round(mean_eff_conf, 4)


def update_profile_ema_unconstrained(
    user_profile: dict[str, Any],
    session_judgments: dict[str, ScoreJudgment] | None = None,
    explicit_deltas: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Update Layer-1 unconstrained weights in `[0.0, 1.0]` without cross-slot dilution."""
    eta = settings.recsys_ema_learning_rate
    base_w = dict(settings.default_base_weights)
    base_w.update(user_profile.get("base_weights") or {})

    persona_w = dict(settings.default_persona_weights)
    persona_w.update(user_profile.get("persona_weights") or {})

    if session_judgments:
        for key, judgment in session_judgments.items():
            # Confidence-weighted EMA update so weak guesses don't overwrite strong persona priors
            step = eta * judgment.confidence
            if key in base_w:
                base_w[key] = round(clip((1.0 - step) * base_w[key] + step * judgment.score, 0.0, 1.0), 4)
            elif key in persona_w:
                persona_w[key] = round(clip((1.0 - step) * persona_w[key] + step * judgment.score, 0.0, 1.0), 4)

    if explicit_deltas:
        for key, target_val in explicit_deltas.items():
            clamped = round(clip(float(target_val), 0.0, 1.0), 4)
            if key in base_w:
                base_w[key] = clamped
            elif key in persona_w:
                persona_w[key] = clamped
            else:
                for dyn in user_profile.get("dynamic_slots", []):
                    if dyn.get("feature_key") == key:
                        dyn["weight"] = clamped

    user_profile["base_weights"] = base_w
    user_profile["persona_weights"] = persona_w
    user_profile["interaction_count"] = int(user_profile.get("interaction_count", 0)) + 1
    return user_profile
