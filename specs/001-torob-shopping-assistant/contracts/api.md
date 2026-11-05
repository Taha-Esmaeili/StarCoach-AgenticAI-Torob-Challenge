# API Contracts: Torob Smart In-Person Shopping Assistant (`001-torob-shopping-assistant`)

**Base URL**: `/api/v1` (proxied by Vite in dev, served by FastAPI in production container)  
**Locale / Encoding**: UTF-8 JSON; all user-facing labels formatted for Persian RTL (`dir="rtl"`).

---

## 1. `POST /api/v1/chat/turn` — Primary Conversational & Generative UI Endpoint

Processes a user's Persian natural-language message (plus optional GPS coordinates and active sidebar filter overrides), runs the **Jev System One (`jev-1.14.0` / fallback)** 15-parameter extraction & confidence-gated fusion, and returns structured generative UI widgets for [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template).

### Request Body
```json
{
  "session_id": "sess_98a7f1",
  "user_id": "usr_tehran_01",
  "message": "یه هندزفری بلوتوثی تا ۲ میلیون میخوام که همین الان سمت ولیعصر باز باشه و قسطی هم بده",
  "user_location": {
    "lat": 35.7219,
    "lng": 51.4043
  },
  "ui_overrides": {
    "require_open_now": true,
    "require_installment": true,
    "require_warranty": false,
    "max_distance_km": null,
    "max_price_toman": 2000000
  }
}
```

### Response Body (`200 OK`)
```json
{
  "session_id": "sess_98a7f1",
  "assistant_text": "۳ فروشگاه باز در محدوده ولیعصر و جمهوری که هندزفری بلوتوثی زیر ۲ میلیون با پرداخت قسطی حضوری دارند براتون پیدا کردم:",
  "widget_type": "store_ranking",
  "clarification_card": null,
  "recsys_state": {
    "effective_confidence": 0.84,
    "clarification_count": 0,
    "active_weights": [
      {"slot": 1, "key": "w_distance", "label_fa": "نزدیکی و مسافت", "weight": 0.24, "confidence": 0.88},
      {"slot": 2, "key": "w_price", "label_fa": "قیمت اقتصادی", "weight": 0.21, "confidence": 0.85},
      {"slot": 4, "key": "w_open_now", "label_fa": "باز بودن در این لحظه", "weight": 0.19, "confidence": 0.94},
      {"slot": 6, "key": "w_installment", "label_fa": "پرداخت اقساطی حضوری", "weight": 0.18, "confidence": 0.92},
      {"slot": 11, "key": "spec_anc_mic", "label_fa": "میکروفون و مکالمه", "weight": 0.08, "confidence": 0.72}
    ],
    "hard_constraints": {
      "require_open_now": true,
      "require_installment": true,
      "require_warranty": false
    }
  },
  "stores": [
    {
      "offer_id": 1049281,
      "product_id": 8419201,
      "product_name": "هندزفری بلوتوثی شیائومی مدل Redmi Buds 5",
      "shop_id": 2194,
      "shop_name": "فروشگاه دیجیتال پایتخت",
      "price_toman": 1680000,
      "utility_score": 94,
      "pareto_role": "best_overall",
      "pareto_badge_fa": "بهترین انتخاب کلی",
      "why_this_shop_fa": ["۹۰۰ متر فاصله (۴ دقیقه)", "پرداخت حضوری ترب‌پی و اسنپ‌پی", "بروزرسانی قیمت ۲ ساعت پیش"],
      "distance_km": 0.9,
      "driving_minutes": 4,
      "walking_minutes": 11,
      "latitude": 35.7152,
      "longitude": 51.4048,
      "address": "تهران، خیابان ولیعصر، تقاطع طالقانی، مجتمع تجاری نور تهران، طبقه همکف، واحد ۱۲",
      "mall_micro_guide": {
        "mall_name": "مجتمع تجاری نور تهران",
        "floor_label": "طبقه همکف",
        "unit_label": "واحد ۱۲"
      },
      "is_open_now": true,
      "today_hours_fa": "۱۰:۰۰ تا ۲۱:۳۰",
      "last_price_changed_at": "2026-10-13T11:20:00+00:00",
      "freshness_badge_fa": "بروزرسانی ۲ ساعت پیش",
      "shop_score": 4.7,
      "votes_count": 68,
      "has_official_warranty": true,
      "warranty_provider": "گارانتی ۱۸ ماهه شرکتی",
      "has_in_person_installment": true,
      "installment_providers": ["ترب‌پی", "اسنپ‌پی"],
      "primary_phone": "02188941234",
      "is_real_torob_shop": true,
      "instagram": "digital_paytakht",
      "website_url": "https://digitalpaytakht.ir",
      "is_category_fallback": false
    }
  ],
  "comparison_matrix": null
}
```

---

## 2. `FeatureClarificationCard` Payload (When $\text{mean}(\text{EffConf}_k) < 0.45$)

When the user prompt is underspecified on Turn 1 (`clarification_count == 0`) or after explicit dissatisfaction (`clarification_count == 1` and 👎 / `user_dissatisfied.noul >= 0.70`), `widget_type` includes `"clarification"` and `clarification_card` is populated alongside initial Pareto-diverse results:

```json
{
  "question_fa": "برای اینکه دقیق‌ترین مغازه و مدل رو بهتون پیشنهاد بدم، کدوم مورد براتون اولویت بیشتری داره؟",
  "clarification_round": 1,
  "max_rounds": 2,
  "options": [
    {
      "option_id": "opt_fastest",
      "label_fa": "نزدیک‌ترین مغازه باز (حداقل مسافت)",
      "weight_deltas": {"w_distance": 0.95, "w_open_now": 0.90}
    },
    {
      "option_id": "opt_cheapest",
      "label_fa": "کمترین قیمت ممکن در کل تهران",
      "weight_deltas": {"w_price": 0.95, "w_distance": 0.20}
    },
    {
      "option_id": "opt_installment_warranty",
      "label_fa": "خرید قسطی حضوری و گارانتی معتبر",
      "weight_deltas": {"w_installment": 0.95, "w_warranty": 0.90}
    }
  ]
}
```

---

## 3. `POST /api/v1/feedback` — Live Weight Adaptation & 1-Tap Clarifier Endpoint

Called when the user:
1. Taps a pill on `FeatureClarificationCard.tsx`
2. Clicks 👍 (`ThumbsUp`) or 👎 (`ThumbsDown`) under an assistant message
3. Adjusts a priority slider/toggle in `ProfilePrioritiesModal.tsx` or the right-hand filter sidebar

### Request Body
```json
{
  "session_id": "sess_98a7f1",
  "user_id": "usr_tehran_01",
  "feedback_type": "clarification_choice | thumbs_up | thumbs_down | weight_override",
  "selected_option_id": "opt_fastest",
  "weight_overrides": {
    "w_distance": 0.95,
    "w_price": 0.45
  }
}
```

### Response Body (`200 OK`)
Returns the updated `recsys_state`, re-ranked `stores` array, and (if `feedback_type == "thumbs_down"` and `clarification_count == 1`) the single follow-up `clarification_card`.

---

## 4. `GET /api/v1/products/compare` — Dynamic Model Battle Matrix

Compares 2–3 products side-by-side (`ComparisonMatrix.tsx`), combining category-adaptive technical `specs` from `products.csv` with live physical-store availability in Tehran from `offers.csv`.

### Query Parameters
- `product_ids`: Comma-separated product IDs (e.g., `102938,104921`) or `query=A55 vs Redmi Note 13 Pro`
- `lat`, `lng`: User coordinates

### Response Body (`200 OK`)
```json
{
  "category_name": "گوشی موبایل",
  "spec_keys": ["حافظه داخلی", "رم", "ظرفیت باتری", "دوربین اصلی"],
  "models": [
    {
      "product_id": 102938,
      "name": "گوشی سامسونگ Galaxy A55 5G ظرفیت 256/8 گیگابایت",
      "min_in_person_price_toman": 21450000,
      "open_stores_count": 14,
      "closest_open_shop": {
        "shop_id": 1102,
        "shop_name": "موبایل علاءالدین پلاس",
        "distance_km": 1.4,
        "price_toman": 21600000,
        "mall_badge_fa": "پاساژ علاءالدین، طبقه ۲، واحد ۲۱۴"
      },
      "specs": {
        "حافظه داخلی": "256 گیگابایت",
        "رم": "8 گیگابایت",
        "ظرفیت باتری": "5000 میلی‌آمپر ساعت",
        "دوربین اصلی": "50 مگاپیکسل"
      },
      "pros_fa": ["بدنه فلزی و شیشه‌ای مقاوم (IP67)", "موجود در ۱۴ فروشگاه باز اطراف شما"],
      "cons_fa": ["سرعت شارژ ۲۵ وات"]
    }
  ]
}
```

---

## 5. `GET /api/v1/stores/{offer_id}/fallback` — 1-Tap Alternative Store Rescue

Triggered by the **"مغازه بسته بود / موجود نداشت — جایگزین فوری"** button in `ShoppingCompanionModal.tsx` (`US4`). Immediately excludes the failed `shop_id`, boosts `w_distance` and `w_open_now`, and returns the nearest open alternative store stocking the same `product_id` (or closest same-category substitute).

### Query Parameters
- `lat`, `lng`: User's current live location (at the closed/out-of-stock shop)
- `excluded_shop_ids`: Comma-separated shop IDs already visited

### Response Body (`200 OK`)
```json
{
  "fallback_type": "exact_product_same_mall | exact_product_nearby | similar_product_nearby",
  "banner_fa": "جایگزین فوری در همان پاساژ (۱ طبقه بالاتر):",
  "alternative_store": {
    "offer_id": 1049912,
    "product_id": 8419201,
    "shop_id": 2208,
    "shop_name": "فروشگاه همراه نور",
    "price_toman": 1710000,
    "price_diff_toman": 30000,
    "distance_km": 0.05,
    "walking_minutes": 1,
    "mall_micro_guide": {
      "mall_name": "مجتمع تجاری نور تهران",
      "floor_label": "طبقه اول",
      "unit_label": "واحد ۴۵"
    },
    "is_open_now": true,
    "freshness_badge_fa": "بروزرسانی ۱ ساعت پیش",
    "primary_phone": "02188945678"
  }
}
```

---

## 6. `GET /api/v1/health` — Liara Readiness & Dataset Integrity Probe

Used for automated verification and Liara health checks.

```json
{
  "status": "ok",
  "postgres_pgvector_ready": true,
  "redis_ready": true,
  "counts": {
    "shops": 6476,
    "products": 225903,
    "offers": 331506,
    "real_torob_shops": 112
  },
  "jev_engine_mode": "typesafe_sdk | openai_compatible_system_one"
}
```
