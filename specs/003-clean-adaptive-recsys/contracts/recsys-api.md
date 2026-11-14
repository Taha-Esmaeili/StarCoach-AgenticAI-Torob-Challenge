# Phase 1 Interface Contracts (`003-clean-adaptive-recsys`)

**Feature**: Clean Two-Layer Adaptive Recommender System  
**Scope**: System-One Decision Model (`gemini-decision-1` / `Jev`), LLM Concept Extractor, FastAPI REST API (`/api/v1/*`), and `UI_Template` TypeScript Client

---

## 1. Internal System-One Decision Model Contracts (`POST {TYPESAFE_BASE_URL}`)

### 1.1 Turn-1 Parallel Intent, Store Rubric, Outlier Shield & Selective Trait Transfer
Executed in a **single parallel Decision Model request** inside `evaluate_turn_with_jev`:

- **`state` payload**:
  ```json
  {
    "user_message": "یه گوشی خوش‌دست می‌خوام، عصر می‌خوام برم سمت پاساژ چارسو حضوری بخرم و پارت‌نامبر ZAA باشه",
    "conversation_history": [],
    "user_location": {"lat": 35.7575, "lng": 51.4100},
    "candidate_stored_traits": [
      {"idx": 0, "source_category": "لپ‌تاپ و نوت‌بوک", "aspect": "ابعاد صفحه", "preference": "15.6 اینچ"},
      {"idx": 1, "source_category": "لپ‌تاپ و نوت‌بوک", "aspect": "پنل نمایشگر", "preference": "OLED"},
      {"idx": 2, "source_category": "لپ‌تاپ و نوت‌بوک", "aspect": "شارژدهی باتری", "preference": "بالا"}
    ]
  }
  ```
- **`questions` map** (100% category-agnostic — zero hardcoded `VALID_DOMAINS` list):
  - `intent_mode`: `Choice` over `["specific_product", "broad_category", "comparison", "store_followup"]`
  - `needs_clarification`: `Noul` (whether the request is too underspecified to rank confidently without 1 concise clarification round)
  - `user_dissatisfied`: `Noul`
  - `is_ephemeral_or_gift`: `Noul` (buying for someone else, gift, or one-off emergency unrelated to personal taste)
  - `w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`: 3-level `Score` (`0.0`: unmentioned, `0.5`: mild, `1.0`: primary)
  - `w_offer_custom`: 3-level `Score` (`0.0`: no unstructured store/offer condition; `0.5`: mild preference; `1.0`: primary store/offer requirement such as target mall/neighborhood, part-number, color, test guarantee, or stock grade)
  - `require_open_now`, `require_installment`, `require_warranty`: `Noul` dealbreaker hurdles
  - `trait_transfer_{idx}` (for each `idx` in `candidate_stored_traits`): `Noul` — *"Is stored trait `(aspect: preference)` learned in `source_category` physically, numerically, and semantically valid as a soft preference for the user's current product request without scale mismatch or contradiction?"*
  - `price_prior_transfer_{c}` (for each stored category `c` in `user_profiles.price_percentiles_json`): `Noul` — *"Does the user's spending tier in `c` reasonably transfer as a soft prior to their current product request?"*

---

### 1.2 LLM Concept-to-Catalog & Open-Vocabulary Entity Extraction
Executed concurrently via `asyncio.gather` alongside §1.1 (zero sequential latency):

```json
{
  "product_search_query": "گوشی موبایل",
  "catalog_search_terms": ["OLED", "AMOLED", "فست شارژ"],
  "category_keywords": ["گوشی", "موبایل"],
  "is_accessory_request": false,
  "price_tier": "unspecified",
  "min_price_toman": null,
  "max_price_toman": null,
  "custom_offer_criterion": "واقع در محدوده پاساژ چارسو / جمهوری و دارای پارت‌نامبر ZAA",
  "extracted_traits": [
    {"aspect": "فرم‌فکتور و خوش‌دستی", "preference": "خوش‌دست و سبک"}
  ]
}
```

---

### 1.3 Layer 1 Semantic Product Candidate Scoring & Trait Attribution
Single batched Decision Model call across up to 12 candidate products:
- Input per product: `title`, `category_name`, `min_price_toman`, `specs_summary`, `offer_titles_sample` (from `offers.seller_title` / `offers.description`), plus `active_session_traits` and `transferred_traits`.
- Output per product `idx`:
  - `prod_fit_{idx}` (`Score` in `[0, 1]`): Holistic product fit.
  - `prod_{idx}_trait_{t}` (`Noul` in `[0, 1]` for up to top 4 active/transferred traits): Semantic satisfaction check (e.g., `6000mAh` satisfies `شارژدهی بالا`). Badge `"منطبق با سلیقه شما: ..."` is attached **iff** `noul >= 0.65`.

---

### 1.4 Layer 2 Conditional Open-Vocabulary Offer Scoring (`w_offer_custom`)
Executed **only when `custom_offer_criterion != ""`** across at most `RECSYS_CUSTOM_OFFER_TOP_K` (`15`) candidate offers:
- Input per offer `idx`: `shop_name`, `address`, `mall_name`, `seller_title`, `description`, `warranty_raw`, and `custom_offer_criterion`.
- Output per offer `idx`: `offer_custom_{idx}` (`Score` in `[0, 1]`), injected as $f_{o,\text{custom}}$ into `score_and_rank_offers`.

---

## 2. External FastAPI REST & Frontend Contracts (`/api/v1`)

All existing response shapes for `POST /api/v1/chat/turn`, `GET /api/v1/products/compare`, and `GET /api/v1/stores/{shop_id}/fallback` remain **100% backward-compatible** with `UI_Template/src/types.ts`.

### 2.1 Updated `POST /api/v1/feedback` Request Schema (Fixes Bug #1 `HTTP 500`)

Both `backend/models/schemas.py` (`FeedbackRequest`) and `UI_Template/src/api/client.ts` (`postFeedback`) add optional target identifiers so positive selections (`thumbs_up` / store contact / navigation click) carry exact offer/product attribution:

```json
{
  "session_id": "sess_abc123",
  "user_id": "usr_tehran_default",
  "feedback_type": "thumbs_up",
  "target_offer_id": "off_99812",
  "target_product_id": "prd_44120",
  "selected_option_id": null,
  "clarification_answers": {},
  "weight_overrides": {},
  "hard_constraints": null,
  "user_location": {"lat": 35.7219, "lng": 51.3347}
}
```

**Behavioral Contract by `feedback_type`**:
| `feedback_type` | Updates Session State? | Updates Long-Term `user_profiles` / `user_trait_memory`? |
| :--- | :--- | :--- |
| `clarification_choice` | **Yes** (refines session weights & traits, increments `clarification_count`) | **No** (session-only until confirmed selection) |
| `thumbs_down` | **Yes** (sets `dissatisfaction_triggered = true`, triggers Round-2 clarification if eligible) | **NEVER** (`0%` mutation on `store_weights_json` or `user_trait_memory`) |
| `thumbs_up` | **Yes** | **Yes** (if `not is_ephemeral_or_gift`: contrastive `store_weights_json` update using `target_offer_id` vs. `shown_store_features`, confirmed `alpha = 0.35` trait reinforcement, and domain price percentile update) |
| `weight_override` | **Yes** (re-normalizes active store weights & re-ranks stores) | **Yes** (persists explicit slider preferences to `store_weights_json`) |
| `price_discrepancy` | **Yes** (triggers 1-tap fallback recommendation) | **No** |

---

### 2.2 Active Weights Contract (`RecSysStatePayload.active_weights`)
- Contains the 5 orthogonal store slots (`slot 1..5`: `w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`) plus `slot 6` (`w_offer_custom`, `slot_group: "dynamic"`, `label_fa: "تطابق شرط خاص فروشگاهی"`) **only when `custom_offer_criterion` is active** in the current session.
- Sum of `weight` across returned `active_weights` is strictly `1.0` ($\pm 10^{-4}$).

### 2.3 Store Ranking Pareto Top-3 Contract (`ChatTurnResponse.stores`)
When $\ge 3$ qualifying distinct offers exist:
- `stores[0].pareto_role == "best_overall"` (`بهترین انتخاب کل`)
- `stores[1].pareto_role == "closest_open"` (`نزدیک‌ترین مغازه باز`, if an open distinct offer exists)
- `stores[2].pareto_role == "lowest_price"` (`ارزان‌ترین پیشنهاد`, if a distinct lower-price offer exists)
