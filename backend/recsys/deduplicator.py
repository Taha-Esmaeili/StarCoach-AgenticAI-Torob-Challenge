"""Category-Agnostic Trait Consolidator (`user_trait_memory` via `pgvector` + `Jev` `Noul` + Top-2 Inertia)."""

from typing import Any

import asyncpg
import numpy as np

from backend.config import settings
from backend.db.normalizer import normalize_persian_text
from backend.db.profiles import (
    find_closest_user_aspects_pgvector,
    upsert_user_trait_with_inertia,
)
from backend.recsys.jev_engine import (
    ExtractedTrait,
    check_trait_aspect_and_preference_noul,
    embed_text_async,
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


async def sync_user_traits(
    user_id: str,
    source_category: str,
    extracted_traits: list[ExtractedTrait],
    pg_pool: asyncpg.Pool | None = None,
    is_ephemeral_or_gift: bool = False,
    alpha: float | None = None,
) -> list[dict[str, Any]]:
    """Consolidate durable user traits with gift/outlier shield and Top-2 per-aspect `strength` inertia.

    - Gift / Ephemeral Shield: When `is_ephemeral_or_gift` is True, zero traits are written to `user_trait_memory`.
    - Aspect Deduplication & Competing Stance Detection:
      Uses `pgvector` cosine candidate lookup + `Jev` `check_trait_aspect_and_preference_noul` so:
      * Same aspect + same preference reinforces `strength` (`1 - (1 - s)*(1 - alpha)`).
      * Same aspect + competing preference decays rival (`0.92 * s`) and retains Top-2 stances per aspect.
    """
    if is_ephemeral_or_gift:
        return []

    durable = [t for t in extracted_traits if t.is_durable and t.aspect and t.preference]
    if not durable:
        return []

    cos_thresh = float(settings.recsys_trait_cosine_candidate_threshold)
    noul_thresh = float(settings.recsys_trait_jev_same_aspect_noul)
    step_alpha = float(alpha if alpha is not None else settings.recsys_trait_soft_step)
    persisted: list[dict[str, Any]] = []

    for trait in durable:
        aspect_vec = await embed_text_async(trait.aspect)
        closest_rows = await find_closest_user_aspects_pgvector(
            pg_pool=pg_pool,
            user_id=user_id,
            aspect_embedding=aspect_vec,
            limit=5,
        )

        matched_aspect_rows: list[dict[str, Any]] = []
        same_pref_id: int | None = None
        norm_new_aspect = normalize_persian_text(trait.aspect)
        norm_new_pref = normalize_persian_text(trait.preference)

        for row in closest_rows:
            existing_aspect = str(row.get("aspect") or "")
            existing_pref = str(row.get("preference") or "")
            cos_sim = float(row.get("cos_sim", 0.0))

            if normalize_persian_text(existing_aspect) == norm_new_aspect:
                matched_aspect_rows.append(row)
                if normalize_persian_text(existing_pref) == norm_new_pref:
                    same_pref_id = int(row["trait_id"])
                else:
                    _, same_p = await check_trait_aspect_and_preference_noul(
                        trait.aspect, trait.preference, existing_aspect, existing_pref
                    )
                    if same_p.noul >= noul_thresh and same_pref_id is None:
                        same_pref_id = int(row["trait_id"])
            elif cos_sim >= cos_thresh:
                same_a, same_p = await check_trait_aspect_and_preference_noul(
                    trait.aspect, trait.preference, existing_aspect, existing_pref
                )
                if same_a.noul >= noul_thresh:
                    matched_aspect_rows.append(row)
                    if (
                        same_p.noul >= noul_thresh or normalize_persian_text(existing_pref) == norm_new_pref
                    ) and same_pref_id is None:
                        same_pref_id = int(row["trait_id"])

        saved = await upsert_user_trait_with_inertia(
            pg_pool=pg_pool,
            user_id=user_id,
            source_category=source_category,
            aspect=trait.aspect,
            preference=trait.preference,
            aspect_embedding=aspect_vec,
            alpha=step_alpha,
            matched_aspect_rows=matched_aspect_rows,
            same_preference_trait_id=same_pref_id,
        )
        persisted.append(saved)

    return persisted
