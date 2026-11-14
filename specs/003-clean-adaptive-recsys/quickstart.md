# Quickstart & End-to-End Validation Guide (`003-clean-adaptive-recsys`)

**Feature**: Clean Two-Layer Adaptive Recommender System  
**Contracts Reference**: [contracts/recsys-api.md](contracts/recsys-api.md) | **Data Model Reference**: [data-model.md](data-model.md)

---

## 1. Prerequisites & Environment Setup

1. Ensure PostgreSQL (`pgvector` + `pg_trgm`) and Redis are running (or run pure math/unit & mocked contract suites directly via `.venv/bin/pytest`).
2. Verify `.env` contains valid model credentials and the cleaned RecSys thresholds from `.env.example` (`TYPESAFE_API_KEY`, `LLM_API_KEY`, `RECSYS_MENTION_SCORE_THRESHOLD=0.35`, `RECSYS_TRAIT_TRANSFER_NOUL_THRESHOLD=0.72`, `RECSYS_EPHEMERAL_GIFT_NOUL_THRESHOLD=0.60`).

```bash
# Run full automated test suite
.venv/bin/pytest -q

# Verify frontend production build & TypeScript contract alignment
cd UI_Template && npm run build
```

---

## 2. End-to-End Validation Scenarios

### Scenario 1: Selective Cross-Category Trait Transfer (`Laptop -> Phone`, SC-001 & SC-003)
1. Seed or run a session in `electronics` (`لپ‌تاپ`) recording mixed traits (`ابعاد صفحه: 15.6 اینچ`, `کیبورد: بک‌لایت`, `پنل: OLED`, `شارژدهی باتری: بالا`).
2. Start a new session for the same `user_id` with `message: "یه گوشی موبایل خوب معرفی کن"`.
3. **Expected Outcome**:
   - `15.6 اینچ` and `کیبورد بک‌لایت` are filtered out (`0%` leak).
   - `پنل OLED` and `شارژدهی بالا` are transferred as soft boosts (`6000mAh` semantically recognized without substring match).
   - Products lacking matching traits receive **zero** hallucinated `"منطبق با سلیقه شما"` badges.

### Scenario 2: Zero-Keyword Concept Expansion & Offer-Level `استوک` / Custom Mall (`SC-002` & `SC-004`)
1. Send `POST /api/v1/chat/turn` with conceptual phrasing (`"هدفونی که تو مترو صدای اطراف نیاد"`) or offer/location phrasing (`"لپ‌تاپ استوک می‌خوام، عصر برم سمت پاساژ چارسو حضوری بخرم"`).
2. **Expected Outcome**:
   - Concept expansion surfaces `ANC / حذف نویز` headphones without any hardcoded keyword list in Python.
   - `استوک` matches `offers.seller_title` / `offers.description`, and `w_offer_custom` boosts stores located in `پاساژ چارسو` into Top-3.
   - `stores[0..2]` physically place `best_overall`, `closest_open`, and `lowest_price` at positions 1, 2, and 3.

### Scenario 3: Gift Outlier Shield, Top-2 Inertia & `👎` Feedback Safety (`SC-005` & `SC-007`)
1. Send a gift query (`"می‌خوام برای تولد دوستم یه کفش ارزون هدیه بخرم"`) for a user with established `footwear_apparel` traits (`hit_count >= 5`) and high price percentile (`0.80`).
2. Send `POST /api/v1/feedback` with `feedback_type: "thumbs_down"`, then `feedback_type: "thumbs_up"` with `target_offer_id`.
3. **Expected Outcome**:
   - Gift session leaves long-term `user_trait_memory` and `price_percentiles_json` `100%` unchanged.
   - `thumbs_down` returns HTTP `200` with a clarification card and `0%` mutation on `store_weights_json`.
   - `thumbs_up` with `target_offer_id` returns HTTP `200` (zero `AttributeError`) and updates `store_weights_json` contrastively on non-gift sessions.

### Scenario 4: Dead-Code & `.env` Integrity Audit (`SC-006` & `SC-007`)
1. Verify zero references remain in `backend/` to `user_dynamic_slots`, `FIXED_SLOT_CATALOG`, `CandidateDynamicSpec`, `upsert_dynamic_spec_slots`, `compute_fusion_alpha`, `map_clarification_answers_to_deltas`, `_PARTICLES_FA`, `_ACCESSORY_CATEGORY_REGEX`, or `rerank_products_with_domain_traits`.
2. Verify `post_chat_turn` makes **zero** online calls to `embed_text_async`.
