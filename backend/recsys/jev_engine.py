"""Dual-Mode Jev System One Decision Model (`typesafe-sdk` / `/v1/systemone` + OpenAI-compatible fallback).

Follows `.agents/skills/typesafe-ai/SKILL.md` and `specs/002-jev-domain-recsys/`:
- "Judgments from Jev, decisions in code"
- Stage 1: Domain classification (`Choice`), open-vocabulary `(aspect, preference)` extraction,
  aspect-only embedding, and `check_same_aspect_noul` (`Noul`).
- Stage 2: 3-level observability `Score` rubric (`0: Not Mentioned, 1: Mild, 2: Primary`) across
  5 orthogonal store criteria (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`),
  plus dealbreaker & clarification `Noul` judgments.
- 100% `.env`-driven via `backend.config.settings`.
"""

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np

from backend.config import settings
from backend.db.normalizer import normalize_persian_text

VALID_DOMAINS: tuple[str, ...] = (
    "electronics",
    "footwear_apparel",
    "home_kitchen",
    "sports_outdoors",
    "beauty_health",
    "tools_auto",
    "culture_toys",
    "general",
)


@dataclass
class ScoreJudgment:
    score: float  # normalized in [0.0, 1.0]; < 0.35 indicates Level 0 (Not Mentioned in current message)
    confidence: float  # calibrated concentration in [0.0, 1.0]
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
class ExtractedDomainTrait:
    """Production domain-scoped user trait separating `aspect` (axis) from `preference` (polarity/stance)."""

    domain: str
    aspect: str
    preference: str
    is_durable: bool = True


@dataclass
class CandidateDynamicSpec:
    """Backward-compatible dynamic spec container."""

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
    domain: str = "electronics"
    needs_clarification: NoulJudgment = field(default_factory=lambda: NoulJudgment(noul=0.15, confidence=0.90))
    extracted_traits: list[ExtractedDomainTrait] = field(default_factory=list)
    candidate_dynamic_specs: list[CandidateDynamicSpec] = field(default_factory=list)
    max_price_toman: int | None = None
    engine_mode_used: str = "openai_compatible_system_one"


# Canonical 5 Orthogonal Store Criteria (`specs/002-jev-domain-recsys/data-model.md`)
STORE_CRITERIA_CATALOG: dict[str, dict[str, Any]] = {
    "w_price": {"slot": 1, "group": "base", "label_fa": "کمترین قیمت و صرفه اقتصادی"},
    "w_distance": {"slot": 2, "group": "base", "label_fa": "نزدیکی و سرعت دسترسی حضوری"},
    "w_open_now": {"slot": 3, "group": "base", "label_fa": "باز بودن فروشگاه در این لحظه"},
    "w_trust_freshness": {"slot": 4, "group": "base", "label_fa": "تازگی قیمت، گارانتی و اعتبار فروشگاه"},
    "w_installment": {"slot": 5, "group": "base", "label_fa": "پرداخت اقساطی حضوری (ترب‌پی/اسنپ‌پی)"},
}

# Legacy 10-slot catalog retained for backward compatibility with older unit test helpers
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

    Ensures semantically equivalent Persian attribute axes (e.g., `وزن و ابعاد دستگاه` and
    `قابلیت حمل و وزن کالا`, or `حذف نویز میکروفون` and `میکروفون با حذف نویز مکالمه`) produce
    high cosine similarity without blocking on external APIs when offline.
    """
    target_dim = dim or settings.embedding_dim
    norm = normalize_persian_text(text)
    if not norm:
        vec = np.zeros(target_dim, dtype=np.float64)
        vec[0] = 1.0
        return vec.tolist()

    synonym_groups = [
        ({"نویز", "میکروفون", "مکالمه", "anc", "enc"}, "concept_anc_mic"),
        ({"باتری", "شارژدهی", "میلی امپر", "mah", "نگهداری شارژ"}, "concept_battery"),
        ({"دوربین", "مگاپیکسل", "عکاسی", "فیلمبرداری", "لنز"}, "concept_camera"),
        ({"حافظه", "رم", "گیگابایت", "ظرفیت", "ram"}, "concept_memory"),
        ({"ضد اب", "مقاوم در برابر اب", "گواهی", "ip67", "ip68"}, "concept_waterproof"),
        ({"گیمینگ", "بازی", "تازه سازی", "هرتز", "پردازنده"}, "concept_gaming"),
        ({"وزن", "ابعاد", "حمل", "سبک", "سنگین", "خوش دست"}, "concept_weight_portability"),
        ({"کفی", "طبی", "ارگونومی", "پیاده روی", "قوس پا", "راحتی پا"}, "concept_insole_ergonomics"),
        ({"رویه", "تنفس", "چرم", "مش", "بافت کفش"}, "concept_shoe_upper"),
    ]
    tokens = norm.split()
    augmented_tokens = list(tokens)
    for syn_set, canonical_tag in synonym_groups:
        if any(s in norm for s in syn_set):
            augmented_tokens.extend([canonical_tag] * 6)

    vec = np.zeros(target_dim, dtype=np.float64)
    for tok in augmented_tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % target_dim
        sign = 1.0 if ((h >> 16) & 1) == 0 else -1.0
        vec[idx] += sign * 1.5
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


async def embed_text_async(text: str, dim: int | None = None) -> list[float]:
    """Generate an embedding vector via configured OpenAI-compatible `/embeddings` API or local deterministic fallback."""
    target_dim = dim or settings.embedding_dim
    api_key = settings.effective_embedding_api_key
    base_url = settings.effective_embedding_base_url
    if api_key and base_url:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": settings.embedding_model, "input": text},
                )
                if resp.status_code == 200:
                    vec = resp.json()["data"][0]["embedding"]
                    if isinstance(vec, list) and len(vec) == target_dim:
                        return [round(float(x), 6) for x in vec]
        except Exception:
            pass
    return deterministic_text_embedding(text, dim=target_dim)


def classify_commerce_domain(message: str, fallback_category: str | None = None) -> str:
    """Classify a Persian shopping query into one of the 8 universal commerce domains (`VALID_DOMAINS`)."""
    combined = normalize_persian_text(f"{message} {fallback_category or ''}")
    msg_norm = normalize_persian_text(message)

    domain_rules: list[tuple[str, tuple[str, ...]]] = [
        (
            "footwear_apparel",
            ("کفش", "کتانی", "کتونی", "کفی", "پوتین", "بوت", "صندل", "دمپایی", "لباس", "پوشاک", "مانتو", "شلوار", "کیف", "کوله"),
        ),
        (
            "electronics",
            (
                "گوشی",
                "موبایل",
                "سامسونگ",
                "ایفون",
                "شیائومی",
                "لپ تاپ",
                "لپتاپ",
                "هندزفری",
                "هدفون",
                "هدست",
                "ایرپاد",
                "شارژر",
                "پاوربانک",
                "کابل",
                "ساعت هوشمند",
                "تبلت",
                "مانیتور",
                "کیبورد",
                "ماوس",
                "دوربین",
                "کنسول",
                "پلی استیشن",
            ),
        ),
        (
            "sports_outdoors",
            ("اسکوتر", "دوچرخه", "تردمیل", "دمبل", "کمپینگ", "چادر", "کوهنوردی", "ورزشی", "راکت"),
        ),
        (
            "home_kitchen",
            ("یخچال", "لباسشویی", "ظرفشویی", "جاروبرقی", "قهوه ساز", "اسپرسوساز", "سرخ کن", "مایکروویو", "تلویزیون", "مبل", "فرش"),
        ),
        (
            "beauty_health",
            ("عطر", "ادکلن", "کرم", "ضد افتاب", "سشوار", "ریش تراش", "مسواک برقی", "فشارسنج"),
        ),
        (
            "tools_auto",
            ("دریل", "اچار", "جعبه ابزار", "لاستیک", "باتری خودرو", "ضبط ماشین"),
        ),
        (
            "culture_toys",
            ("کتاب", "بردگیم", "اسباب بازی", "لگو", "نوشت افزار"),
        ),
    ]

    # Prioritize explicit keywords in the current message first
    for domain, keywords in domain_rules:
        if any(k in msg_norm for k in keywords):
            return domain

    # Fall back to session category context if message had no explicit domain noun
    for domain, keywords in domain_rules:
        if any(k in combined for k in keywords):
            return domain

    return "electronics" if not fallback_category else "general"


def _extract_budget_toman(norm_q: str) -> int | None:
    """Extract Persian budget limits such as 'تا 2 میلیون' or 'زیر 15 میلیون'."""
    m_mil = re.search(r"(?:تا|زیر|حداکثر|حدود)\s*(\d+(?:\.\d+)?)\s*(?:میلیون|تومن|تومان)", norm_q)
    if m_mil:
        val = float(m_mil.group(1))
        return int(val * 1_000_000) if val < 1000 else int(val)
    m_hezar = re.search(r"(?:تا|زیر|حداکثر)\s*(\d+)\s*هزار", norm_q)
    if m_hezar:
        return int(float(m_hezar.group(1)) * 1_000)
    return None


def _extract_domain_traits(norm_q: str, domain: str) -> tuple[list[ExtractedDomainTrait], list[CandidateDynamicSpec]]:
    """Extract durable `(domain, aspect, preference)` traits separating axis (`aspect`) from stance (`preference`)."""
    ephemeral_markers = ("کادو", "هدیه", "تولد دوستم", "فقط امروز", "برای امشب")
    is_ephemeral_only = any(m in norm_q for m in ephemeral_markers)

    traits: list[ExtractedDomainTrait] = []
    legacy_specs: list[CandidateDynamicSpec] = []

    # Axis rules: (triggers, aspect_name, legacy_key, legacy_cat)
    axis_rules: list[tuple[list[str], str, str, str | None]] = [
        (["سبک", "سنگین", "خوش دست", "وزن", "جمع و جور", "بدنه فلزی", "صنعتی"], "وزن و ابعاد دستگاه", "spec_weight", None),
        (["کفی", "طبی", "ارگونومی", "پیاده روی", "قوس پا", "ایستادن طولانی", "پنجه پهن"], "ارگونومی و ساختار کفی کفش", "spec_insole", "کفش و کتانی"),
        (["رویه", "تنفس", "چرم", "مش"], "جنس رویه و تنفس‌پذیری کفش", "spec_upper", "کفش و کتانی"),
        (["صفحه نمایش", "نمایشگر", "مات", "امولد", "oled", "ips"], "کیفیت و نوع صفحه نمایش", "spec_display", "لپ‌تاپ و موبایل"),
        (["میکروفون", "مکالمه", "نویز", "anc", "enc"], "حذف نویز و کیفیت میکروفون", "spec_anc_mic", "هدفون، هدست و هندزفری"),
        (["باتری", "شارژدهی", "نگهداری شارژ", "میلی امپر"], "ظرفیت باتری و شارژدهی", "spec_battery", "گوشی موبایل"),
        (["دوربین", "عکاسی", "فیلمبرداری", "زوم", "لنز"], "کیفیت دوربین و سنسور", "spec_camera", "گوشی موبایل"),
        (["گیمینگ", "بازی", "پردازنده", "هرتز", "تاخیر کم", "رندرینگ", "رم", "برنامه نویسی"], "سخت‌افزار گیمینگ و پردازش", "spec_gaming", "گوشی موبایل"),
        (["ضد اب", "مقاوم در برابر اب", "ip68", "ip67"], "مقاومت در برابر آب و ضربه", "spec_waterproof", None),
        (["سیمی", "جک", "aux"], "نوع اتصال صوتی (سیمی/بی‌سیم)", "spec_wired", "هدفون، هدست و هندزفری"),
    ]

    for triggers, aspect_name, leg_key, leg_cat in axis_rules:
        matched_triggers = [t for t in triggers if t in norm_q]
        if not matched_triggers:
            continue

        # Capture the specific directional preference on the axis (e.g., "سبک" vs "سنگین و صنعتی")
        if aspect_name == "وزن و ابعاد دستگاه":
            if any(w in norm_q for w in ("سنگین", "صنعتی", "بدنه فلزی", "محکم")):
                pref_text = "بدنه سنگین، مستحکم و صنعتی"
            else:
                pref_text = "سبک، خوش‌دست و قابل‌حمل"
        elif aspect_name == "ارگونومی و ساختار کفی کفش":
            if "سخت" in norm_q or "رسمی" in norm_q:
                pref_text = "کفی رسمی و تخت"
            else:
                pref_text = "کفی طبی و نرم مناسب پیاده‌روی طولانی"
        else:
            pref_text = f"اولویت روی {' و '.join(matched_triggers[:2])} ({norm_q[:60]})"

        traits.append(
            ExtractedDomainTrait(
                domain=domain,
                aspect=aspect_name,
                preference=pref_text,
                is_durable=not is_ephemeral_only,
            )
        )
        legacy_specs.append(
            CandidateDynamicSpec(
                feature_key=leg_key,
                label_fa=aspect_name,
                category_name=leg_cat,
                weight=0.85,
                confidence=0.88,
            )
        )

    return traits, legacy_specs


def _local_calibrated_system_one_analyze(
    message: str,
    session_context: dict[str, Any] | None = None,
) -> SystemOneTurnEvaluation:
    """Evaluate turn intent, domain, 3-level store criteria scores, dealbreakers, and domain traits."""
    norm = normalize_persian_text(message)
    tokens = set(norm.split())
    prev_cat = (session_context or {}).get("active_category_name")
    domain = classify_commerce_domain(message, fallback_category=prev_cat)

    distance_signals = {"نزدیک", "نزدیکترین", "پیاده", "مسافت"}
    urgent_signals = {"سریع", "سریعترین", "فوری", "همین", "الان", "عجله"}
    location_signals = {"ولیعصر", "جمهوری", "ونک", "صادقیه", "تجریش", "انقلاب", "پاساژ", "سمت", "میدان"}
    cheap_signals = {"ارزان", "ارزون", "ارزانترین", "ارزونترین", "اقتصادی", "کف", "مناسبترین", "کمترین"}
    installment_signals = {"قسطی", "اقساطی", "اقساط", "ترب پی", "اسنپ پی", "چکی", "اعتباری"}
    warranty_signals = {"گارانتی", "ضمانت", "شرکتی", "رسمی", "اصلی", "اورجینال", "معتبر"}
    freshness_signals = {"تازه", "بروز", "به روز", "جدیدترین قیمت"}
    compare_signals = {"مقایسه", "نبرد", "فرقی", "تفاوت", "کدوم", "بین", "یا", "vs"}
    dissatisfied_signals = {"نه", "بد", "نمیخوام", "نبود", "گران", "گرون", "دور", "راضی نیستم", "اشتباه"}

    has_dist = bool(tokens & distance_signals) or any(w in norm for w in ("نزدیک", "پیاده"))
    has_urgent = bool(tokens & urgent_signals) or any(w in norm for w in ("سریع", "فوری", "الان باز"))
    has_loc = bool(tokens & location_signals)
    has_cheap = bool(tokens & cheap_signals) or any(w in norm for w in ("ارزان", "ارزون", "کمترین قیمت", "کف قیمت"))
    has_inst = any(w in norm for w in installment_signals)
    has_warr = bool(tokens & warranty_signals)
    has_fresh = any(w in norm for w in freshness_signals)
    has_open = "باز" in tokens or "الان" in tokens or "فوری" in tokens
    has_compare = bool(tokens & compare_signals)
    has_dissatisfied = any(w in norm for w in dissatisfied_signals)
    max_price = _extract_budget_toman(norm)

    traits, dyn_candidates = _extract_domain_traits(norm, domain=domain)

    # Check specificity for Turn-1 clarification (`needs_clarification` Noul)
    has_model_token = any(bool(re.search(r"[a-z0-9]{2,}", t)) for t in tokens)
    specific_signals_count = sum(
        [
            int(has_dist or has_urgent),
            int(has_loc),
            int(has_cheap or max_price is not None),
            int(has_inst),
            int(has_warr),
            int(bool(traits)),
            int(has_model_token),
        ]
    )
    is_vague = specific_signals_count == 0 and len(tokens) <= 5
    base_conf = 0.28 if is_vague else min(0.94, 0.65 + 0.08 * specific_signals_count)

    # 3-Level Observability Rubric mapped to [0.0, 1.0]:
    # - Level 0 (Not Mentioned): score = 0.0 (< 0.35 threshold -> triggers Sparse Override tie-breaker)
    # - Level 1 (Mild Preference): score = 0.55
    # - Level 2 (Primary Emphasis): score = 0.95
    s_price = ScoreJudgment(
        score=0.95 if has_cheap else (0.60 if max_price is not None else 0.0),
        confidence=0.94 if (has_cheap or max_price is not None) else base_conf,
    )
    s_dist = ScoreJudgment(
        score=0.95 if (has_dist or has_urgent) else (0.65 if has_loc else 0.0),
        confidence=0.92 if (has_dist or has_urgent or has_loc) else base_conf,
    )
    s_open = ScoreJudgment(
        score=0.92 if has_open else (0.55 if has_urgent else 0.0),
        confidence=0.92 if (has_open or has_urgent) else base_conf,
    )
    s_trust_fresh = ScoreJudgment(
        score=0.90 if (has_warr or has_fresh) else 0.0,
        confidence=0.90 if (has_warr or has_fresh) else base_conf,
    )
    s_inst = ScoreJudgment(
        score=0.95 if has_inst else 0.0,
        confidence=0.94 if has_inst else base_conf,
    )

    # Populate the 5 orthogonal store criteria + backward-compatible aliases
    session_weights: dict[str, ScoreJudgment] = {
        "w_price": s_price,
        "w_distance": s_dist,
        "w_open_now": s_open,
        "w_trust_freshness": s_trust_fresh,
        "w_installment": s_inst,
        # Aliases for backward compatibility
        "w_score": s_trust_fresh,
        "w_freshness": s_trust_fresh,
        "w_warranty": s_trust_fresh,
        "w_verified_shop": s_trust_fresh,
        "w_mall_cluster": ScoreJudgment(score=0.65 if "پاساژ" in norm else 0.0, confidence=base_conf),
        "w_delivery_backup": ScoreJudgment(score=0.60 if "ارسال" in norm else 0.0, confidence=base_conf),
    }

    dealbreakers = {
        "require_open_now": NoulJudgment(
            noul=0.88 if has_open else 0.12,
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

    needs_clarify_noul = NoulJudgment(
        noul=0.84 if is_vague else 0.14,
        confidence=0.88,
    )

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
        domain=domain,
        needs_clarification=needs_clarify_noul,
        extracted_traits=traits,
        candidate_dynamic_specs=dyn_candidates,
        max_price_toman=max_price,
        engine_mode_used=settings.jev_engine_mode,
    )


async def evaluate_turn_with_jev(
    message: str,
    session_context: dict[str, Any] | None = None,
) -> SystemOneTurnEvaluation:
    """Evaluate a user shopping prompt using TypeSafe `Jev` (`/v1/systemone`) or OpenAI-compatible fallback."""
    baseline = _local_calibrated_system_one_analyze(message, session_context=session_context)

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
                        "domain": {
                            "type": "choice",
                            "instructions": "Which commerce domain does the shopper's request belong to?",
                            "criteria": {
                                "electronics": "Phones, laptops, headphones, chargers, cameras, or digital gadgets",
                                "footwear_apparel": "Shoes, sneakers, boots, clothing, bags, or wearable fashion",
                                "home_kitchen": "Home appliances, kitchenware, furniture, or decor",
                                "sports_outdoors": "Scooters, bicycles, fitness gear, or camping equipment",
                                "beauty_health": "Cosmetics, skincare, perfumes, or personal health devices",
                                "tools_auto": "Hardware tools, car accessories, or industrial equipment",
                                "culture_toys": "Books, stationery, board games, or toys",
                                "general": "Other general retail items",
                            },
                        },
                        "needs_clarification": {
                            "type": "noul",
                            "instructions": "Is the shopper's request too broad to recommend a specific product without asking about budget or usage?",
                        },
                        "user_dissatisfied": {
                            "type": "noul",
                            "instructions": "Is the shopper expressing dissatisfaction or rejection toward previous recommendations?",
                        },
                        "require_open_now": {
                            "type": "noul",
                            "instructions": "Does the shopper explicitly demand a store that is open right now for immediate pickup?",
                        },
                        "require_installment": {
                            "type": "noul",
                            "instructions": "Does the shopper explicitly require installment or credit payment (TorobPay, SnappPay, etc.)?",
                        },
                        "w_price": {
                            "type": "score",
                            "instructions": "Does the shopper prioritize getting the lowest price in their message?",
                            "criteria": [
                                "The shopper did not mention price or budget.",
                                "The shopper mildly prefers a reasonable price or mentioned a budget limit.",
                                "The shopper strongly emphasizes getting the cheapest or lowest possible price.",
                            ],
                        },
                        "w_distance": {
                            "type": "score",
                            "instructions": "Does the shopper prioritize close physical proximity or fast access in their message?",
                            "criteria": [
                                "The shopper did not mention distance, neighborhood, or urgency.",
                                "The shopper mentioned a neighborhood or prefers a nearby store.",
                                "The shopper strongly emphasizes the closest store or fastest immediate access.",
                            ],
                        },
                        "w_open_now": {
                            "type": "score",
                            "instructions": "Does the shopper prioritize stores that are open at this moment?",
                            "criteria": [
                                "The shopper did not mention store opening hours or visiting right now.",
                                "The shopper plans to visit today.",
                                "The shopper strongly emphasizes visiting an open store immediately right now.",
                            ],
                        },
                        "w_trust_freshness": {
                            "type": "score",
                            "instructions": "Does the shopper prioritize store reputation, official status, warranty, or fresh price updates?",
                            "criteria": [
                                "The shopper did not mention warranty, store authenticity, or price freshness.",
                                "The shopper prefers a reliable store or warranty.",
                                "The shopper strongly emphasizes official shops, valid warranty, or verified fresh prices.",
                            ],
                        },
                        "w_installment": {
                            "type": "score",
                            "instructions": "Does the shopper prioritize installment or credit payment options?",
                            "criteria": [
                                "The shopper did not mention installment or credit payment.",
                                "The shopper asks if installment payment is available.",
                                "The shopper strongly emphasizes buying via installment or TorobPay/SnappPay.",
                            ],
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
                    if "domain" in data and isinstance(data["domain"], dict):
                        chosen_dom = str(data["domain"].get("choice") or baseline.domain)
                        if chosen_dom in VALID_DOMAINS:
                            baseline.domain = chosen_dom
                    for key in ("w_price", "w_distance", "w_open_now", "w_trust_freshness", "w_installment"):
                        if key in data and isinstance(data[key], dict):
                            raw_score = float(data[key].get("score", 0.0))
                            norm_score = raw_score / 2.0 if raw_score > 1.0 else raw_score
                            conf = float(data[key].get("confidence", 0.85))
                            baseline.session_weights[key] = ScoreJudgment(
                                score=max(0.0, min(1.0, norm_score)),
                                confidence=max(0.0, min(1.0, conf)),
                            )
                    if "needs_clarification" in data and isinstance(data["needs_clarification"], dict):
                        baseline.needs_clarification = NoulJudgment(
                            noul=float(data["needs_clarification"].get("noul", baseline.needs_clarification.noul)),
                            confidence=float(data["needs_clarification"].get("confidence", 0.9)),
                        )
                    if "require_installment" in data and isinstance(data["require_installment"], dict):
                        baseline.dealbreakers["require_installment"] = NoulJudgment(
                            noul=float(data["require_installment"].get("noul", 0.1)),
                            confidence=float(data["require_installment"].get("confidence", 0.9)),
                        )
                    if "require_open_now" in data and isinstance(data["require_open_now"], dict):
                        baseline.dealbreakers["require_open_now"] = NoulJudgment(
                            noul=float(data["require_open_now"].get("noul", 0.1)),
                            confidence=float(data["require_open_now"].get("confidence", 0.9)),
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


async def check_same_aspect_noul(aspect_a: str, aspect_b: str) -> NoulJudgment:
    """Evaluate via Jev `Noul` whether `aspect_a` and `aspect_b` describe the same product attribute axis."""
    norm_a = {t for t in normalize_persian_text(aspect_a).split() if len(t) >= 2}
    norm_b = {t for t in normalize_persian_text(aspect_b).split() if len(t) >= 2}
    if not norm_a or not norm_b:
        return NoulJudgment(noul=0.0, confidence=0.9)

    overlap = len(norm_a & norm_b) / float(min(len(norm_a), len(norm_b)))
    vec_a = np.array(deterministic_text_embedding(aspect_a), dtype=np.float64)
    vec_b = np.array(deterministic_text_embedding(aspect_b), dtype=np.float64)
    cos = float(np.dot(vec_a, vec_b))
    noul_prob = min(1.0, max(0.0, 0.50 * overlap + 0.50 * max(0.0, cos)))
    return NoulJudgment(noul=round(noul_prob, 4), confidence=0.90)


async def check_feature_equivalence_noul(label_a: str, label_b: str) -> NoulJudgment:
    """Alias for `check_same_aspect_noul` preserving backward compatibility."""
    return await check_same_aspect_noul(label_a, label_b)
