"""Live Two-Layer Adaptive System One Decision Engine (`gemini-decision-1` / `Jev` + LLM Extraction).

Zero hardcoded categories, domains, keyword lists, or heuristic simulators:
- Decision Model (`TYPESAFE_API_KEY`): computes ALL calibrated `choice`, `score`, and `noul` judgments,
  including selective cross-category trait transfer, category price-prior transfer, ephemeral/gift shield,
  product candidate scoring + semantic trait satisfaction, and open-vocabulary store offer scoring.
- Language Model (`LLM_API_KEY`): extracts ONLY non-scoring open-vocabulary text entities (`product_search_query`,
  `catalog_search_terms`, `category_keywords`, `custom_offer_criterion`, `extracted_traits`, and budget).
"""

import asyncio
from dataclasses import dataclass, field
import json
import re
from typing import Any, Literal

import httpx

from backend.config import settings
from backend.db.normalizer import normalize_persian_text

# 5 Orthogonal Numerical Store Criteria + Optional Conditional Slot 6 (`w_offer_custom`)
STORE_CRITERIA_CATALOG: dict[str, dict[str, Any]] = {
    "w_price": {"slot": 1, "group": "base", "label_fa": "کمترین قیمت و صرفه اقتصادی"},
    "w_distance": {"slot": 2, "group": "base", "label_fa": "نزدیکی و سرعت دسترسی"},
    "w_open_now": {"slot": 3, "group": "base", "label_fa": "باز بودن فروشگاه در این لحظه"},
    "w_trust_freshness": {"slot": 4, "group": "base", "label_fa": "تازگی قیمت، اعتبار و گارانتی"},
    "w_installment": {"slot": 5, "group": "persona", "label_fa": "پرداخت اقساطی حضوری (ترب‌پی/اسنپ‌پی)"},
}

CUSTOM_OFFER_SLOT_META: dict[str, Any] = {
    "slot": 6,
    "group": "dynamic",
    "label_fa": "تطابق شرط خاص فروشگاهی",
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
    """Calibrated `Choice` categorical primitive output."""

    choice: Literal["store_ranking", "clarification", "comparison", "product_discovery"]
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class ExtractedTrait:
    """Category-agnostic user trait separating attribute axis (`aspect`) from directional `preference`."""

    aspect: str
    preference: str
    is_durable: bool = True
    confidence: float = 0.88


@dataclass
class SystemOneTurnEvaluation:
    """Complete parallel System One + LLM extraction output for a single user conversational turn."""

    intent_choice: ChoiceJudgment
    session_weights: dict[str, ScoreJudgment]
    dealbreakers: dict[str, NoulJudgment]
    user_dissatisfied: NoulJudgment
    needs_clarification: NoulJudgment = field(default_factory=lambda: NoulJudgment(noul=0.15, confidence=0.85))
    is_ephemeral_or_gift: NoulJudgment = field(default_factory=lambda: NoulJudgment(noul=0.05, confidence=0.90))
    extracted_traits: list[ExtractedTrait] = field(default_factory=list)
    transferred_traits: list[dict[str, Any]] = field(default_factory=list)
    inferred_price_percentile: float | None = None
    min_price_toman: int | None = None
    max_price_toman: int | None = None
    product_search_query: str = ""
    catalog_search_terms: list[str] = field(default_factory=list)
    category_keywords: list[str] = field(default_factory=list)
    is_accessory_request: bool = False
    wants_used_or_stock: bool = False
    max_distance_km: float | None = None
    require_torob_pay: bool = False
    custom_offer_criterion: str = ""
    clarification_questions: list[dict[str, Any]] = field(default_factory=list)
    price_tier: Literal["budget", "mid", "flagship"] = "mid"
    is_continuation: bool = False
    engine_mode_used: str = "typesafe_sdk"


def _has_valid_api_key(key: str) -> bool:
    cleaned = (key or "").strip()
    return bool(cleaned and cleaned not in ("sk-replace-me", "your-api-key", "replace-me"))


def _resolve_decision_endpoint_url(base_url: str) -> str:
    """Resolve `TYPESAFE_BASE_URL` to the Decision API endpoint."""
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


_SHARED_HTTP_CLIENT: httpx.AsyncClient | None = None
_SHARED_HTTP_LOOP_ID: int | None = None


def _get_shared_http_client() -> httpx.AsyncClient:
    """Return a shared `httpx.AsyncClient` bound to the active event loop for TCP+TLS reuse."""
    global _SHARED_HTTP_CLIENT, _SHARED_HTTP_LOOP_ID
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = None
    if (
        _SHARED_HTTP_CLIENT is None
        or _SHARED_HTTP_CLIENT.is_closed
        or _SHARED_HTTP_LOOP_ID != loop_id
    ):
        _SHARED_HTTP_CLIENT = httpx.AsyncClient(
            timeout=max(settings.typesafe_timeout_seconds, settings.llm_timeout_seconds)
        )
        _SHARED_HTTP_LOOP_ID = loop_id
    return _SHARED_HTTP_CLIENT


async def close_shared_http_client() -> None:
    """Close the shared `httpx.AsyncClient` on application shutdown."""
    global _SHARED_HTTP_CLIENT, _SHARED_HTTP_LOOP_ID
    if _SHARED_HTTP_CLIENT is not None and not _SHARED_HTTP_CLIENT.is_closed:
        await _SHARED_HTTP_CLIENT.aclose()
    _SHARED_HTTP_CLIENT = None
    _SHARED_HTTP_LOOP_ID = None


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

    resp: httpx.Response | None = None
    client = _get_shared_http_client()
    for attempt in range(5):
        try:
            resp = await client.post(
                target_url,
                headers=headers,
                json=body_payload,
                timeout=settings.typesafe_timeout_seconds,
            )
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 4:
                break
            if resp.status_code == 429:
                m_delay = re.search(r"retryDelay\"\s*:\s*\"(\d+)", resp.text or "")
                wait_s = min(28.0, float(m_delay.group(1)) + 1.5) if m_delay else min(20.0, 3.0 * (2**attempt))
                await asyncio.sleep(wait_s)
                continue
        except httpx.HTTPError as exc:
            if attempt == 4:
                raise RuntimeError(
                    f"خطای شبکه/تایم‌اوت در فراخوانی مدل Decision ({model_name}) از {target_url}: {type(exc).__name__} ({exc})"
                ) from exc
        await asyncio.sleep(1.5 * (2**attempt))
    assert resp is not None

    if resp.status_code != 200:
        raise RuntimeError(
            f"خطا در فراخوانی مدل Decision ({model_name}) از {target_url} (کد {resp.status_code}): {resp.text[:300]}"
        )
    resp_json = resp.json()
    if isinstance(resp_json.get("data"), dict) and "answers" in resp_json["data"]:
        return resp_json["data"]["answers"]
    return resp_json.get("answers", {})


async def embed_text_async(text: str, dim: int | None = None) -> list[float]:
    """Generate an embedding vector strictly via the configured live `/embeddings` API."""
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
        client = _get_shared_http_client()
        resp = await client.post(
            f"{base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.llm_timeout_seconds,
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
        if len(vec) > target_dim:
            vec = vec[:target_dim]
        else:
            vec = vec + [0.0] * (target_dim - len(vec))
        norm_sq = sum(x * x for x in vec)
        if norm_sq > 1e-12:
            inv_norm = 1.0 / (norm_sq ** 0.5)
            vec = [x * inv_norm for x in vec]
    return [round(x, 6) for x in vec]


_LLM_TEXT_EXTRACTION_PROMPT = """You are the stateful multi-turn entity extraction assistant for Torob's in-person shopping assistant in Tehran.
Do NOT output any scores, weights, or probabilities, and do NOT classify into fixed domains.
You receive `user_message` together with `current_session_state` (the accumulated shopping state from earlier turns and clarification answers).
Extract a clean JSON object for ANY product category in Torob's catalog:
- Set `is_continuation` to `true` whenever `current_session_state.product_search_query` or `current_session_state.active_category_name` is non-empty AND `user_message` is a follow-up, refinement, clarification answer, comparison request, or store/payment/location filter on that same item (e.g. "فقط فروشگاه‌های دارای ترب‌پی", "نمایش روی نقشه تهران", "مقایسه مشخصات فنی مدل‌ها", "رو گوش (On-Ear)", "ارزون‌ترش رو بیار", "سفیدش رو می‌خوام"). Set `is_continuation` to `false` ONLY when starting a brand-new product search or switching to a completely unrelated product category.
- When `is_continuation` is `true`:
  1. Keep `product_search_query` and `category_keywords` anchored to the core product in `current_session_state` (refine `product_search_query` only if the user adds a specific brand/model for that same item; NEVER replace `product_search_query` with store/payment filter phrases like "فقط فروشگاه‌های دارای ترب‌پی").
  2. Return the CUMULATIVE `catalog_search_terms` and `extracted_traits` by merging `current_session_state` with any new product attributes or clarification answers in `user_message` (if the user updates an existing `aspect`, replace its `preference` with the new one).
- Convert colloquial Iranian Tomans (e.g. "۵-۶ تومن" -> 5000000..6000000, "۴۵ تومن" -> 45000000).
- If the shopper explicitly specifies a maximum travel radius in kilometers (e.g. "تا ۵ کیلومتر", "زیر ۳ کیلومتری"), set `max_distance_km` to that number (e.g. `5.0`); otherwise `null`.
- In `catalog_search_terms`, translate indirect, colloquial, functional, or clarification-selected needs into 1 to 6 concrete Persian/English terms that appear in catalog titles, technical specs, or seller offer descriptions (e.g. "صدای اطراف نیاد" -> ["حذف نویز", "ANC", "نویز کنسلینگ"]; "رو گوش (On-Ear)" -> ["رو گوش", "On-Ear", "هدست"]; "کمرم درد نگیره" -> ["طبی", "ارگونومیک"]; "استوک تمیز" -> ["استوک", "گرید"]).
- In `custom_offer_criterion`, capture ONLY a specific target destination mall/street/market (e.g. "پاساژ چارسو", "پاساژ علاءالدین") or a specific seller-offer attribute (e.g. "پارت نامبر ZAA", "رنگ مشکی موجود", "ریجستر شده"). Leave `custom_offer_criterion` as `""` when the user only mentions generic open-now ("مغازه باز حضوری"), installment/TorobPay, official/corporate warranty, cheap price, distance radius ("تا ۵ کیلومتر"), or merely states their own current starting location ("نزدیک تجریش هستم", "سمت صادقیه هستم").
- Set `is_durable` to `false` if a preference is for a gift, another person, or a one-time temporary situation.

{
  "is_continuation": false,
  "product_search_query": "Clean Persian core product/model/brand noun ONLY without conversational filler, store filters, or Tehran locations",
  "catalog_search_terms": ["0 to 6 concrete Persian/English catalog, spec, or offer-condition search terms"],
  "category_keywords": ["1 to 3 canonical Persian e-commerce catalog category names"],
  "is_accessory_request": false,
  "custom_offer_criterion": "",
  "min_price_toman": null,
  "max_price_toman": null,
  "max_distance_km": null,
  "extracted_traits": [
    {
      "aspect": "Neutral Persian attribute axis name ONLY without polarity",
      "preference": "Specific Persian directional preference on that axis",
      "is_durable": true
    }
  ],
  "clarification_questions": [
    {
      "id": "spec_focus",
      "title": "Short Persian topic title tailored to this item",
      "question": "Concise Persian question helping narrow down this specific item",
      "options": ["Option 1", "Option 2", "Option 3"]
    }
  ]
}
"""


def _build_session_state_snapshot(session_context: dict[str, Any] | None) -> dict[str, Any]:
    """Build a structured snapshot of the active multi-turn shopping session context."""
    ctx = session_context or {}
    raw_cat = str(ctx.get("active_category_name") or "").strip()
    if "حذف" in raw_cat:
        raw_cat = ""
    return {
        "active_category_name": raw_cat,
        "product_search_query": str(ctx.get("product_search_query") or "").strip(),
        "last_query": str(ctx.get("last_query") or "").strip(),
        "catalog_search_terms": [str(t).strip() for t in (ctx.get("catalog_search_terms") or []) if str(t).strip()],
        "category_keywords": [str(k).strip() for k in (ctx.get("category_keywords") or []) if str(k).strip()],
        "is_accessory_request": bool(ctx.get("is_accessory_request") or False),
        "wants_used_or_stock": bool(ctx.get("wants_used_or_stock") or False),
        "active_session_traits": [
            {
                "aspect": str(t.get("aspect") or "").strip(),
                "preference": str(t.get("preference") or "").strip(),
                "is_durable": bool(t.get("is_durable", True)),
            }
            for t in (ctx.get("active_session_traits") or [])
            if isinstance(t, dict) and str(t.get("aspect") or "").strip() and str(t.get("preference") or "").strip()
        ],
        "custom_offer_criterion": str(ctx.get("custom_offer_criterion") or "").strip(),
        "price_tier": str(ctx.get("price_tier") or "mid"),
        "min_price_toman": ctx.get("min_price_toman"),
        "max_price_toman": ctx.get("max_price_toman"),
        "max_distance_km": ctx.get("max_distance_km"),
        "require_torob_pay": bool(ctx.get("require_torob_pay") or False),
        "hard_constraints": dict(ctx.get("hard_constraints") or {}),
        "recent_messages": list(ctx.get("messages") or [])[-8:],
    }


def _merge_session_traits_ordered(
    prior_traits: list[dict[str, Any]],
    new_traits: list[ExtractedTrait],
) -> list[ExtractedTrait]:
    """Merge multi-turn traits by `aspect` so newer user answers update or extend earlier session traits."""
    by_aspect: dict[str, ExtractedTrait] = {}
    for pt in prior_traits:
        asp = str(pt.get("aspect") or "").strip()
        pref = str(pt.get("preference") or "").strip()
        if asp and pref:
            by_aspect[asp] = ExtractedTrait(
                aspect=asp,
                preference=pref,
                is_durable=bool(pt.get("is_durable", True)),
            )
    for nt in new_traits:
        asp = nt.aspect.strip()
        pref = nt.preference.strip()
        if asp and pref:
            by_aspect[asp] = ExtractedTrait(aspect=asp, preference=pref, is_durable=nt.is_durable)
    return list(by_aspect.values())[:6]


async def _extract_entities_with_llm(
    message: str,
    session_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the Language Model (LLM) for stateful multi-turn open-vocabulary text entity extraction."""
    api_key = settings.llm_api_key.strip()
    base_url = settings.llm_base_url.strip()
    if not _has_valid_api_key(api_key) or not base_url:
        raise RuntimeError(
            "کلید API مدل زبانی (LLM_API_KEY) در فایل .env تنظیم نشده است یا معتبر نیست."
        )

    snap = _build_session_state_snapshot(session_context)
    user_content = json.dumps(
        {
            "user_message": message,
            "current_session_state": snap,
        },
        ensure_ascii=False,
    )

    resp: httpx.Response | None = None
    client = _get_shared_http_client()
    for attempt in range(4):
        try:
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
                timeout=settings.llm_timeout_seconds,
            )
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                break
        except httpx.HTTPError as exc:
            if attempt == 3:
                raise RuntimeError(
                    f"خطای شبکه/تایم‌اوت در اتصال به مدل زبانی ({settings.llm_model}) در {base_url}: {type(exc).__name__} ({exc})"
                ) from exc
        await asyncio.sleep(1.5 * (2**attempt))
    assert resp is not None

    if resp.status_code != 200:
        raise RuntimeError(
            f"خطا در فراخوانی مدل زبانی ({settings.llm_model}) از {base_url} (کد {resp.status_code}): {resp.text[:300]}"
        )
    body = resp.json()
    raw_content = body["choices"][0]["message"]["content"]
    parsed = _extract_json_object(raw_content)

    is_continuation = bool(parsed.get("is_continuation", False))
    product_search_query = str(parsed.get("product_search_query") or "").strip() or message
    raw_terms = parsed.get("catalog_search_terms") or []
    catalog_search_terms = (
        [str(t).strip() for t in raw_terms if str(t).strip()][:6] if isinstance(raw_terms, list) else []
    )
    raw_cat_kws = parsed.get("category_keywords") or []
    category_keywords = (
        [str(k).strip() for k in raw_cat_kws if str(k).strip()][:3] if isinstance(raw_cat_kws, list) else []
    )
    is_accessory_request = bool(parsed.get("is_accessory_request", False))
    custom_offer_criterion = str(parsed.get("custom_offer_criterion") or "").strip()

    traits: list[ExtractedTrait] = []
    for t in parsed.get("extracted_traits") or []:
        if not isinstance(t, dict):
            continue
        aspect = str(t.get("aspect") or "").strip()
        pref = str(t.get("preference") or "").strip()
        is_dur = bool(t.get("is_durable", True))
        if aspect and pref:
            traits.append(ExtractedTrait(aspect=aspect, preference=pref, is_durable=is_dur))

    clarify_qs: list[dict[str, Any]] = []
    for q in parsed.get("clarification_questions") or []:
        if isinstance(q, dict) and q.get("question") and isinstance(q.get("options"), list) and len(q["options"]) >= 2:
            clarify_qs.append(
                {
                    "id": str(q.get("id") or f"dyn_q_{len(clarify_qs) + 1}"),
                    "title": str(q.get("title") or "ترجیح تخصصی شما"),
                    "question": str(q["question"]),
                    "options": [str(o) for o in q["options"][:4] if str(o).strip()],
                }
            )

    min_p_raw = parsed.get("min_price_toman")
    min_price_toman = int(min_p_raw) if isinstance(min_p_raw, (int, float)) and min_p_raw > 0 else None
    max_p_raw = parsed.get("max_price_toman")
    max_price_toman = int(max_p_raw) if isinstance(max_p_raw, (int, float)) and max_p_raw > 0 else None
    max_d_raw = parsed.get("max_distance_km")
    max_distance_km = float(max_d_raw) if isinstance(max_d_raw, (int, float)) and float(max_d_raw) > 0 else None

    return {
        "is_continuation": is_continuation,
        "product_search_query": product_search_query,
        "catalog_search_terms": catalog_search_terms,
        "category_keywords": category_keywords,
        "is_accessory_request": is_accessory_request,
        "custom_offer_criterion": custom_offer_criterion,
        "extracted_traits": traits,
        "clarification_questions": clarify_qs[:2],
        "min_price_toman": min_price_toman,
        "max_price_toman": max_price_toman,
        "max_distance_km": max_distance_km,
    }


async def evaluate_turn_with_jev(
    message: str,
    session_context: dict[str, Any] | None = None,
    skip_llm_extraction: bool = False,
    candidate_categories: list[str] | None = None,
    stored_user_traits: list[dict[str, Any]] | None = None,
    stored_price_priors: dict[str, dict[str, Any]] | None = None,
) -> SystemOneTurnEvaluation:
    """Evaluate a shopping turn in parallel with full multi-turn context preservation:
    1. Decision Model (`gemini-decision-1` / `Jev`): computes ALL `choice`, `score`, and `noul` judgments,
       including mission-continuity detection and selective cross-category trait & price-prior transfer (`0` extra RTT).
    2. Language Model (`LLM`): runs concurrently via `asyncio.gather` for cumulative open-vocabulary entity extraction.
    """
    snap = _build_session_state_snapshot(session_context)
    has_existing_mission = bool(snap["active_category_name"] or snap["product_search_query"])

    traits_pool = list(stored_user_traits or [])[: settings.recsys_max_stored_traits_per_user]
    price_prior_items = [
        (cat, info)
        for cat, info in list((stored_price_priors or {}).items())[:8]
        if cat and isinstance(info, dict) and "pct" in info
    ]

    state_payload: dict[str, Any] = {
        "user_message": message,
        "current_session_state": snap,
    }
    if traits_pool:
        state_payload["stored_user_traits"] = [
            {
                "idx": idx,
                "source_category": t.get("source_category") or "",
                "aspect": t.get("aspect") or "",
                "preference": t.get("preference") or "",
            }
            for idx, t in enumerate(traits_pool)
        ]

    questions: dict[str, Any] = {
        "intent_choice": {
            "type": "choice",
            "instructions": "What is the primary shopping action requested in `user_message`?",
            "criteria": {
                "store_ranking": "Finding, filtering, ranking, or visiting physical stores to buy a specific or sufficiently clear product",
                "comparison": "Comparing two or more product models side by side",
                "clarification": "Broad, open-ended product discovery request without a specific model (e.g. 'what good laptop do you recommend?') that genuinely needs 1 narrowing question before ranking stores",
            },
        },
        "price_tier": {
            "type": "choice",
            "instructions": (
                "What product class tier matches the PRODUCT MODEL itself that the shopper wants to buy? "
                "Important: asking for the 'cheapest store' or 'good store price' for a specific mid/flagship product (e.g. PS5 Slim, AirPods Pro 2, DeLonghi Espresso) "
                "does NOT make the product tier 'budget'; select 'budget' ONLY when the shopper asks for an entry-level, basic, or low-end product model."
            ),
            "criteria": {
                "budget": "Shopper asks for an entry-level, basic, student, or low-end product model.",
                "mid": "Shopper wants a standard, mainstream, or midrange product model (even if asking for the cheapest store selling it).",
                "flagship": "Shopper asks for a pro, ultra, flagship, luxury, or high-end product model.",
            },
        },
        "needs_clarification": {
            "type": "noul",
            "instructions": (
                "Is `user_message` genuinely vague or broad about WHICH product model to buy (e.g. 'یه لپتاپ خوب چی پیشنهاد میدی؟' with no brand/model/spec), "
                "such that asking 1 quick narrowing question is necessary before showing stores? "
                "Answer false when the shopper already named a specific product/model (e.g. S24 Ultra, iPhone 16, Redmi Note 13 Pro, PS5 Slim, AirPods Pro 2) or clear technical specs."
            ),
        },
        "user_dissatisfied": {
            "type": "noul",
            "instructions": "Is the shopper expressing dissatisfaction or rejection toward previous recommendations?",
        },
        "is_ephemeral_or_gift": {
            "type": "noul",
            "instructions": (
                "Is the shopper buying a gift for someone else, shopping on behalf of another person, "
                "or explicitly describing a one-off temporary need that does NOT reflect their own durable personal taste?"
            ),
        },
        "wants_used_or_stock": {
            "type": "noul",
            "instructions": (
                "Does the shopper explicitly ask for or welcome second-hand, used, refurbished, open-box, or stock items "
                "(استوک / دست دوم / کارکرده / ویترینی)?"
            ),
        },
        "is_accessory_or_spare_part": {
            "type": "noul",
            "instructions": (
                "Is the shopper explicitly asking to buy an accessory, cover, cable, game disc, or single replacement spare part "
                "(e.g. left/right earbud only, charging case only, water pump) rather than the complete standalone main product?"
            ),
        },
        "has_genuine_custom_offer_criterion": {
            "type": "noul",
            "instructions": (
                "Does the shopper explicitly demand a specific destination mall/street (NOT merely stating where they currently are, such as 'I am near Tajrish') "
                "or a specific seller-offer attribute (such as part-number ZAA, registered status, or specific color in stock) "
                "that goes beyond standard store price, distance radius, currently-open status, corporate warranty, or installment/TorobPay?"
            ),
        },
        "require_open_now": {
            "type": "noul",
            "instructions": "Does the shopper explicitly demand a store that is open right now for immediate pickup?",
        },
        "require_installment": {
            "type": "noul",
            "instructions": "Does the shopper explicitly require installment or credit payment (قسطی, TorobPay / ترب‌پی, SnappPay, etc.)?",
        },
        "require_torob_pay": {
            "type": "noul",
            "instructions": "Does the shopper specifically require TorobPay (ترب‌پی / ترب پی) payment?",
        },
        "require_warranty": {
            "type": "noul",
            "instructions": "Does the shopper explicitly require an official or corporate warranty (گارانتی شرکتی / رسمی)?",
        },
        "w_price": {
            "type": "score",
            "instructions": "How much does the shopper prioritize low, economical, or competitive store price in this message?",
            "criteria": [
                "The shopper did not mention store price, affordability, or budget priority.",
                "The shopper mentioned a budget or wants a fair/reasonable price.",
                "The shopper strongly emphasizes getting the cheapest, lowest possible store price.",
            ],
        },
        "w_distance": {
            "type": "score",
            "instructions": "Does the shopper prioritize close physical proximity or fast access in their message?",
            "criteria": [
                "The shopper did not mention distance or urgency of access.",
                "The shopper prefers a nearby store.",
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
            "instructions": "Does the shopper prioritize installment or credit payment options (such as TorobPay / ترب‌پی or SnappPay)?",
            "criteria": [
                "The shopper did not mention installment, TorobPay, or credit payment.",
                "The shopper asks if installment or TorobPay payment is available.",
                "The shopper strongly emphasizes or filters for stores supporting installment or TorobPay (ترب‌پی).",
            ],
        },
        "w_offer_custom": {
            "type": "score",
            "instructions": (
                "Does the shopper specify an unstructured destination mall/street or seller-offer detail beyond standard price, distance radius, open hours, warranty, or installment "
                "(for example: Pasaj Charsou, Alaeddin, ZAA part-number, specific color in stock)?"
            ),
            "criteria": [
                "No special destination mall, seller condition, color, or part-number requirement was mentioned.",
                "The shopper expressed a mild preference for a specific destination mall or offer detail.",
                "The shopper explicitly requires a specific destination mall/street, color, or part-number.",
            ],
        },
    }

    if has_existing_mission:
        questions["is_same_shopping_mission"] = {
            "type": "noul",
            "instructions": (
                f"The shopper's active session is currently searching for '{snap['product_search_query']}' "
                f"in category '{snap['active_category_name']}'. Is `user_message` continuing, refining, filtering "
                "(e.g. TorobPay/installment, open hours, distance, price, brand/specs, map view, or comparing models), or answering questions "
                "about this same shopping mission rather than switching to buy a completely unrelated new product?"
            ),
        }
        questions["is_refining_product_or_brand"] = {
            "type": "noul",
            "instructions": (
                "Does `user_message` specify or refine a product brand, model, or technical specification "
                "(e.g. 'ASUS laptop with Core i7', '256GB', 'Pro model'), as opposed to ONLY filtering stores, payment, open status, distance, or map view "
                "(e.g. 'only stores with TorobPay', 'open right now', 'show on map')?"
            ),
        }

    raw_cand_cats = [c for c in (candidate_categories or []) if c and "حذف" not in c]
    if snap["active_category_name"] and "حذف" not in snap["active_category_name"]:
        raw_cand_cats = [
            snap["active_category_name"],
            *[c for c in raw_cand_cats if c != snap["active_category_name"]],
        ]
    valid_cand_cats = raw_cand_cats[:10]
    cat_id_map = {f"cat_{idx}": cat for idx, cat in enumerate(valid_cand_cats)}
    if len(valid_cand_cats) >= 2:
        questions["target_category"] = {
            "type": "choice",
            "instructions": (
                "Which database product category best matches the core item the shopper wants to buy "
                "(choose the standalone main product category rather than spare parts, cables, or accessories unless explicitly requested)?"
            ),
            "criteria": {cid: f"Products in catalog category '{cat}'" for cid, cat in cat_id_map.items()},
        }

    for idx, t in enumerate(traits_pool):
        questions[f"trait_transfer_{idx}"] = {
            "type": "noul",
            "instructions": (
                f"Past user trait #{idx}: aspect='{t.get('aspect')}', preference='{t.get('preference')}' "
                f"(learned in category '{t.get('source_category') or 'previous'}'). "
                "Is this preference physically meaningful, scale-compatible, and genuinely applicable to the product being shopped for?"
            ),
        }

    for idx, (cat_name, _) in enumerate(price_prior_items):
        questions[f"price_prior_transfer_{idx}"] = {
            "type": "noul",
            "instructions": (
                f"Does historical shopping category '{cat_name}' belong to a compatible spending domain with the product being shopped for "
                "so the shopper's historical price-tier percentile in '{cat_name}' is a valid prior?"
            ),
        }

    if skip_llm_extraction:
        data = await _call_decision_model(state_payload, questions)
        llm_res = {
            "is_continuation": True if has_existing_mission else False,
            "product_search_query": snap["product_search_query"] or message,
            "catalog_search_terms": list(snap["catalog_search_terms"]),
            "category_keywords": list(snap["category_keywords"]),
            "is_accessory_request": bool(snap["is_accessory_request"]),
            "custom_offer_criterion": snap["custom_offer_criterion"],
            "extracted_traits": [],
            "clarification_questions": list((session_context or {}).get("clarification_questions") or []),
            "min_price_toman": snap["min_price_toman"],
            "max_price_toman": snap["max_price_toman"],
            "max_distance_km": snap["max_distance_km"],
        }
    else:
        data, llm_res = await asyncio.gather(
            _call_decision_model(state_payload, questions),
            _extract_entities_with_llm(message, session_context=session_context),
        )

    def _read_noul(q_key: str, default_val: float) -> NoulJudgment:
        item = data.get(q_key) if isinstance(data.get(q_key), dict) else {}
        return NoulJudgment(
            noul=max(0.0, min(1.0, float(item.get("noul", default_val)))),
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.90)))),
        )

    same_mission_j = _read_noul("is_same_shopping_mission", 0.90) if has_existing_mission else NoulJudgment(noul=0.0)
    refining_prod_j = _read_noul("is_refining_product_or_brand", 0.0) if has_existing_mission else NoulJudgment(noul=1.0)
    is_continuation = bool(
        has_existing_mission
        and (same_mission_j.noul >= 0.45 or bool(llm_res.get("is_continuation", False)))
    )
    is_product_refinement = refining_prod_j.noul >= 0.50

    jev_chosen_cat: str | None = None
    if len(valid_cand_cats) == 1:
        jev_chosen_cat = valid_cand_cats[0]
    elif isinstance(data.get("target_category"), dict):
        cand_cat = str(data["target_category"].get("choice") or "").strip()
        if cand_cat in cat_id_map:
            jev_chosen_cat = cat_id_map[cand_cat]
        elif cand_cat in valid_cand_cats:
            jev_chosen_cat = cand_cat

    chosen_db_category: str | None = None
    if is_continuation and snap["active_category_name"] and not is_product_refinement:
        chosen_db_category = snap["active_category_name"]
    elif jev_chosen_cat:
        chosen_db_category = jev_chosen_cat
    elif is_continuation and snap["active_category_name"]:
        chosen_db_category = snap["active_category_name"]

    intent_raw = "store_ranking"
    intent_conf = 0.88
    intent_probs: dict[str, float] = {}
    if isinstance(data.get("intent_choice"), dict):
        cand_intent = str(data["intent_choice"].get("choice") or "store_ranking")
        if cand_intent in ("store_ranking", "clarification", "comparison", "product_discovery"):
            intent_raw = cand_intent
        intent_conf = max(0.0, min(1.0, float(data["intent_choice"].get("confidence", 0.88))))
        raw_probs = data["intent_choice"].get("probabilities") or {}
        if isinstance(raw_probs, dict):
            intent_probs = {str(k): float(v) for k, v in raw_probs.items()}

    session_weights: dict[str, ScoreJudgment] = {}
    for key in (*STORE_CRITERIA_CATALOG.keys(), "w_offer_custom"):
        entry = data.get(key) if isinstance(data.get(key), dict) else {}
        raw_score = float(entry.get("score", 0.0))
        norm_score = max(0.0, min(1.0, raw_score / 2.0))
        conf = max(0.0, min(1.0, float(entry.get("confidence", 0.85))))
        session_weights[key] = ScoreJudgment(score=norm_score, confidence=conf)

    torob_pay_j = _read_noul("require_torob_pay", 0.05)
    inst_j = _read_noul("require_installment", 0.05)
    if torob_pay_j.noul >= 0.65 and inst_j.noul < torob_pay_j.noul:
        inst_j = torob_pay_j

    dealbreakers = {
        "require_open_now": _read_noul("require_open_now", 0.05),
        "require_installment": inst_j,
        "require_warranty": _read_noul("require_warranty", 0.05),
    }
    needs_clarify = _read_noul("needs_clarification", 0.15)
    if is_continuation:
        needs_clarify = NoulJudgment(noul=min(needs_clarify.noul, 0.20), confidence=needs_clarify.confidence)
    user_dissat = _read_noul("user_dissatisfied", 0.05)
    if is_product_refinement:
        user_dissat = NoulJudgment(noul=min(user_dissat.noul, 0.25), confidence=user_dissat.confidence)
    ephemeral_gift = _read_noul("is_ephemeral_or_gift", 0.05)
    wants_used_j = _read_noul("wants_used_or_stock", 0.05)
    is_acc_j = _read_noul("is_accessory_or_spare_part", 0.05)
    has_genuine_custom_j = _read_noul("has_genuine_custom_offer_criterion", 0.05)
    is_gift_turn = ephemeral_gift.noul >= settings.recsys_ephemeral_gift_noul_threshold

    transfer_thresh = settings.recsys_trait_transfer_noul_threshold
    transferred_traits: list[dict[str, Any]] = []
    if not is_gift_turn:
        for idx, t in enumerate(traits_pool):
            j_trans = _read_noul(f"trait_transfer_{idx}", 0.0)
            if j_trans.noul >= transfer_thresh:
                transferred_traits.append({**t, "transfer_noul": round(j_trans.noul, 4)})
        transferred_traits.sort(
            key=lambda it: float(it.get("transfer_noul", 0.0)) * float(it.get("strength", 0.5)),
            reverse=True,
        )
        transferred_traits = transferred_traits[: settings.recsys_max_traits_per_query]

    inferred_price_pct: float | None = None
    if not is_gift_turn and price_prior_items:
        best_noul = 0.0
        for idx, (_, info) in enumerate(price_prior_items):
            j_pp = _read_noul(f"price_prior_transfer_{idx}", 0.0)
            if j_pp.noul >= transfer_thresh and j_pp.noul > best_noul:
                best_noul = j_pp.noul
                inferred_price_pct = max(0.0, min(1.0, float(info.get("pct", 0.5))))

    # Strictly separate Layer-1 product tier from Layer-2 store `w_price` priority!
    price_tier: Literal["budget", "mid", "flagship"] = "mid"
    if is_continuation and snap["price_tier"] in ("budget", "mid", "flagship"):
        price_tier = snap["price_tier"]  # type: ignore[assignment]
    if isinstance(data.get("price_tier"), dict):
        cand_tier = str(data["price_tier"].get("choice") or "mid")
        if cand_tier in ("budget", "flagship") or not is_continuation:
            if cand_tier in ("budget", "mid", "flagship"):
                price_tier = cand_tier  # type: ignore[assignment]

    # Merge product query, catalog search terms, traits, and category keywords across multi-turn continuations
    final_search_query = str(llm_res["product_search_query"] or "").strip()
    if is_continuation and snap["product_search_query"]:
        prev_q_ns = normalize_persian_text(snap["product_search_query"]).replace(" ", "")
        new_q_ns = normalize_persian_text(final_search_query).replace(" ", "")
        msg_ns = normalize_persian_text(message).replace(" ", "")
        if not is_product_refinement or not new_q_ns or (new_q_ns == msg_ns and prev_q_ns not in new_q_ns):
            final_search_query = snap["product_search_query"]
        elif prev_q_ns not in new_q_ns:
            final_search_query = f"{snap['product_search_query']} {final_search_query}".strip()

    if is_continuation:
        merged_terms = list(
            dict.fromkeys([*llm_res["catalog_search_terms"], *snap["catalog_search_terms"]])
        )[:8]
        merged_traits = _merge_session_traits_ordered(
            snap["active_session_traits"],
            list(llm_res["extracted_traits"]),
        )
        category_keywords = list(
            dict.fromkeys([*( [chosen_db_category] if chosen_db_category else [] ), *llm_res["category_keywords"], *snap["category_keywords"]])
        )[:4]
        min_price_final = llm_res.get("min_price_toman") if llm_res.get("min_price_toman") is not None else snap["min_price_toman"]
        max_price_final = llm_res.get("max_price_toman") if llm_res.get("max_price_toman") is not None else snap["max_price_toman"]
        max_dist_final = llm_res.get("max_distance_km") if llm_res.get("max_distance_km") is not None else snap["max_distance_km"]
        raw_new_custom = str(llm_res.get("custom_offer_criterion") or "").strip()
        custom_criterion = (
            raw_new_custom
            if (raw_new_custom and has_genuine_custom_j.noul >= 0.55)
            else snap["custom_offer_criterion"]
        )
        is_acc_final = bool(snap["is_accessory_request"] or (is_acc_j.noul >= 0.55 and bool(llm_res.get("is_accessory_request"))))
        wants_used_final = bool(snap["wants_used_or_stock"] or wants_used_j.noul >= 0.55)
        req_torob_pay = bool(snap["require_torob_pay"] or torob_pay_j.noul >= 0.65)
    else:
        merged_terms = list(llm_res.get("catalog_search_terms") or [])
        merged_traits = list(llm_res.get("extracted_traits") or [])
        category_keywords = list(llm_res.get("category_keywords") or [])
        if chosen_db_category:
            category_keywords = [chosen_db_category, *[k for k in category_keywords if k != chosen_db_category]]
        min_price_final = llm_res.get("min_price_toman")
        max_price_final = llm_res.get("max_price_toman")
        max_dist_final = llm_res.get("max_distance_km")
        raw_new_custom = str(llm_res.get("custom_offer_criterion") or "").strip()
        custom_criterion = raw_new_custom if has_genuine_custom_j.noul >= 0.55 else ""
        is_acc_final = bool(is_acc_j.noul >= 0.55 and (bool(llm_res.get("is_accessory_request")) or is_acc_j.noul >= 0.70))
        wants_used_final = bool(wants_used_j.noul >= 0.55)
        req_torob_pay = bool(torob_pay_j.noul >= 0.65)

    if not custom_criterion:
        session_weights["w_offer_custom"] = ScoreJudgment(score=0.0, confidence=0.92)
    elif session_weights["w_offer_custom"].score < settings.recsys_mention_score_threshold:
        session_weights["w_offer_custom"] = ScoreJudgment(
            score=max(0.65, session_weights["w_offer_custom"].score),
            confidence=0.88,
        )

    return SystemOneTurnEvaluation(
        intent_choice=ChoiceJudgment(
            choice=intent_raw,  # type: ignore[arg-type]
            confidence=intent_conf,
            probabilities=intent_probs or {intent_raw: intent_conf},
        ),
        session_weights=session_weights,
        dealbreakers=dealbreakers,
        user_dissatisfied=user_dissat,
        needs_clarification=needs_clarify,
        is_ephemeral_or_gift=ephemeral_gift,
        extracted_traits=merged_traits,
        transferred_traits=transferred_traits,
        inferred_price_percentile=inferred_price_pct,
        min_price_toman=min_price_final,
        max_price_toman=max_price_final,
        product_search_query=final_search_query,
        catalog_search_terms=merged_terms,
        category_keywords=category_keywords,
        is_accessory_request=is_acc_final,
        wants_used_or_stock=wants_used_final,
        max_distance_km=max_dist_final,
        require_torob_pay=req_torob_pay,
        custom_offer_criterion=custom_criterion,
        clarification_questions=list(llm_res["clarification_questions"]),
        price_tier=price_tier,
        is_continuation=is_continuation,
        engine_mode_used=settings.jev_engine_mode,
    )


async def score_candidate_products_with_decision_model(
    user_message: str,
    candidates: list[dict[str, Any]],
    active_traits: list[dict[str, Any]] | None = None,
    max_price_toman: int | None = None,
    min_price_toman: int | None = None,
    price_tier: str = "mid",
    inferred_price_percentile: float | None = None,
    limit: int = 4,
    is_accessory_request: bool = False,
    wants_used_or_stock: bool = False,
) -> list[dict[str, Any]]:
    """Layer-1 Product Ranking & Semantic Trait Attribution powered strictly by the Decision Model (`0` false badges)."""
    if not candidates:
        return []

    traits = [
        {"aspect": str(t.get("aspect") or ""), "preference": str(t.get("preference") or "")}
        for t in (active_traits or [])
        if t.get("preference")
    ][:4]

    compact_candidates = [
        {
            "idx": i,
            "title": str(c.get("title") or ""),
            "category": str(c.get("category_name") or ""),
            "min_price_toman": int(c.get("min_price_toman") or 0),
            "store_count": int(c.get("store_count") or 1),
            "specs": dict(list((c.get("specs") or {}).items())[:6]),
            "offer_samples": str(c.get("offer_titles_sample") or "")[:180],
        }
        for i, c in enumerate(candidates[:10])
    ]

    min_pool_price = min((c["min_price_toman"] for c in compact_candidates if c["min_price_toman"] > 0), default=0)
    max_pool_price = max((c["min_price_toman"] for c in compact_candidates if c["min_price_toman"] > 0), default=0)
    state_payload = {
        "shopper_request": user_message,
        "target_price_tier": price_tier,
        "is_accessory_request": is_accessory_request,
        "wants_used_or_stock": wants_used_or_stock,
        "category_minimum_price_toman": min_pool_price,
        "active_shopper_traits": traits,
        "max_budget_toman": max_price_toman,
        "candidate_products": compact_candidates,
    }
    questions: dict[str, Any] = {}
    tier_guidance = (
        "The shopper wants an entry-level / economical product model (target_price_tier='budget'): reward affordable genuine models and avoid overpriced luxury variants."
        if price_tier == "budget"
        else "Evaluate exact model/spec match, product authenticity, and suitability for the shopper's request."
    )
    for c in compact_candidates:
        idx = c["idx"]
        questions[f"prod_{idx}"] = {
            "type": "score",
            "instructions": (
                f"How well does candidate product #{idx} ({c['title']} in category '{c['category']}', "
                f"price {c['min_price_toman']:,} Toman, specs: {json.dumps(c['specs'], ensure_ascii=False)}, "
                f"seller offers: '{c['offer_samples']}') match the shopper's requested product/model, active traits, and price tier? {tier_guidance}"
            ),
            "criteria": [
                "Irrelevant product, spare part/game disc when main device was requested, counterfeit clone, or wrong model.",
                "Weak or partial match (e.g. different model/generation or suboptimal specs).",
                "Good product match that satisfies the shopper's category, brand, and use-case.",
                "Exact or ideal product match with the requested model, specs, and condition.",
            ],
        }
        questions[f"prod_{idx}_is_core_device"] = {
            "type": "noul",
            "instructions": (
                f"For shopper request '{user_message}', is candidate #{idx} ('{c['title']}' in category '{c['category']}', "
                f"price {c['min_price_toman']:,} Toman) the complete standalone main product requested, "
                "rather than an accessory, cover, cable, game disc/software, water pump, or single replacement spare part? "
                "NOTE: In Persian titles, 'گوش چپ', 'گوش راست', 'گوش سمت راست', 'گوش سمت چپ', 'تک گوش', or 'کیس شارژ' mean a SINGLE replacement earbud/case spare part (NOT a full headphone pair), and 'پمپ اسپرسوساز' means a spare pump (NOT an espresso machine) — answer false for all such spare parts."
            ),
        }
        questions[f"prod_{idx}_is_new_authentic"] = {
            "type": "noul",
            "instructions": (
                f"Based on title '{c['title']}', price {c['min_price_toman']:,} Toman (pool range: {min_pool_price:,}..{max_pool_price:,} Toman), "
                f"and seller offers '{c['offer_samples']}', is candidate #{idx} a brand-new authentic/original product "
                "rather than second-hand/used/stock/open-box (استوک / دست دوم / کارکرده / ویترینی) or a counterfeit/high-copy clone (طرح اصلی / های کپی / مشابه اصل)?"
            ),
        }
        for t_idx, tr in enumerate(traits):
            questions[f"prod_{idx}_trait_{t_idx}"] = {
                "type": "noul",
                "instructions": (
                    f"Does candidate product #{idx} ({c['title']}, specs: {json.dumps(c['specs'], ensure_ascii=False)}, "
                    f"offers: '{c['offer_samples']}') genuinely satisfy the preference '{tr['preference']}' on aspect '{tr['aspect']}'?"
                ),
            }

    answers = await _call_decision_model(state_payload, questions)

    apply_price_prior = (
        inferred_price_percentile is not None
        and min_price_toman is None
        and max_price_toman is None
        and price_tier == "mid"
    )
    prior_lambda = float(settings.recsys_price_prior_boost_weight)

    scored_list: list[dict[str, Any]] = []
    for i, orig in enumerate(candidates[:10]):
        item = dict(orig)
        ans = answers.get(f"prod_{i}") if isinstance(answers.get(f"prod_{i}"), dict) else {}
        raw_score = float(ans.get("score", 1.5))
        norm_score = max(0.0, min(1.0, raw_score / 3.0))
        conf = max(0.0, min(1.0, float(ans.get("confidence", 0.85))))

        core_ans = answers.get(f"prod_{i}_is_core_device")
        core_noul = float(core_ans.get("noul", 0.85)) if isinstance(core_ans, dict) else 0.85
        auth_ans = answers.get(f"prod_{i}_is_new_authentic")
        auth_noul = float(auth_ans.get("noul", 0.85)) if isinstance(auth_ans, dict) else 0.85

        item["is_core_device"] = core_noul >= 0.50
        item["is_stock_or_copy"] = auth_noul < 0.50

        if apply_price_prior and inferred_price_percentile is not None:
            p10 = int(item.get("category_p10_price") or min_pool_price)
            p90 = int(item.get("category_p90_price") or max_pool_price)
            price_val = int(item.get("min_price_toman") or 0)
            if p90 > p10 and price_val > 0:
                prod_pct = max(0.0, min(1.0, float(price_val - p10) / float(p90 - p10)))
                price_fit = 1.0 - abs(prod_pct - float(inferred_price_percentile))
                norm_score = (1.0 - prior_lambda) * norm_score + prior_lambda * price_fit

        verified_traits: list[str] = []
        trait_nouls: list[float] = []
        for t_idx, tr in enumerate(traits):
            t_ans = answers.get(f"prod_{i}_trait_{t_idx}")
            t_noul = float(t_ans.get("noul", 0.0)) if isinstance(t_ans, dict) else 0.0
            trait_nouls.append(max(0.0, min(1.0, t_noul)))
            if t_noul >= 0.65:
                verified_traits.append(tr["preference"])

        if trait_nouls:
            mean_trait_noul = sum(trait_nouls) / float(len(trait_nouls))
            norm_score = max(0.0, min(1.0, 0.65 * norm_score + 0.35 * mean_trait_noul))

        if not is_accessory_request and not item["is_core_device"]:
            norm_score *= 0.15
        if not wants_used_or_stock and item["is_stock_or_copy"]:
            norm_score *= 0.35

        item["matched_traits"] = verified_traits[:2]
        item["trgm_sim"] = round(norm_score, 4)
        item["decision_score"] = round(norm_score, 4)
        item["decision_confidence"] = round(conf, 4)
        scored_list.append(item)

    # Filter out accessories/spare parts when main device candidates exist and shopper didn't ask for an accessory
    if not is_accessory_request:
        core_only = [p for p in scored_list if p.get("is_core_device", True)]
        if core_only:
            scored_list = core_only

    # Filter out stock/copy candidates when brand-new authentic matches exist and shopper didn't ask for stock/used
    if not wants_used_or_stock:
        new_auth_only = [
            p for p in scored_list
            if not p.get("is_stock_or_copy", False) and float(p.get("decision_score") or 0.0) >= 0.40
        ]
        if new_auth_only:
            scored_list = new_auth_only

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


async def score_custom_offer_criterion_with_decision_model(
    custom_criterion: str,
    offers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score up to `RECSYS_CUSTOM_OFFER_TOP_K` (`15`) candidate offers against an open-vocabulary store/offer criterion.

    Executes `0` calls when `custom_criterion` is empty, and `1` batched Decision Model pass when non-empty.
    """
    criterion = (custom_criterion or "").strip()
    if not criterion or not offers:
        return offers

    top_k = max(1, int(settings.recsys_custom_offer_top_k))
    head = offers[:top_k]
    compact_offers = [
        {
            "idx": idx,
            "shop_name": str(o.get("shop_name") or ""),
            "address": str(o.get("address") or ""),
            "mall_name": str((o.get("mall_micro_guide") or {}).get("mall_name") or ""),
            "distance_km": float(o.get("distance_km") or 0.0),
            "is_open_now": bool(o.get("is_open_now", False)),
            "today_hours_fa": str(o.get("today_hours_fa") or ""),
            "price_toman": int(o.get("price_toman") or 0),
            "has_in_person_installment": bool(o.get("has_in_person_installment", False)),
            "installment_providers": list(o.get("installment_providers") or []),
            "seller_title": str(o.get("seller_title") or "")[:120],
            "description": str(o.get("description") or "")[:140],
            "warranty": str(o.get("warranty_provider") or o.get("warranty_raw") or ""),
        }
        for idx, o in enumerate(head)
    ]

    questions: dict[str, Any] = {}
    for c in compact_offers:
        idx = c["idx"]
        questions[f"offer_{idx}"] = {
            "type": "score",
            "instructions": (
                f"How well does store offer #{idx} (shop='{c['shop_name']}', mall='{c['mall_name']}', "
                f"address='{c['address']}', distance_km={c['distance_km']}, is_open_now={c['is_open_now']}, "
                f"hours='{c['today_hours_fa']}', installment_providers={c['installment_providers']}, "
                f"seller_title='{c['seller_title']}', description='{c['description']}', "
                f"warranty='{c['warranty']}') satisfy the shopper's special condition: '{criterion}'?"
            ),
            "criteria": [
                "Does not match or contradicts the shopper's special store/offer condition.",
                "Unclear or weak partial overlap with the condition.",
                "Likely satisfies the shopper's special condition (e.g. nearby area or compatible offer text).",
                "Directly and explicitly satisfies the shopper's exact store/location/offer condition.",
            ],
        }

    answers = await _call_decision_model(
        state_payload={"custom_offer_criterion": criterion, "candidate_offers": compact_offers},
        questions=questions,
    )

    annotated: list[dict[str, Any]] = []
    for idx, orig in enumerate(offers):
        item = dict(orig)
        if idx < top_k:
            ans = answers.get(f"offer_{idx}") if isinstance(answers.get(f"offer_{idx}"), dict) else {}
            raw_score = float(ans.get("score", 0.5))
            item["f_offer_custom"] = round(max(0.0, min(1.0, raw_score / 3.0)), 4)
        else:
            item["f_offer_custom"] = 0.25
        item["custom_match_label_fa"] = f"منطبق با شرط شما ({criterion[:28]})"
        annotated.append(item)
    return annotated


async def check_trait_aspect_and_preference_noul(
    new_aspect: str,
    new_preference: str,
    existing_aspect: str,
    existing_preference: str,
) -> tuple[NoulJudgment, NoulJudgment]:
    """Evaluate in a single Decision Model call whether two traits share the same axis AND the same directional preference."""
    answers = await _call_decision_model(
        state_payload={
            "new_trait": {"aspect": new_aspect, "preference": new_preference},
            "existing_trait": {"aspect": existing_aspect, "preference": existing_preference},
        },
        questions={
            "same_aspect": {
                "type": "noul",
                "instructions": "Do `new_trait.aspect` and `existing_trait.aspect` refer to the exact same product attribute axis?",
            },
            "same_preference": {
                "type": "noul",
                "instructions": (
                    "Assuming both traits refer to the same attribute axis, do `new_trait.preference` and "
                    "`existing_trait.preference` express the same compatible directional preference (rather than competing or opposite choices)?"
                ),
            },
        },
    )
    ans_a = answers.get("same_aspect", {}) if isinstance(answers.get("same_aspect"), dict) else {}
    ans_p = answers.get("same_preference", {}) if isinstance(answers.get("same_preference"), dict) else {}
    return (
        NoulJudgment(
            noul=max(0.0, min(1.0, float(ans_a.get("noul", 0.0)))),
            confidence=max(0.0, min(1.0, float(ans_a.get("confidence", 0.90)))),
        ),
        NoulJudgment(
            noul=max(0.0, min(1.0, float(ans_p.get("noul", 0.0)))),
            confidence=max(0.0, min(1.0, float(ans_p.get("confidence", 0.90)))),
        ),
    )
