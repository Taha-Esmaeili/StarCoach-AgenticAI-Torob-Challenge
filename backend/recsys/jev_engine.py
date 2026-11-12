"""Live System One Decision Engine (`Jev` / OpenRouter OpenAI-Compatible Live API).

All heuristic/keyword simulators and hash-based embedding fallbacks have been removed.
Every turn evaluation, aspect deduplication check, and text embedding is served strictly
by the configured live model (`TYPESAFE_API_KEY` or `LLM_API_KEY` / OpenRouter in `.env`).
"""

from dataclasses import dataclass, field
import json
import re
from typing import Any, Literal

import httpx

from backend.config import settings

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

# 5 Orthogonal Store Criteria (`Stage 2` of `specs/002-jev-domain-recsys`)
STORE_CRITERIA_CATALOG: dict[str, dict[str, Any]] = {
    "w_price": {"slot": 1, "group": "base", "label_fa": "کمترین قیمت و صرفه اقتصادی"},
    "w_distance": {"slot": 2, "group": "base", "label_fa": "نزدیکی و سرعت دسترسی"},
    "w_open_now": {"slot": 3, "group": "base", "label_fa": "باز بودن فروشگاه در این لحظه"},
    "w_trust_freshness": {"slot": 4, "group": "base", "label_fa": "تازگی قیمت، اعتبار و گارانتی"},
    "w_installment": {"slot": 5, "group": "persona", "label_fa": "پرداخت اقساطی حضوری (ترب‌پی/اسنپ‌پی)"},
}

# Legacy 10-slot catalog retained only for UI label lookup
FIXED_SLOT_CATALOG: dict[str, dict[str, Any]] = {
    "w_distance": {"slot": 1, "group": "base", "label_fa": "نزدیکی و سرعت دسترسی"},
    "w_price": {"slot": 2, "group": "base", "label_fa": "کمترین قیمت و صرفه اقتصادی"},
    "w_score": {"slot": 3, "group": "base", "label_fa": "امتیاز و اعتبار فروشگاه"},
    "w_open_now": {"slot": 4, "group": "base", "label_fa": "باز بودن فروشگاه در این لحظه"},
    "w_freshness": {"slot": 5, "group": "base", "label_fa": "تازگی بروزرسانی قیمت"},
    "w_trust_freshness": {"slot": 4, "group": "base", "label_fa": "تازگی قیمت، اعتبار و گارانتی"},
    "w_installment": {"slot": 6, "group": "persona", "label_fa": "پرداخت اقساطی حضوری (ترب‌پی/اسنپ‌پی)"},
    "w_warranty": {"slot": 7, "group": "persona", "label_fa": "گارانتی رسمی و شرکتی"},
    "w_mall_cluster": {"slot": 8, "group": "persona", "label_fa": "حضور در بورس و پاساژ تخصصی"},
    "w_verified_shop": {"slot": 9, "group": "persona", "label_fa": "فروشگاه رسمی تاییدشده ترب"},
    "w_delivery_backup": {"slot": 10, "group": "persona", "label_fa": "امکان ارسال فوری"},
}


@dataclass
class ScoreJudgment:
    """Calibrated `Score` primitive output normalized to [0.0, 1.0] with confidence in [0.0, 1.0]."""

    score: float
    confidence: float
    probabilities: list[float] = field(default_factory=list)


@dataclass
class NoulJudgment:
    """Calibrated `Noul` binary probability judgment in [0.0, 1.0]."""

    noul: float
    confidence: float = 0.90


@dataclass
class ChoiceJudgment:
    """Calibrated `Choice` categorical primitive output with mode & excess-probability confidence."""

    choice: Literal["store_ranking", "clarification", "comparison", "product_discovery"]
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class ExtractedDomainTrait:
    """Open-vocabulary domain-scoped user trait separating attribute axis (`aspect`) from stance (`preference`)."""

    domain: str
    aspect: str
    preference: str
    is_durable: bool = True
    confidence: float = 0.88


@dataclass
class CandidateDynamicSpec:
    """Dynamic technical specification slot metadata."""

    feature_key: str
    label_fa: str
    category_name: str | None
    weight: float
    confidence: float


@dataclass
class SystemOneTurnEvaluation:
    """Complete parallel System One output for a single user conversational turn."""

    intent_choice: ChoiceJudgment
    session_weights: dict[str, ScoreJudgment]
    dealbreakers: dict[str, NoulJudgment]
    user_dissatisfied: NoulJudgment
    domain: str = "general"
    needs_clarification: NoulJudgment = field(default_factory=lambda: NoulJudgment(noul=0.15, confidence=0.85))
    extracted_traits: list[ExtractedDomainTrait] = field(default_factory=list)
    candidate_dynamic_specs: list[CandidateDynamicSpec] = field(default_factory=list)
    max_price_toman: int | None = None
    engine_mode_used: str = "openai_compatible_system_one"


def _has_valid_api_key(key: str) -> bool:
    cleaned = (key or "").strip()
    return bool(cleaned and cleaned not in ("sk-replace-me", "your-api-key", "replace-me"))


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Parse JSON object from LLM response content (stripping markdown fences if present)."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end >= start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


async def embed_text_async(text: str, dim: int | None = None) -> list[float]:
    """Generate an embedding vector strictly via the configured live `/embeddings` API (e.g. OpenRouter)."""
    target_dim = dim or settings.embedding_dim
    api_key = settings.effective_embedding_api_key.strip()
    base_url = settings.effective_embedding_base_url.strip()

    if not _has_valid_api_key(api_key) or not base_url:
        raise RuntimeError(
            "کلید API امبدینگ (EMBEDDING_API_KEY یا LLM_API_KEY) در فایل .env تنظیم نشده است."
        )

    payload: dict[str, Any] = {
        "model": settings.embedding_model,
        "input": text,
    }
    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"خطا در دریافت امبدینگ از {base_url}/embeddings (کد {resp.status_code}): {resp.text[:300]}"
            )
        body = resp.json()
        data_list = body.get("data") or []
        if not data_list or "embedding" not in data_list[0]:
            raise RuntimeError(f"پاسخ نامعتبر از سرویس امبدینگ: {str(body)[:300]}")
        vec = [float(x) for x in data_list[0]["embedding"]]
        if len(vec) != target_dim:
            # Pad or truncate only if model dimension differs from configured pgvector column dimension
            if len(vec) > target_dim:
                vec = vec[:target_dim]
            else:
                vec = vec + [0.0] * (target_dim - len(vec))
        return [round(x, 6) for x in vec]


_SYSTEM_ONE_JSON_PROMPT = """You are a calibrated System-One decision engine for Torob's in-person shopping assistant in Tehran.
Analyze the Persian shopper's message and return ONLY a valid JSON object with the exact structure below (no markdown, no extra text):

{
  "domain": "electronics" | "footwear_apparel" | "home_kitchen" | "sports_outdoors" | "beauty_health" | "tools_auto" | "culture_toys" | "general",
  "intent_choice": "store_ranking" | "clarification" | "comparison",
  "intent_confidence": 0.0 to 1.0,
  "needs_clarification_noul": 0.0 to 1.0,
  "user_dissatisfied_noul": 0.0 to 1.0,
  "max_price_toman": integer budget in Tomans (e.g. 15000000 for "15 میلیون") or null,
  "dealbreakers": {
    "require_open_now": 0.0 to 1.0,
    "require_installment": 0.0 to 1.0,
    "require_warranty": 0.0 to 1.0
  },
  "store_scores": {
    "w_price": {"level": 0 | 1 | 2, "confidence": 0.0 to 1.0},
    "w_distance": {"level": 0 | 1 | 2, "confidence": 0.0 to 1.0},
    "w_open_now": {"level": 0 | 1 | 2, "confidence": 0.0 to 1.0},
    "w_trust_freshness": {"level": 0 | 1 | 2, "confidence": 0.0 to 1.0},
    "w_installment": {"level": 0 | 1 | 2, "confidence": 0.0 to 1.0}
  },
  "extracted_traits": [
    {
      "aspect": "Neutral Persian attribute axis name ONLY without polarity (e.g. 'وزن و ابعاد دستگاه' or 'ارگونومی و ساختار کفی کفش')",
      "preference": "Specific Persian directional preference of the user on that axis (e.g. 'سبک و قابل حمل' or 'بدنه فلزی سنگین و صنعتی')",
      "is_durable": true if this reflects the user's personal taste/need, false if it is a one-off gift for someone else (e.g. 'کادو برای دوستم')
    }
  ]
}

Strict Rubric for `store_scores` (`level` MUST be 0, 1, or 2):
- `0`: Not mentioned in the message at all.
- `1`: Mildly mentioned or secondary preference.
- `2`: Strongly emphasized as the primary store criterion (e.g. 'ارزان‌ترین', 'نزدیک‌ترین', 'فقط قسطی', 'همین الان باز باشه').
"""


async def _evaluate_with_openai_compatible_llm(
    message: str,
    session_context: dict[str, Any] | None = None,
) -> SystemOneTurnEvaluation:
    """Call OpenRouter / OpenAI-compatible `/chat/completions` endpoint for live System-One turn evaluation."""
    api_key = settings.llm_api_key.strip()
    base_url = settings.llm_base_url.strip()
    if not _has_valid_api_key(api_key) or not base_url:
        raise RuntimeError(
            "کلید API مدل زبانی (LLM_API_KEY) در فایل .env تنظیم نشده است یا معتبر نیست."
        )

    prev_cat = (session_context or {}).get("active_category_name") or ""
    prev_dom = (session_context or {}).get("active_domain") or ""
    user_content = json.dumps(
        {
            "user_message": message,
            "previous_category": prev_cat,
            "previous_domain": prev_dom,
        },
        ensure_ascii=False,
    )

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "temperature": settings.llm_temperature,
                "messages": [
                    {"role": "system", "content": _SYSTEM_ONE_JSON_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"خطا در فراخوانی مدل زبانی {settings.llm_model} از {base_url} (کد {resp.status_code}): {resp.text[:300]}"
            )
        body = resp.json()
        raw_content = body["choices"][0]["message"]["content"]
        parsed = _extract_json_object(raw_content)

    domain = str(parsed.get("domain") or "general")
    if domain not in VALID_DOMAINS:
        domain = "general"

    intent_raw = str(parsed.get("intent_choice") or "store_ranking")
    intent: Literal["store_ranking", "clarification", "comparison", "product_discovery"] = (
        intent_raw
        if intent_raw in ("store_ranking", "clarification", "comparison", "product_discovery")
        else "store_ranking"
    )
    intent_conf = max(0.0, min(1.0, float(parsed.get("intent_confidence", 0.85))))

    needs_clarify = NoulJudgment(
        noul=max(0.0, min(1.0, float(parsed.get("needs_clarification_noul", 0.15)))),
        confidence=0.90,
    )
    user_dissat = NoulJudgment(
        noul=max(0.0, min(1.0, float(parsed.get("user_dissatisfied_noul", 0.05)))),
        confidence=0.90,
    )

    db_raw = parsed.get("dealbreakers") or {}
    dealbreakers = {
        "require_open_now": NoulJudgment(
            noul=max(0.0, min(1.0, float(db_raw.get("require_open_now", 0.05)))),
            confidence=0.90,
        ),
        "require_installment": NoulJudgment(
            noul=max(0.0, min(1.0, float(db_raw.get("require_installment", 0.05)))),
            confidence=0.90,
        ),
        "require_warranty": NoulJudgment(
            noul=max(0.0, min(1.0, float(db_raw.get("require_warranty", 0.05)))),
            confidence=0.90,
        ),
    }

    scores_raw = parsed.get("store_scores") or {}
    session_weights: dict[str, ScoreJudgment] = {}
    for key in ("w_price", "w_distance", "w_open_now", "w_trust_freshness", "w_installment"):
        entry = scores_raw.get(key) or {}
        level = float(entry.get("level", 0.0))
        norm_score = max(0.0, min(1.0, level / 2.0 if level > 1.0 or level in (0.0, 1.0, 2.0) else level))
        conf = max(0.0, min(1.0, float(entry.get("confidence", 0.88))))
        session_weights[key] = ScoreJudgment(score=norm_score, confidence=conf)

    # Populate legacy aliases from `w_trust_freshness`
    session_weights["w_score"] = session_weights["w_trust_freshness"]
    session_weights["w_freshness"] = session_weights["w_trust_freshness"]
    session_weights["w_warranty"] = session_weights["w_trust_freshness"]
    session_weights["w_verified_shop"] = session_weights["w_trust_freshness"]
    session_weights["w_mall_cluster"] = ScoreJudgment(score=0.0, confidence=0.80)
    session_weights["w_delivery_backup"] = ScoreJudgment(score=0.0, confidence=0.80)

    traits: list[ExtractedDomainTrait] = []
    dyn_specs: list[CandidateDynamicSpec] = []
    for idx, t in enumerate(parsed.get("extracted_traits") or []):
        aspect = str(t.get("aspect") or "").strip()
        pref = str(t.get("preference") or "").strip()
        is_dur = bool(t.get("is_durable", True))
        if aspect and pref:
            traits.append(
                ExtractedDomainTrait(
                    domain=domain,
                    aspect=aspect,
                    preference=pref,
                    is_durable=is_dur,
                )
            )
            dyn_specs.append(
                CandidateDynamicSpec(
                    feature_key=f"spec_dyn_{idx + 1}",
                    label_fa=aspect,
                    category_name=None,
                    weight=0.85,
                    confidence=0.88,
                )
            )

    max_p_raw = parsed.get("max_price_toman")
    max_price_toman = int(max_p_raw) if isinstance(max_p_raw, (int, float)) and max_p_raw > 0 else None

    return SystemOneTurnEvaluation(
        intent_choice=ChoiceJudgment(
            choice=intent,
            confidence=intent_conf,
            probabilities={intent: intent_conf},
        ),
        session_weights=session_weights,
        dealbreakers=dealbreakers,
        user_dissatisfied=user_dissat,
        domain=domain,
        needs_clarification=needs_clarify,
        extracted_traits=traits,
        candidate_dynamic_specs=dyn_specs,
        max_price_toman=max_price_toman,
        engine_mode_used="openai_compatible_system_one",
    )


async def evaluate_turn_with_jev(
    message: str,
    session_context: dict[str, Any] | None = None,
) -> SystemOneTurnEvaluation:
    """Evaluate a user shopping prompt strictly via live TypeSafe `Jev` or OpenRouter/OpenAI-compatible LLM."""
    if _has_valid_api_key(settings.typesafe_api_key):
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
            if resp.status_code != 200:
                raise RuntimeError(
                    f"خطا در فراخوانی TypeSafe Jev (کد {resp.status_code}): {resp.text[:300]}"
                )
            data = resp.json().get("answers", {})
            # If LLM_API_KEY is also set, extract open-vocabulary traits via LLM; else build from Jev answers
            if _has_valid_api_key(settings.llm_api_key):
                eval_res = await _evaluate_with_openai_compatible_llm(message, session_context=session_context)
            else:
                eval_res = SystemOneTurnEvaluation(
                    intent_choice=ChoiceJudgment(choice="store_ranking", confidence=0.88),
                    session_weights={},
                    dealbreakers={
                        "require_open_now": NoulJudgment(noul=0.05),
                        "require_installment": NoulJudgment(noul=0.05),
                        "require_warranty": NoulJudgment(noul=0.05),
                    },
                    user_dissatisfied=NoulJudgment(noul=0.05),
                )
            if "domain" in data and isinstance(data["domain"], dict):
                chosen_dom = str(data["domain"].get("choice") or eval_res.domain)
                if chosen_dom in VALID_DOMAINS:
                    eval_res.domain = chosen_dom
            for key in ("w_price", "w_distance", "w_open_now", "w_trust_freshness", "w_installment"):
                if key in data and isinstance(data[key], dict):
                    raw_score = float(data[key].get("score", 0.0))
                    norm_score = raw_score / 2.0 if raw_score > 1.0 else raw_score
                    conf = float(data[key].get("confidence", 0.85))
                    eval_res.session_weights[key] = ScoreJudgment(
                        score=max(0.0, min(1.0, norm_score)),
                        confidence=max(0.0, min(1.0, conf)),
                    )
            if "needs_clarification" in data and isinstance(data["needs_clarification"], dict):
                eval_res.needs_clarification = NoulJudgment(
                    noul=float(data["needs_clarification"].get("noul", 0.15)),
                    confidence=float(data["needs_clarification"].get("confidence", 0.9)),
                )
            if "require_installment" in data and isinstance(data["require_installment"], dict):
                eval_res.dealbreakers["require_installment"] = NoulJudgment(
                    noul=float(data["require_installment"].get("noul", 0.1)),
                    confidence=float(data["require_installment"].get("confidence", 0.9)),
                )
            if "require_open_now" in data and isinstance(data["require_open_now"], dict):
                eval_res.dealbreakers["require_open_now"] = NoulJudgment(
                    noul=float(data["require_open_now"].get("noul", 0.1)),
                    confidence=float(data["require_open_now"].get("confidence", 0.9)),
                )
            if "user_dissatisfied" in data and isinstance(data["user_dissatisfied"], dict):
                eval_res.user_dissatisfied = NoulJudgment(
                    noul=float(data["user_dissatisfied"].get("noul", 0.08)),
                    confidence=float(data["user_dissatisfied"].get("confidence", 0.9)),
                )
            eval_res.engine_mode_used = "typesafe_sdk"
            return eval_res

    return await _evaluate_with_openai_compatible_llm(message, session_context=session_context)


async def check_same_aspect_noul(aspect_a: str, aspect_b: str) -> NoulJudgment:
    """Evaluate strictly via live Jev / OpenRouter model whether `aspect_a` and `aspect_b` are the same attribute axis."""
    if _has_valid_api_key(settings.typesafe_api_key):
        async with httpx.AsyncClient(timeout=settings.typesafe_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.typesafe_base_url.rstrip('/')}/systemone",
                headers={"Authorization": f"Bearer {settings.typesafe_api_key.strip()}"},
                json={
                    "model": settings.typesafe_model,
                    "state": {"aspect_a": aspect_a, "aspect_b": aspect_b},
                    "questions": {
                        "same_aspect": {
                            "type": "noul",
                            "instructions": "Do aspect_a and aspect_b refer to the exact same product attribute axis (even if phrased differently)?",
                        }
                    },
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f"TypeSafe Noul error ({resp.status_code}): {resp.text[:200]}")
            ans = resp.json().get("answers", {}).get("same_aspect", {})
            return NoulJudgment(
                noul=float(ans.get("noul", 0.0)),
                confidence=float(ans.get("confidence", 0.90)),
            )

    api_key = settings.llm_api_key.strip()
    base_url = settings.llm_base_url.strip()
    if not _has_valid_api_key(api_key) or not base_url:
        raise RuntimeError(
            "کلید API مدل زبانی (LLM_API_KEY) برای بررسی هم‌محور بودن ویژگی‌ها در .env تنظیم نشده است."
        )

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "temperature": 0.0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Determine whether aspect_a and aspect_b refer to the same product attribute axis "
                            "(regardless of polarity). Return ONLY JSON: {\"noul\": 0.0 to 1.0, \"confidence\": 0.0 to 1.0}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps({"aspect_a": aspect_a, "aspect_b": aspect_b}, ensure_ascii=False),
                    },
                ],
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LLM Noul error ({resp.status_code}): {resp.text[:200]}")
        parsed = _extract_json_object(resp.json()["choices"][0]["message"]["content"])
        return NoulJudgment(
            noul=max(0.0, min(1.0, float(parsed.get("noul", 0.0)))),
            confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.90)))),
        )


async def check_feature_equivalence_noul(label_a: str, label_b: str) -> NoulJudgment:
    """Evaluate feature equivalence strictly via the live model."""
    return await check_same_aspect_noul(label_a, label_b)
