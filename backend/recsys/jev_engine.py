"""Live System One Decision Engine (`Jev` / OpenRouter OpenAI-Compatible Live API).

All heuristic/keyword simulators and hash-based embedding fallbacks have been removed.
Every turn evaluation, aspect deduplication check, and text embedding is served strictly
by the configured live model (`TYPESAFE_API_KEY` or `LLM_API_KEY` / OpenRouter in `.env`).
"""

import asyncio
from dataclasses import dataclass, field
import asyncio
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
    min_price_toman: int | None = None
    max_price_toman: int | None = None
    product_search_query: str = ""
    category_keywords: list[str] = field(default_factory=list)
    is_accessory_request: bool = False
    price_tier: Literal["budget", "mid", "flagship"] = "mid"
    engine_mode_used: str = "typesafe_sdk"


def _has_valid_api_key(key: str) -> bool:
    cleaned = (key or "").strip()
    return bool(cleaned and cleaned not in ("sk-replace-me", "your-api-key", "replace-me"))


def _resolve_decision_endpoint_url(base_url: str) -> str:
    """Resolve `TYPESAFE_BASE_URL` to the exact Decision API endpoint (`generativelanguage.googleapis.com/v1beta/decisions` or `api.typesafe.ai/v1/systemone`)."""
    cleaned = (base_url or "https://generativelanguage.googleapis.com/v1beta/decisions").strip().rstrip("/")
    if "generativelanguage.googleapis.com" in cleaned:
        if cleaned.endswith("/decisions"):
            return cleaned
        return "https://generativelanguage.googleapis.com/v1beta/decisions"
    if cleaned.endswith("/v1/systemone") or cleaned.endswith("/api/v1/decisions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/systemone"
    return f"{cleaned}/v1/systemone"


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Parse JSON object from LLM response content (stripping <thought> blocks and markdown fences)."""
    cleaned = re.sub(r"<thought>.*?</thought>", "", raw_text or "", flags=re.S).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end >= start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


async def _call_decision_model(state_payload: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    """Call the dedicated Decision Model (`gemini-decision-1` on Google AI Studio or `Jev` on TypeSafe).

    Strictly never substitutes an LLM for decision scoring. Raises `RuntimeError` immediately on any error.
    """
    api_key = settings.typesafe_api_key.strip()
    if not _has_valid_api_key(api_key):
        raise RuntimeError(
            "کلید API مدل تصمیم‌گیرنده (TYPESAFE_API_KEY) در فایل .env تنظیم نشده است."
        )
    target_url = _resolve_decision_endpoint_url(settings.typesafe_base_url)
    model_name = settings.typesafe_model.strip() or "gemini-decision-1"

    if "generativelanguage.googleapis.com" in target_url:
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        body_payload: dict[str, Any] = {
            "model": model_name,
            "input": json.dumps(state_payload, ensure_ascii=False),
            "questions": questions,
        }
    else:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body_payload = {
            "model": model_name,
            "state": state_payload,
            "questions": questions,
        }

    try:
        async with httpx.AsyncClient(timeout=settings.typesafe_timeout_seconds) as client:
            for attempt in range(3):
                resp = await client.post(target_url, headers=headers, json=body_payload)
                if resp.status_code not in (429, 502, 503, 504) or attempt == 2:
                    break
                await asyncio.sleep(1.2 * (attempt + 1))
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"خطای شبکه/تایم‌اوت در فراخوانی مدل Decision ({model_name}) از {target_url}: {type(exc).__name__} ({exc})"
        ) from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"خطا در فراخوانی مدل Decision ({model_name}) از {target_url} (کد {resp.status_code}): {resp.text[:300]}"
        )
    resp_json = resp.json()
    if isinstance(resp_json.get("data"), dict) and "answers" in resp_json["data"]:
        return resp_json["data"]["answers"]
    return resp_json.get("answers", {})


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
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"خطای شبکه/تایم‌اوت در فراخوانی امبدینگ {settings.embedding_model} از {base_url}: {type(exc).__name__} ({exc})"
        ) from exc
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
        # Pad or truncate (e.g. Matryoshka 3072 -> 1536 for gemini-embedding-2) and L2-renormalize
        if len(vec) > target_dim:
            vec = vec[:target_dim]
        else:
            vec = vec + [0.0] * (target_dim - len(vec))
        norm_sq = sum(x * x for x in vec)
        if norm_sq > 1e-12:
            inv_norm = 1.0 / (norm_sq ** 0.5)
            vec = [x * inv_norm for x in vec]
    return [round(x, 6) for x in vec]


_LLM_TEXT_EXTRACTION_PROMPT = """You are the natural-language entity extraction assistant for Torob's in-person shopping assistant in Tehran.
Do NOT output any scores, weights, or probabilities.
Extract the clean core product search query, canonical Persian category keywords, whether the shopper is asking for an accessory/spare-part, explicit budget range (if any), and open-vocabulary product feature traits as a JSON object.
Note on colloquial Iranian currency: when a shopper says a small number like "۵-۶ تومن" or "۴۵ تومن" for consumer goods, convert to Tomans (e.g. 5,000,000 to 6,000,000 Tomans, or 45,000,000 Tomans).

{
  "product_search_query": "Clean Persian core product/model/brand noun ONLY without conversational filler, adjectives, or Tehran locations",
  "category_keywords": ["1 to 3 canonical Persian product category names matching the item in an e-commerce catalog"],
  "is_accessory_request": false,
  "min_price_toman": integer lower budget bound in Tomans or null,
  "max_price_toman": integer upper budget bound in Tomans or null,
  "extracted_traits": [
    {
      "aspect": "Neutral Persian attribute axis name ONLY without polarity",
      "preference": "Specific Persian directional preference of the user on that axis",
      "is_durable": true
    }
  ]
}
"""


async def _extract_traits_and_budget_with_llm(
    message: str,
    domain: str,
    session_context: dict[str, Any] | None = None,
) -> tuple[str, list[str], bool, list[ExtractedDomainTrait], list[CandidateDynamicSpec], int | None, int | None]:
    """Use the Language Model (LLM) strictly for non-scoring text extraction.

    Never outputs scores, weights, or probabilities, and never falls back to another model.
    """
    api_key = settings.llm_api_key.strip()
    base_url = settings.llm_base_url.strip()
    if not _has_valid_api_key(api_key) or not base_url:
        raise RuntimeError(
            "کلید API مدل زبانی (LLM_API_KEY) در فایل .env تنظیم نشده است یا معتبر نیست."
        )

    prev_cat = (session_context or {}).get("active_category_name") or ""
    prev_query = (session_context or {}).get("last_query") or ""
    user_content = json.dumps(
        {
            "user_message": message,
            "previous_query": prev_query,
            "previous_category": prev_cat,
            "domain": domain,
        },
        ensure_ascii=False,
    )

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for attempt in range(3):
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
                            {"role": "system", "content": _LLM_TEXT_EXTRACTION_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                    },
                )
                if resp.status_code not in (429, 502, 503, 504) or attempt == 2:
                    break
                await asyncio.sleep(1.2 * (attempt + 1))
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"خطای شبکه/تایم‌اوت در اتصال به مدل زبانی ({settings.llm_model}) در {base_url}: {type(exc).__name__} ({exc})"
        ) from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"خطا در فراخوانی مدل زبانی ({settings.llm_model}) از {base_url} (کد {resp.status_code}): {resp.text[:300]}"
        )
    body = resp.json()
    raw_content = body["choices"][0]["message"]["content"]
    parsed = _extract_json_object(raw_content)

    product_search_query = str(parsed.get("product_search_query") or "").strip() or message
    raw_cat_kws = parsed.get("category_keywords") or []
    category_keywords = [str(k).strip() for k in raw_cat_kws if str(k).strip()] if isinstance(raw_cat_kws, list) else []
    is_accessory_request = bool(parsed.get("is_accessory_request", False))

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

    min_p_raw = parsed.get("min_price_toman")
    min_price_toman = (
        int(min_p_raw) if isinstance(min_p_raw, (int, float)) and min_p_raw > 0 else None
    )
    max_p_raw = parsed.get("max_price_toman")
    max_price_toman = (
        int(max_p_raw) if isinstance(max_p_raw, (int, float)) and max_p_raw > 0 else None
    )
    return (
        product_search_query,
        category_keywords,
        is_accessory_request,
        traits,
        dyn_specs,
        min_price_toman,
        max_price_toman,
    )


async def evaluate_turn_with_jev(
    message: str,
    session_context: dict[str, Any] | None = None,
    skip_llm_extraction: bool = False,
    candidate_categories: list[str] | None = None,
) -> SystemOneTurnEvaluation:
    """Evaluate a shopping turn with strict separation of responsibilities:
    1. Decision Model (`gemini-decision-1` / `Jev`): computes ALL `choice`, `score`, and `noul` judgments.
    2. Language Model (`LLM`): extracts ONLY open-vocabulary text traits (`aspect`/`preference`) and budget.
    Neither model ever substitutes for the other.
    """
    state_payload = {
        "user_message": message,
        "previous_category": (session_context or {}).get("active_category_name"),
    }
    questions: dict[str, Any] = {
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
        "intent_choice": {
            "type": "choice",
            "instructions": "What is the primary shopping action requested in the message?",
            "criteria": {
                "store_ranking": "Finding, ranking, or visiting physical stores to buy a product",
                "comparison": "Comparing two or more product models side by side",
                "clarification": "Broad or ambiguous need that requires narrowing down options first",
            },
        },
        "price_tier": {
            "type": "choice",
            "instructions": "What product price tier best matches the shopper's request, persona, and use-case?",
            "criteria": {
                "budget": "Shopper asks for cheap, economical, student, basic, entry-level, or minimum-price items (e.g. 'ارزان', 'دانشجویی', 'اقتصادی', 'کف قیمت', 'معمولی').",
                "mid": "Shopper wants a balanced midrange or standard everyday product without asking for the cheapest possible item.",
                "flagship": "Shopper explicitly asks for pro, luxury, flagship, high-end gaming, or top-tier expensive models.",
            },
        },
        "needs_clarification": {
            "type": "noul",
            "instructions": (
                "Did the shopper leave their in-person store visiting preference "
                "(whether they prefer the closest open store right now vs. the lowest price across Tehran vs. installment/credit payment) "
                "unspecified in this message?"
            ),
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
        "require_warranty": {
            "type": "noul",
            "instructions": "Does the shopper explicitly require an official or corporate warranty?",
        },
        "w_price": {
            "type": "score",
            "instructions": "How much does the shopper care about affordable, reasonable, economical, or low price in their request?",
            "criteria": [
                "The shopper did not mention price, affordability, or budget at all.",
                "The shopper mentioned a budget or wants a reasonable/fair/good price (e.g. 'قیمت مناسب', 'به صرفه').",
                "The shopper strongly emphasizes getting the cheapest, most economical, or lowest possible price (e.g. 'ارزان', 'اقتصادی', 'کف قیمت').",
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
    }

    valid_cand_cats = [c for c in (candidate_categories or []) if c][:10]
    if len(valid_cand_cats) >= 2:
        questions["target_category"] = {
            "type": "choice",
            "instructions": "Which database product category best matches the core item the shopper wants to buy (choose the main product category, NOT spare parts or accessories, unless the shopper explicitly asked for an accessory/part)?",
            "criteria": {
                cat: f"Products in catalog category '{cat}'"
                for cat in valid_cand_cats
            },
        }

    # 1. Strictly evaluate all scores, choices, and nouls with the Decision Model (`gemini-decision-1`)
    data = await _call_decision_model(state_payload, questions)

    chosen_db_category: str | None = None
    if len(valid_cand_cats) == 1:
        chosen_db_category = valid_cand_cats[0]
    elif isinstance(data.get("target_category"), dict):
        cand_cat = str(data["target_category"].get("choice") or "").strip()
        if cand_cat in valid_cand_cats:
            chosen_db_category = cand_cat

    domain = "general"
    if "domain" in data and isinstance(data["domain"], dict):
        chosen_dom = str(data["domain"].get("choice") or "general")
        if chosen_dom in VALID_DOMAINS:
            domain = chosen_dom

    intent_raw = "store_ranking"
    intent_conf = 0.88
    intent_probs: dict[str, float] = {}
    if "intent_choice" in data and isinstance(data["intent_choice"], dict):
        cand_intent = str(data["intent_choice"].get("choice") or "store_ranking")
        if cand_intent in ("store_ranking", "clarification", "comparison", "product_discovery"):
            intent_raw = cand_intent
        intent_conf = max(0.0, min(1.0, float(data["intent_choice"].get("confidence", 0.88))))
        raw_probs = data["intent_choice"].get("probabilities") or {}
        if isinstance(raw_probs, dict):
            intent_probs = {str(k): float(v) for k, v in raw_probs.items()}

    session_weights: dict[str, ScoreJudgment] = {}
    for key in ("w_price", "w_distance", "w_open_now", "w_trust_freshness", "w_installment"):
        entry = data.get(key) if isinstance(data.get(key), dict) else {}
        raw_score = float(entry.get("score", 0.0))
        norm_score = max(0.0, min(1.0, raw_score / 2.0))
        conf = max(0.0, min(1.0, float(entry.get("confidence", 0.85))))
        session_weights[key] = ScoreJudgment(score=norm_score, confidence=conf)

    # Populate legacy slot aliases from `w_trust_freshness`
    session_weights["w_score"] = session_weights["w_trust_freshness"]
    session_weights["w_freshness"] = session_weights["w_trust_freshness"]
    session_weights["w_warranty"] = session_weights["w_trust_freshness"]
    session_weights["w_verified_shop"] = session_weights["w_trust_freshness"]
    session_weights["w_mall_cluster"] = ScoreJudgment(score=0.0, confidence=0.80)
    session_weights["w_delivery_backup"] = ScoreJudgment(score=0.0, confidence=0.80)

    def _read_noul(q_key: str, default_val: float) -> NoulJudgment:
        item = data.get(q_key) if isinstance(data.get(q_key), dict) else {}
        return NoulJudgment(
            noul=max(0.0, min(1.0, float(item.get("noul", default_val)))),
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.90)))),
        )

    dealbreakers = {
        "require_open_now": _read_noul("require_open_now", 0.05),
        "require_installment": _read_noul("require_installment", 0.05),
        "require_warranty": _read_noul("require_warranty", 0.05),
    }
    needs_clarify = _read_noul("needs_clarification", 0.15)
    user_dissat = _read_noul("user_dissatisfied", 0.05)

    price_tier: Literal["budget", "mid", "flagship"] = "mid"
    if isinstance(data.get("price_tier"), dict):
        cand_tier = str(data["price_tier"].get("choice") or "mid")
        if cand_tier in ("budget", "mid", "flagship"):
            price_tier = cand_tier  # type: ignore[assignment]
    if session_weights["w_price"].score >= 0.45:
        price_tier = "budget"

    # 2. Strictly use the Language Model (LLM) ONLY for text trait extraction, clean search noun, and explicit budget parsing
    if skip_llm_extraction:
        product_search_query = str((session_context or {}).get("product_search_query") or message)
        category_keywords = list((session_context or {}).get("category_keywords") or [])
        is_accessory_request = bool((session_context or {}).get("is_accessory_request") or False)
        traits = []
        dyn_specs = []
        min_price_toman = None
        max_price_toman = None
    else:
        (
            product_search_query,
            category_keywords,
            is_accessory_request,
            traits,
            dyn_specs,
            min_price_toman,
            max_price_toman,
        ) = await _extract_traits_and_budget_with_llm(
            message, domain=domain, session_context=session_context
        )

    if chosen_db_category:
        category_keywords = [chosen_db_category, *[k for k in category_keywords if k != chosen_db_category]]

    return SystemOneTurnEvaluation(
        intent_choice=ChoiceJudgment(
            choice=intent_raw,  # type: ignore[arg-type]
            confidence=intent_conf,
            probabilities=intent_probs or {intent_raw: intent_conf},
        ),
        session_weights=session_weights,
        dealbreakers=dealbreakers,
        user_dissatisfied=user_dissat,
        domain=domain,
        needs_clarification=needs_clarify,
        extracted_traits=traits,
        candidate_dynamic_specs=dyn_specs,
        min_price_toman=min_price_toman,
        max_price_toman=max_price_toman,
        product_search_query=product_search_query,
        category_keywords=category_keywords,
        is_accessory_request=is_accessory_request,
        price_tier=price_tier,
        engine_mode_used="typesafe_sdk",
    )


async def score_candidate_products_with_decision_model(
    user_message: str,
    candidates: list[dict[str, Any]],
    domain_traits: list[dict[str, Any]] | None = None,
    max_price_toman: int | None = None,
    price_tier: str = "mid",
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Stage-1 Product Ranking strictly powered by the Decision Model (`gemini-decision-1`).

    Evaluates all candidate products in a single `/v1beta/decisions` forward pass (`total_output_tokens: 0`)
    and ranks them by calibrated expected utility score.
    """
    if not candidates:
        return []

    traits = domain_traits or []
    trait_summary = [
        {"aspect": str(t.get("aspect") or ""), "preference": str(t.get("preference") or "")}
        for t in traits
        if t.get("preference")
    ]
    compact_candidates = [
        {
            "idx": i,
            "title": str(c.get("title") or ""),
            "category": str(c.get("category_name") or ""),
            "min_price_toman": int(c.get("min_price_toman") or 0),
            "store_count": int(c.get("store_count") or 1),
            "specs": dict(list((c.get("specs") or {}).items())[:5]),
        }
        for i, c in enumerate(candidates[:10])
    ]

    min_pool_price = min((c["min_price_toman"] for c in compact_candidates if c["min_price_toman"] > 0), default=0)
    state_payload = {
        "shopper_request": user_message,
        "target_price_tier": price_tier,
        "category_minimum_price_toman": min_pool_price,
        "shopper_domain_preferences": trait_summary,
        "max_budget_toman": max_price_toman,
        "candidate_products": compact_candidates,
    }
    questions: dict[str, Any] = {}
    tier_guidance = (
        "The shopper explicitly wants a BUDGET / STUDENT / ECONOMICAL item (target_price_tier='budget'): strongly reward affordable models near the category minimum price and heavily penalize expensive models."
        if price_tier == "budget"
        else "Evaluate overall product quality, specs, and price suitability for the shopper's request."
    )
    for c in compact_candidates:
        idx = c["idx"]
        questions[f"prod_{idx}"] = {
            "type": "score",
            "instructions": (
                f"How well does candidate product #{idx} ({c['title']} in category '{c['category']}', "
                f"price {c['min_price_toman']:,} Toman, specs: {json.dumps(c['specs'], ensure_ascii=False)}) "
                f"match the shopper's request, use-case, and price tier? {tier_guidance}"
            ),
            "criteria": [
                "Irrelevant product, wrong category, overpriced for a budget/student request, or unsuitable.",
                "Weak or partial match with suboptimal price or specs for the shopper's use-case.",
                "Good product match that satisfies the shopper's category, use-case, and price tier.",
                "Ideal product match with strong suitability and optimal price for the shopper's exact need.",
            ],
        }

    answers = await _call_decision_model(state_payload, questions)

    scored_list: list[dict[str, Any]] = []
    for i, orig in enumerate(candidates[:10]):
        item = dict(orig)
        ans = answers.get(f"prod_{i}") if isinstance(answers.get(f"prod_{i}"), dict) else {}
        raw_score = float(ans.get("score", 1.5))
        norm_score = max(0.0, min(1.0, raw_score / 3.0))
        conf = max(0.0, min(1.0, float(ans.get("confidence", 0.85))))
        item["trgm_sim"] = round(norm_score, 4)
        item["decision_score"] = round(norm_score, 4)
        item["decision_confidence"] = round(conf, 4)
        if trait_summary and not item.get("matched_traits"):
            item["matched_traits"] = [t["preference"] for t in trait_summary[:2]]
        scored_list.append(item)

    if price_tier == "budget":
        scored_list.sort(
            key=lambda p: (
                round(float(p.get("decision_score") or 0.0), 1),
                -int(p.get("min_price_toman") or 0),
            ),
            reverse=True,
        )
    else:
        scored_list.sort(
            key=lambda p: (float(p.get("decision_score") or 0.0), int(p.get("store_count") or 0)),
            reverse=True,
        )
    return scored_list[:limit]


async def check_same_aspect_noul(aspect_a: str, aspect_b: str) -> NoulJudgment:
    """Evaluate strictly via the Decision Model (`gemini-decision-1` / `Jev`) whether `aspect_a` and `aspect_b` share the same axis.

    Never uses an LLM for `noul` probability evaluation.
    """
    answers = await _call_decision_model(
        state_payload={"aspect_a": aspect_a, "aspect_b": aspect_b},
        questions={
            "same_aspect": {
                "type": "noul",
                "instructions": "Do aspect_a and aspect_b refer to the exact same product attribute axis (even if phrased differently)?",
            }
        },
    )
    ans = answers.get("same_aspect", {}) if isinstance(answers.get("same_aspect"), dict) else {}
    return NoulJudgment(
        noul=max(0.0, min(1.0, float(ans.get("noul", 0.0)))),
        confidence=max(0.0, min(1.0, float(ans.get("confidence", 0.90)))),
    )


async def check_feature_equivalence_noul(label_a: str, label_b: str) -> NoulJudgment:
    """Evaluate feature equivalence strictly via the Decision Model."""
    return await check_same_aspect_noul(label_a, label_b)
