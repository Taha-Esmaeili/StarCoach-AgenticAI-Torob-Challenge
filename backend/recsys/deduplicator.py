"""Hybrid Feature Deduplicator (Stage-1 `pgvector`/Cosine > 0.80 + Stage-2 `Jev` `Noul` [0.65, 0.80]).

Maintains the strict fixed capacity of `RECSYS_DYNAMIC_SLOTS` (Slots 11..15) so total user
parameters never exceed `RECSYS_TOTAL_SLOTS = 15`.
"""

import math
from typing import Any

import asyncpg
import numpy as np

from backend.config import settings
from backend.db.profiles import find_closest_dynamic_slot_pgvector
from backend.recsys.jev_engine import (
    CandidateDynamicSpec,
    check_feature_equivalence_noul,
    deterministic_text_embedding,
)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity in [-1.0, 1.0] between two embedding vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a = np.asarray(vec_a, dtype=np.float64)
    b = np.asarray(vec_b, dtype=np.float64)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-9:
        return 0.0
    return float(np.dot(a, b) / denom)


async def upsert_dynamic_spec_slots(
    user_profile: dict[str, Any],
    candidates: list[CandidateDynamicSpec],
    pg_pool: asyncpg.Pool | None = None,
) -> dict[str, Any]:
    """Deduplicate and insert/merge candidate dynamic spec features into Slots 11..15."""
    if not candidates:
        return user_profile

    slots: list[dict[str, Any]] = list(user_profile.get("dynamic_slots") or [])
    max_dyn = settings.recsys_dynamic_slots
    first_slot_id = settings.recsys_base_slots + settings.recsys_persona_slots + 1
    tau_high = settings.recsys_dedup_cosine_high_threshold
    tau_low = settings.recsys_dedup_cosine_low_threshold
    tau_noul = settings.recsys_dedup_jev_noul_threshold
    decay_lambda = settings.recsys_dynamic_slot_decay_lambda

    # Increment age (sessions_since_hit) on existing slots for decayed-utility LRU eviction
    for s in slots:
        s["sessions_since_hit"] = int(s.get("sessions_since_hit", 0)) + 1
        if "embedding" not in s or not s["embedding"]:
            s["embedding"] = deterministic_text_embedding(str(s.get("label_fa") or s.get("feature_key") or ""))

    for cand in candidates:
        cand_emb = deterministic_text_embedding(f"{cand.label_fa} {cand.feature_key}")
        matched_idx: int | None = None
        best_cos = -1.0

        # Stage 1A: Query PostgreSQL `pgvector` `<=>` operator when pool is active
        pg_slot_id, pg_cos = await find_closest_dynamic_slot_pgvector(
            pg_pool,
            str(user_profile.get("user_id") or settings.default_user_id),
            cand_emb,
        )
        if pg_slot_id is not None and pg_cos >= tau_high:
            for idx, s in enumerate(slots):
                if int(s.get("slot_id", 0)) == pg_slot_id:
                    matched_idx = idx
                    best_cos = pg_cos
                    break

        # Stage 1B: Local vector cosine check across Slots 11..15
        if matched_idx is None:
            for idx, s in enumerate(slots):
                if s.get("feature_key") == cand.feature_key:
                    matched_idx = idx
                    best_cos = 1.0
                    break
                cos = cosine_similarity(cand_emb, s.get("embedding") or [])
                if cos > best_cos:
                    best_cos = cos
                    matched_idx = idx

        should_merge = False
        if matched_idx is not None and best_cos >= tau_high:
            should_merge = True
        elif matched_idx is not None and tau_low <= best_cos < tau_high:
            # Stage 2: Borderline cosine similarity -> invoke Jev `Noul` equivalence check
            existing_label = str(slots[matched_idx].get("label_fa") or "")
            noul_judgment = await check_feature_equivalence_noul(cand.label_fa, existing_label)
            if noul_judgment.noul >= tau_noul:
                should_merge = True

        if should_merge and matched_idx is not None:
            target = slots[matched_idx]
            old_w = float(target.get("weight", 0.5))
            target["weight"] = round(min(1.0, 0.6 * cand.weight + 0.4 * old_w), 4)
            target["confidence"] = round(max(float(target.get("confidence", 0.5)), cand.confidence), 4)
            target["session_hits"] = int(target.get("session_hits", 1)) + 1
            target["sessions_since_hit"] = 0
            continue

        # Truly novel feature: insert into free slot or evict lowest decayed-utility slot
        if len(slots) < max_dyn:
            used_ids = {int(s.get("slot_id", 0)) for s in slots}
            next_slot_id = next(
                sid for sid in range(first_slot_id, first_slot_id + max_dyn) if sid not in used_ids
            )
            slots.append(
                {
                    "slot_id": next_slot_id,
                    "feature_key": cand.feature_key,
                    "label_fa": cand.label_fa,
                    "category_name": cand.category_name,
                    "weight": round(cand.weight, 4),
                    "confidence": round(cand.confidence, 4),
                    "embedding": cand_emb,
                    "session_hits": 1,
                    "sessions_since_hit": 0,
                }
            )
        else:
            # Evict k* = argmin_{k in 11..15} w_k * exp(-lambda_decay * sessions_since_hit_k)
            evict_idx = min(
                range(len(slots)),
                key=lambda i: float(slots[i].get("weight", 0.5))
                * math.exp(-decay_lambda * float(slots[i].get("sessions_since_hit", 1))),
            )
            evicted_slot_id = int(slots[evict_idx]["slot_id"])
            slots[evict_idx] = {
                "slot_id": evicted_slot_id,
                "feature_key": cand.feature_key,
                "label_fa": cand.label_fa,
                "category_name": cand.category_name,
                "weight": round(cand.weight, 4),
                "confidence": round(cand.confidence, 4),
                "embedding": cand_emb,
                "session_hits": 1,
                "sessions_since_hit": 0,
            }

    user_profile["dynamic_slots"] = sorted(slots[:max_dyn], key=lambda s: int(s["slot_id"]))
    return user_profile
