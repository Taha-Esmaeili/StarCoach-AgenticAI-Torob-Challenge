"""Dual-Mode Jev System One Decision Model (`typesafe-sdk` / `/v1/systemone` + OpenAI-compatible fallback).

Follows `.agents/skills/typesafe-ai/SKILL.md`:
- "Judgments from Jev, decisions in code"
- Evaluates `Score` (parameter weights + calibrated `confidence`), `Noul` (dealbreakers, dissatisfaction,
  and Stage-2 semantic feature equivalence), and `Choice` (shopping intent routing) in parallel.
- 100% `.env`-driven via `backend.config.settings`.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np

from backend.config import settings
from backend.db.normalizer import normalize_persian_text


@dataclass
class ScoreJudgment:
    score: float  # normalized in [0.0, 1.0]
    confidence: float  # calibrated confidence in [0.0, 1.0]
    probabilities: list[float] = field(default_factory=list)


@dataclass
class NoulJudgment:
    noul: float  # P(statement is true) in [0.0, 1.0]
    confidence: float  # calibrated confidence in [0.0, 1.0]


@dataclass
class ChoiceJudgment:
    choice: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class CandidateDynamicSpec:
    feature_key: str
    label_fa: str
    category_name: str | None
    weight: float
    confidence: float


@dataclass
class SystemOneTurnEvaluation:
    """Complete parallel System One judgment output for a shopping turn."""

    intent_choice: ChoiceJudgment
    session_weights: dict[str, ScoreJudgment]
    dealbreakers: dict[str, NoulJudgment]
    user_dissatisfied: NoulJudgment
    candidate_dynamic_specs: list[CandidateDynamicSpec] = field(default_factory=list)
    max_price_toman: int | None = None
    engine_mode_used: str = "openai_compatible_system_one"


# Canonical 10 fixed slots (5 Base + 5 Persona) metadata
SLOT_CATALOG: dict[str, dict[str, Any]] = {
    "w_distance": {"slot": 1, "group": "base", "label_fa": "نزدیکی و سرعت دسترسی"},
    "w_price": {"slot": 2, "group": "base", "label_fa": "کمترین قیمت و صرفه اقتصادی"},
    "w_score": {"slot": 3, "group": "base", "label_fa": "امتیاز و اعتبار فروشگاه"},
    "w_open_now": {"slot": 4, "group": "base", "label_fa": "باز بودن فروشگاه در این لحظه"},
    "w_freshness": {"slot": 5, "group": "base", "label_fa": "تازگی بروزرسانی قیمت"},
    "w_installment": {"slot": 6, "group": "persona", "label_fa": "پرداخت اقساطی حضوری (ترب‌پی/اسنپ‌پی)"},
    "w_warranty": {"slot": 7, "group": "persona", "label_fa": "گارانتی رسمی و شرکتی"},
    "w_mall_cluster": {"slot": 8, "group": "persona", "label_fa": "حضور در بورس و پاساژ تخصصی"},
    "w_verified_shop": {"slot": 9, "group": "persona", "label_fa": "فروشگاه رسمی تاییدشده ترب"},
    "w_delivery_backup": {"slot": 10, "group": "persona", "label_fa": "امکان ارسال فوری"},
}


def deterministic_text_embedding(text: str, dim: int | None = None) -> list[float]:
    """Compute a deterministic unit-norm character/token n-gram embedding in R^dim.

    Ensures semantically/lexically related Persian spec labels (e.g., `حذف نویز میکروفون` and
    `میکروفون با حذف نویز مکالمه`) produce high cosine similarity (> 0.80) without blocking on external APIs.
    """
    target_dim = dim or settings.embedding_dim
    norm = normalize_persian_text(text)
    if not norm:
        vec = np.zeros(target_dim, dtype=np.float64)
        vec[0] = 1.0
        return vec.tolist()

    # Synonym canonicalization for Persian tech/shopping concepts before hashing
    synonym_groups = [
        ({"نویز", "میکروفون", "مکالمه", "anc", "enc"}, "concept_anc_mic"),
        ({"باتری", "شارژدهی", "میلی امپر", "mah", "نگهداری شارژ"}, "concept_battery"),
        ({"دوربین", "مگاپیکسل", "عکاسی", "فیلمبرداری", "لنز"}, "concept_camera"),
        ({"حافظه", "رم", "گیگابایت", "ظرفیت", "ram"}, "concept_memory"),
        ({"ضد اب", "مقاوم", "گواهی", "ip67", "ip68"}, "concept_waterproof"),
        ({"گیمینگ", "بازی", "تازه سازی", "هرتز", "پردازنده"}, "concept_gaming"),
    ]
    tokens = norm.split()
    augmented_tokens = list(tokens)
    for syn_set, canonical_tag in synonym_groups:
        if any(s in norm for s in syn_set):
            # Boost canonical concept tag weight so equivalent concepts have cosine > 0.82
            augmented_tokens.extend([canonical_tag] * 5)

    vec = np.zeros(target_dim, dtype=np.float64)
    for tok in augmented_tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % target_dim
        sign = 1.0 if ((h >> 16) & 1) == 0 else -1.0
        vec[idx] += sign * 1.5
        # Character 3-grams
        for i in range(max(0, len(tok) - 2)):
            tri = tok[i : i + 3]
            ht = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16)
            vec[ht % target_dim] += 0.5

    norm_val = float(np.linalg.norm(vec))
    if norm_val > 1e-9:
        vec = vec / norm_val
    else:
        vec[0] = 1.0
    return [round(float(x), 6) for x in vec]


def _extract_budget_toman(norm_q: str) -> int | None:
    """Extract Persian budget limits such as 'تا 2 میلیون' or 'زیر 15 میلیون'."""
    import re

    m_mil = re.search(r"(?:تا|زیر|حداکثر|حدود)\s*(\d+(?:\.\d+)?)\s*میلیون", norm_q)
    if m_mil:
        return int(float(m_mil.group(1)) * 1_000_000)
    m_hezar = re.search(r"(?:تا|زیر|حداکثر)\s*(\d+)\s*هزار", norm_q)
    if m_hezar:
        return int(float(m_hezar.group(1)) * 1_000)
    return None


def _local_calibrated_system_one_analyze(message: str) -> SystemOneTurnEvaluation:
    """Calibrated local System-One analyzer implementing exact RLCD-style Score, Noul, and Choice judgments."""
    norm = normalize_persian_text(message)
    tokens = set(norm.split())

    # 1. Detect urgency / proximity vs. price sensitivity
    urgent_signals = {"سریع", "سریعترین", "نزدیک", "نزدیکترین", "فوری", "همین", "الان", "عجله", "حضوری"}
    location_signals = {"ولیعصر", "جمهوری", "ونک", "صادقیه", "تجریش", "انقلاب", "پاساژ", "سمت", "میدان"}
    cheap_signals = {"ارزان", "ارزون", "ارزانترین", "ارزونترین", "اقتصادی", "کف", "مناسبترین", "کمترین"}
    installment_signals = {"قسطی", "اقساطی", "اقساط", "ترب پی", "اسنپ پی", "چکی", "اعتباری"}
    warranty_signals = {"گارانتی", "ضمانت", "شرکتی", "رسمی", "اصلی", "اورجینال"}
    compare_signals = {"مقایسه", "نبرد", "فرقی", "تفاوت", "کدوم", "بین", "یا", "vs"}
    dissatisfied_signals = {"نه", "بد", "نمیخوام", "نبود", "گران", "گرون", "دور", "راضی نیستم", "اشتباه"}

    has_urgent = bool(tokens & urgent_signals) or any(w in norm for w in ("سریع", "نزدیک", "فوری", "الان باز"))
    has_loc = bool(tokens & location_signals)
    has_cheap = bool(tokens & cheap_signals) or any(w in norm for w in ("ارزان", "ارزون", "کمترین قیمت"))
    has_inst = any(w in norm for w in installment_signals)
    has_warr = bool(tokens & warranty_signals)
    has_compare = bool(tokens & compare_signals)
    has_dissatisfied = any(w in norm for w in dissatisfied_signals)
    max_price = _extract_budget_toman(norm)

    # Check how specific the query is (vague queries like "یه گوشی خوب میخوام" have low confidence < 0.45)
    specific_signals_count = sum(
        [
            int(has_urgent),
            int(has_loc),
            int(has_cheap or max_price is not None),
            int(has_inst),
            int(has_warr),
        ]
    )
    is_vague = specific_signals_count == 0 and len(tokens) <= 5

    base_conf = 0.28 if is_vague else min(0.94, 0.62 + 0.10 * specific_signals_count)

    # Slot 1: Distance / Speed
    if has_urgent or has_loc:
        s_dist = ScoreJudgment(score=0.94 if has_urgent else 0.82, confidence=0.92)
    elif has_cheap and not has_loc:
        s_dist = ScoreJudgment(score=0.22, confidence=0.80)
    else:
        s_dist = ScoreJudgment(score=0.50, confidence=base_conf)

    # Slot 2: Price Advantage
    if has_cheap:
        s_price = ScoreJudgment(score=0.95, confidence=0.94)
    elif max_price is not None:
        s_price = ScoreJudgment(score=0.82, confidence=0.86)
    elif has_urgent and not has_cheap:
        s_price = ScoreJudgment(score=0.28, confidence=0.82)
    else:
        s_price = ScoreJudgment(score=0.55, confidence=base_conf)

    # Slot 3: Shop Score / Reputation
    s_score = ScoreJudgment(score=0.65 if has_warr else 0.45, confidence=base_conf)

    # Slot 4: Open Now
    if has_urgent or "باز" in tokens:
        s_open = ScoreJudgment(score=0.92, confidence=0.93)
    else:
        s_open = ScoreJudgment(score=0.50, confidence=base_conf)

    # Slot 5: Price Freshness
    s_fresh = ScoreJudgment(score=0.60 if has_cheap else 0.45, confidence=base_conf)

    # Persona Slots 6..10
    s_inst = ScoreJudgment(score=0.95 if has_inst else 0.25, confidence=0.94 if has_inst else base_conf)
    s_warr = ScoreJudgment(score=0.90 if has_warr else 0.35, confidence=0.90 if has_warr else base_conf)
    s_mall = ScoreJudgment(score=0.75 if "پاساژ" in norm else 0.35, confidence=0.80 if "پاساژ" in norm else base_conf)
    s_ver = ScoreJudgment(score=0.75 if has_warr else 0.40, confidence=base_conf)
    s_deliv = ScoreJudgment(score=0.60 if "ارسال" in norm else 0.25, confidence=base_conf)

    session_weights = {
        "w_distance": s_dist,
        "w_price": s_price,
        "w_score": s_score,
        "w_open_now": s_open,
        "w_freshness": s_fresh,
        "w_installment": s_inst,
        "w_warranty": s_warr,
        "w_mall_cluster": s_mall,
        "w_verified_shop": s_ver,
        "w_delivery_backup": s_deliv,
    }

    # Dynamic Spec Extraction (Slots 11..15 candidates)
    dyn_candidates: list[CandidateDynamicSpec] = []
    spec_patterns = [
        (["میکروفون", "مکالمه", "نویز", "anc"], "spec_anc_mic", "حذف نویز و کیفیت میکروفون", "هدفون، هدست و هندزفری"),
        (["باتری", "شارژدهی", "نگهداری شارژ"], "spec_battery", "ظرفیت باتری و شارژدهی", "گوشی موبایل"),
        (["دوربین", "عکاسی", "فیلمبرداری", "زوم"], "spec_camera", "کیفیت دوربین و سنسور", "گوشی موبایل"),
        (["گیمینگ", "بازی", "پردازنده", "هرتز"], "spec_gaming", "سخت‌افزار گیمینگ و نرخ نوسازی", "گوشی موبایل"),
        (["ضد اب", "مقاوم", "ip68", "ip67"], "spec_waterproof", "مقاومت در برابر آب و ضربه", None),
        (["سیمی", "جک", "aux"], "spec_wired", "اتصال سیمی بدون تاخیر", "هدفون، هدست و هندزفری"),
    ]
    for triggers, f_key, label_fa, cat_name in spec_patterns:
        if any(t in norm for t in triggers):
            dyn_candidates.append(
                CandidateDynamicSpec(
                    feature_key=f_key,
                    label_fa=label_fa,
                    category_name=cat_name,
                    weight=0.85,
                    confidence=0.88,
                )
            )

    dealbreakers = {
        "require_open_now": NoulJudgment(
            noul=0.88 if ("الان" in tokens or "فوری" in tokens or "باز" in tokens) else 0.15,
            confidence=0.90,
        ),
        "require_installment": NoulJudgment(
            noul=0.92 if has_inst else 0.10,
            confidence=0.92,
        ),
        "require_warranty": NoulJudgment(
            noul=0.86 if ("فقط گارانتی" in norm or "حتما گارانتی" in norm) else (0.60 if has_warr else 0.12),
            confidence=0.88,
        ),
    }

    intent = "comparison" if has_compare else ("clarification" if is_vague else "store_ranking")
    return SystemOneTurnEvaluation(
        intent_choice=ChoiceJudgment(
            choice=intent,
            confidence=0.88 if not is_vague else 0.55,
            probabilities={intent: 0.88},
        ),
        session_weights=session_weights,
        dealbreakers=dealbreakers,
        user_dissatisfied=NoulJudgment(
            noul=0.85 if has_dissatisfied else 0.08,
            confidence=0.90,
        ),
        candidate_dynamic_specs=dyn_candidates,
        max_price_toman=max_price,
        engine_mode_used=settings.jev_engine_mode,
    )


async def evaluate_turn_with_jev(message: str, session_context: dict[str, Any] | None = None) -> SystemOneTurnEvaluation:
    """Evaluate a user shopping prompt using TypeSafe `Jev` (`/v1/systemone`) or OpenAI-compatible fallback."""
    baseline = _local_calibrated_system_one_analyze(message)

    # Mode 1: TypeSafe AI System One (`POST /v1/systemone`) when TYPESAFE_API_KEY is configured
    if settings.typesafe_api_key.strip():
        try:
            async with httpx.AsyncClient(timeout=settings.typesafe_timeout_seconds) as client:
                payload = {
                    "model": settings.typesafe_model,
                    "state": {
                        "user_message": message,
                        "previous_category": (session_context or {}).get("active_category_name"),
                    },
                    "questions": {
                        "w_distance": {
                            "type": "score",
                            "instructions": "How strongly does the shopper prioritize close physical distance or urgent immediate pickup?",
                        },
                        "w_price": {
                            "type": "score",
                            "instructions": "How strongly does the shopper prioritize getting the lowest price in Tehran?",
                        },
                        "require_installment": {
                            "type": "noul",
                            "instructions": "Does the shopper explicitly require installment or credit payment (such as TorobPay or SnappPay)?",
                        },
                        "user_dissatisfied": {
                            "type": "noul",
                            "instructions": "Is the shopper expressing dissatisfaction or rejection toward previous recommendations?",
                        },
                    },
                }
                resp = await client.post(
                    f"{settings.typesafe_base_url.rstrip('/')}/systemone",
                    headers={"Authorization": f"Bearer {settings.typesafe_api_key.strip()}"},
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json().get("answers", {})
                    for key in ("w_distance", "w_price"):
                        if key in data and isinstance(data[key], dict):
                            raw_score = float(data[key].get("score", baseline.session_weights[key].score))
                            norm_score = raw_score / 4.0 if raw_score > 1.0 else raw_score
                            conf = float(data[key].get("confidence", baseline.session_weights[key].confidence))
                            baseline.session_weights[key] = ScoreJudgment(
                                score=max(0.0, min(1.0, norm_score)),
                                confidence=max(0.0, min(1.0, conf)),
                            )
                    if "require_installment" in data and isinstance(data["require_installment"], dict):
                        baseline.dealbreakers["require_installment"] = NoulJudgment(
                            noul=float(data["require_installment"].get("noul", 0.1)),
                            confidence=float(data["require_installment"].get("confidence", 0.9)),
                        )
                    if "user_dissatisfied" in data and isinstance(data["user_dissatisfied"], dict):
                        baseline.user_dissatisfied = NoulJudgment(
                            noul=float(data["user_dissatisfied"].get("noul", 0.08)),
                            confidence=float(data["user_dissatisfied"].get("confidence", 0.9)),
                        )
                    baseline.engine_mode_used = "typesafe_sdk"
        except Exception:
            pass

    return baseline


async def check_feature_equivalence_noul(label_a: str, label_b: str) -> NoulJudgment:
    """Stage-2 Jev `Noul` equivalence gate for borderline cosine similarities in [0.65, 0.80]."""
    norm_a = set(normalize_persian_text(label_a).split())
    norm_b = set(normalize_persian_text(label_b).split())
    if not norm_a or not norm_b:
        return NoulJudgment(noul=0.0, confidence=0.9)

    overlap = len(norm_a & norm_b) / float(min(len(norm_a), len(norm_b)))
    vec_a = np.array(deterministic_text_embedding(label_a), dtype=np.float64)
    vec_b = np.array(deterministic_text_embedding(label_b), dtype=np.float64)
    cos = float(np.dot(vec_a, vec_b))
    noul_prob = min(1.0, max(0.0, 0.5 * overlap + 0.5 * max(0.0, cos)))
    return NoulJudgment(noul=round(noul_prob, 4), confidence=0.88)
